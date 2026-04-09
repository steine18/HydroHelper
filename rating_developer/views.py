import json
from datetime import date, datetime, timedelta, timezone

import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
from django.contrib.auth.decorators import login_required
from accounts.decorators import advanced_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from sites.models import Site
from water_balance.usgs import USGSAPIError, fetch_gage_height

from .models import RatingConfig
from .usgs import (
    QUALITY_COLORS,
    QUALITY_ORDER,
    fetch_measurements,
    fetch_rating_table,
    parse_manual_rating,
)

# Colours for cross-site measurement traces on the chart
_CROSS_SITE_COLORS = ['#9B59B6', '#1ABC9C', '#E91E63', '#FF5722', '#607D8B']


def _interpolate_gh(iv_records, target_dt):
    """
    Linearly interpolate GH from a sorted list of IV record dicts at target_dt.
    iv_records must be sorted by 'datetime' (UTC-aware). target_dt must also be UTC-aware.
    Returns interpolated float, or None if no records bracket the target.
    """
    before = [(r['datetime'], r['value']) for r in iv_records
              if r['datetime'] <= target_dt and r['value'] is not None]
    after  = [(r['datetime'], r['value']) for r in iv_records
              if r['datetime'] >= target_dt and r['value'] is not None]
    if not before and not after:
        return None
    if not before:
        return after[0][1]
    if not after:
        return before[-1][1]
    t0, v0 = before[-1]
    t1, v1 = after[0]
    if t0 == t1:
        return v0
    frac = (target_dt - t0).total_seconds() / (t1 - t0).total_seconds()
    return v0 + frac * (v1 - v0)


def _fetch_cross_site_points(config):
    """
    For each entry in config.cross_site_configs, fetch discharge field measurements
    from the secondary site and pair each one with the primary site's GH IV at
    (measurement_time + offset_minutes).
    Returns a list of dicts:
      {site_no, label, offset_minutes, points: [{number, date, discharge, gh, quality}], error}
    """
    results = []
    for cfg in config.cross_site_configs:
        site_no        = cfg['site_no']
        offset_minutes = int(cfg.get('offset_minutes', 0))
        label          = cfg.get('label') or site_no

        try:
            raw_meas = fetch_measurements(site_no)
        except USGSAPIError as exc:
            results.append({'site_no': site_no, 'label': label, 'offset_minutes': offset_minutes,
                            'points': [], 'error': str(exc)})
            continue

        # Apply configurable date range; default to last 6 months / today
        date_start = cfg.get('date_start') or (date.today() - timedelta(days=183)).strftime('%Y-%m-%d')
        date_end   = cfg.get('date_end')   or date.today().strftime('%Y-%m-%d')
        raw_meas = [m for m in raw_meas if date_start <= m.get('date', '') <= date_end]

        # Filter to measurements that have a full timestamp (len > 10 means more than just date)
        timed = []
        for m in raw_meas:
            t = m.get('time', '')
            if not t or len(t) <= 10:
                continue
            try:
                dt_utc = datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(timezone.utc)
                timed.append((m, dt_utc))
            except (ValueError, AttributeError):
                continue

        if not timed:
            results.append({'site_no': site_no, 'label': label, 'offset_minutes': offset_minutes,
                            'points': [], 'error': 'No timestamped measurements found for this site.'})
            continue

        # Date range for primary-site GH IV fetch (add buffer for the offset + rounding)
        offset_td = timedelta(minutes=offset_minutes)
        all_target_dts = [dt + offset_td for _, dt in timed]
        gh_start = min(all_target_dts) - timedelta(hours=2)
        gh_end   = max(all_target_dts) + timedelta(hours=2)

        try:
            df_gh = fetch_gage_height([config.site.site_no], gh_start, gh_end)
        except USGSAPIError as exc:
            results.append({'site_no': site_no, 'label': label, 'offset_minutes': offset_minutes,
                            'points': [], 'error': f'Could not fetch primary site GH: {exc}'})
            continue

        df_gh_clean = df_gh.filter(pl.col('value').is_not_null())
        if df_gh_clean.is_empty():
            results.append({'site_no': site_no, 'label': label, 'offset_minutes': offset_minutes,
                            'points': [], 'error': 'No gage height data for primary site in this period.'})
            continue

        iv_records = df_gh_clean.sort('datetime').to_dicts()

        hidden_set_local = set(str(n) for n in cfg.get('hidden_nos', []))

        points = []
        for m, meas_dt in timed:
            target_dt = meas_dt + offset_td
            gh = _interpolate_gh(iv_records, target_dt)
            if gh is None:
                continue
            meas_no_str = str(m['number'])
            points.append({
                'number':    m['number'],
                'date':      m['date'],
                'discharge': m['discharge'],
                'gh':        round(gh, 2),
                'quality':   m['quality'],
                'hidden':    meas_no_str in hidden_set_local,
            })

        results.append({
            'site_no':        site_no,
            'label':          label,
            'offset_minutes': offset_minutes,
            'date_start':     cfg.get('date_start', ''),
            'date_end':       cfg.get('date_end', ''),
            'hidden_nos':     list(cfg.get('hidden_nos', [])),
            'points':         points,
            'error':          None,
        })
    return results


def _build_rating_chart(rating_curve, rating_points, measurements, hidden_nos, cross_site_data=None):
    hidden_set = set(str(n) for n in hidden_nos)
    fig = go.Figure()

    # Trace 0: Interpolated rating line (no markers)
    if rating_curve:
        fig.add_trace(go.Scatter(
            x=[p['discharge'] for p in rating_curve],
            y=[p['stage'] for p in rating_curve],
            mode='lines',
            name='Rating Curve',
            line=dict(color='#111111', width=2),
            hoverinfo='skip',
        ))
    else:
        fig.add_trace(go.Scatter(x=[], y=[], mode='lines', name='Rating Curve'))

    # Trace 1: Base control points (markers only)
    if rating_points:
        fig.add_trace(go.Scatter(
            x=[p['discharge'] for p in rating_points],
            y=[p['stage'] for p in rating_points],
            mode='markers',
            name='Control Points',
            marker=dict(color='#111111', size=8, symbol='diamond'),
        ))
    else:
        fig.add_trace(go.Scatter(x=[], y=[], mode='markers', name='Control Points'))

    # Traces 2–6: one per quality group (primary site measurements)
    for quality in QUALITY_ORDER:
        color = QUALITY_COLORS[quality]
        pts = [m for m in measurements if m['quality'] == quality and str(m['number']) not in hidden_set]
        fig.add_trace(go.Scatter(
            x=[p['discharge'] for p in pts],
            y=[p['stage'] for p in pts],
            mode='markers',
            name=quality,
            marker=dict(color=color, size=8, line=dict(width=1, color='white')),
            text=[
                f"#{p['number']} — {p['date']}<br>"
                f"Q: {p['discharge']} cfs<br>"
                f"GH: {p['stage']} ft<br>"
                f"{p['quality']}"
                for p in pts
            ],
            hoverinfo='text',
        ))

    # Traces 7+: cross-site transferred measurement points (triangle-up markers)
    for i, cs in enumerate(cross_site_data or []):
        color = _CROSS_SITE_COLORS[i % len(_CROSS_SITE_COLORS)]
        pts = [p for p in cs.get('points', []) if not p.get('hidden')]
        offset_label = (
            f"+{cs['offset_minutes']} min" if cs['offset_minutes'] >= 0
            else f"{cs['offset_minutes']} min"
        )
        fig.add_trace(go.Scatter(
            x=[p['discharge'] for p in pts],
            y=[p['gh'] for p in pts],
            mode='markers',
            name=f"{cs['label']} ({offset_label})",
            marker=dict(color=color, size=9, symbol='triangle-up', line=dict(width=1, color='white')),
            text=[
                f"#{p['number']} — {p['date']}<br>"
                f"Q: {p['discharge']:.2f} cfs (at {cs['site_no']})<br>"
                f"GH: {p['gh']} ft (primary site, {offset_label})<br>"
                f"{p['quality']}"
                for p in pts
            ],
            hoverinfo='text',
        ))

    fig.update_layout(
        margin=dict(l=60, r=20, t=30, b=120),
        height=540,
        xaxis=dict(
            title='Discharge (cfs)',
            type='log',
            showgrid=True,
            gridcolor='#eee',
            zeroline=False,
        ),
        yaxis=dict(title='Gage Height (ft)', showgrid=True, gridcolor='#eee'),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='closest',
        legend=dict(
            orientation='h',
            yanchor='top', y=-0.18,
            xanchor='center', x=0.5,
            font=dict(size=11),
        ),
    )

    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs='cdn',
        div_id='rating-chart-plotly',
        config={'displayModeBar': True},
    )


@login_required
@advanced_required
def index(request):
    configs = RatingConfig.objects.filter(user=request.user).select_related('site')
    return render(request, 'rating_developer/index.html', {'configs': configs})


@login_required
@require_POST
def new_config(request):
    site_no = request.POST.get('site_no', '').strip()
    if not site_no:
        return redirect('rating_index')
    try:
        site = Site.get_or_fetch(site_no)
    except USGSAPIError as exc:
        configs = RatingConfig.objects.filter(user=request.user).select_related('site')
        return render(request, 'rating_developer/index.html', {
            'configs': configs,
            'error': str(exc),
            'site_no': site_no,
        })
    config = RatingConfig.objects.create(
        user=request.user,
        site=site,
        name=f"{site.site_no} Rating",
    )
    return redirect('rating_detail', pk=config.pk)


@login_required
def detail(request, pk):
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)

    # Fetch rating
    rating_points = []   # base control points — table + markers on chart
    rating_curve = []    # full EXSA table — interpolated line on chart
    rating_error = None
    if config.use_manual_rating and config.manual_rating_text:
        rating_points = parse_manual_rating(config.manual_rating_text)
        rating_curve = rating_points
        if not rating_points:
            rating_error = "Could not parse manual rating table."
    else:
        try:
            rating_curve = fetch_rating_table(config.site.site_no, file_type='exsa')
            rating_points = fetch_rating_table(config.site.site_no, file_type='base')
        except USGSAPIError as exc:
            rating_error = str(exc)

    # Fetch measurements
    measurements = []
    meas_error = None
    try:
        measurements = fetch_measurements(config.site.site_no)
    except USGSAPIError as exc:
        meas_error = str(exc)

    # Fetch cross-site transferred measurement points
    cross_site_data = _fetch_cross_site_points(config)

    # Build chart
    chart_html = _build_rating_chart(
        rating_curve, rating_points, measurements,
        config.hidden_measurement_nos, cross_site_data,
    )

    # Date filter (table only, client-side — passed through for form persistence)
    filter_start = request.GET.get('filter_start', '')
    filter_end = request.GET.get('filter_end', '')

    hidden_set = set(str(n) for n in config.hidden_measurement_nos)

    # Strip 'time' key from measurements before serialising to JSON (not needed client-side)
    measurements_for_js = [
        {k: v for k, v in m.items() if k != 'time'}
        for m in measurements
    ]

    return render(request, 'rating_developer/detail.html', {
        'config': config,
        'chart_html': chart_html,
        'rating_points': rating_points,
        'rating_curve': rating_curve,
        'measurements': measurements,
        'all_measurements_json': json.dumps(measurements_for_js),
        'hidden_nos_json': json.dumps(list(hidden_set)),
        'quality_colors': QUALITY_COLORS,
        'quality_order': QUALITY_ORDER,
        'quality_colors_json': json.dumps(QUALITY_COLORS),
        'quality_order_json': json.dumps(QUALITY_ORDER),
        'cross_site_data': cross_site_data,
        'cross_site_data_json': json.dumps(cross_site_data),
        'rating_error': rating_error,
        'meas_error': meas_error,
        'filter_start': filter_start,
        'filter_end': filter_end,
    })


@login_required
@require_POST
def update_config(request, pk):
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)

    # AJAX name update
    if request.content_type and 'json' in request.content_type:
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
        if 'name' in body:
            name = body['name'].strip()
            if name:
                config.name = name
                config.save(update_fields=['name', 'updated_at'])
        return JsonResponse({'ok': True})

    # Form POST: rating source change
    use_manual = request.POST.get('use_manual_rating') == '1'
    manual_text = request.POST.get('manual_rating_text', '').strip()
    config.use_manual_rating = use_manual
    config.manual_rating_text = manual_text
    config.save(update_fields=['use_manual_rating', 'manual_rating_text', 'updated_at'])
    return redirect('rating_detail', pk=config.pk)


@login_required
@require_POST
def toggle_measurement(request, pk):
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)
    try:
        body = json.loads(request.body)
        meas_no = str(body['measurement_no'])
        hide = bool(body['hidden'])
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    hidden = [str(n) for n in config.hidden_measurement_nos]
    if hide and meas_no not in hidden:
        hidden.append(meas_no)
    elif not hide and meas_no in hidden:
        hidden.remove(meas_no)

    config.hidden_measurement_nos = hidden
    config.save(update_fields=['hidden_measurement_nos', 'updated_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def add_cross_site(request, pk):
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)
    try:
        body = json.loads(request.body)
        site_no        = body.get('site_no', '').strip()
        offset_minutes = int(body.get('offset_minutes', 0))
        label          = body.get('label', '').strip()
    except (json.JSONDecodeError, ValueError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    if not site_no:
        return JsonResponse({'ok': False, 'error': 'Site number required.'}, status=400)
    if site_no == config.site.site_no:
        return JsonResponse({'ok': False, 'error': 'That is the primary site.'}, status=400)
    if any(c['site_no'] == site_no for c in config.cross_site_configs):
        return JsonResponse({'ok': False, 'error': f'{site_no} is already configured.'}, status=400)

    try:
        site = Site.get_or_fetch(site_no)
    except USGSAPIError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    entry = {
        'site_no':        site.site_no,
        'offset_minutes': offset_minutes,
        'label':          label or f"{site.site_no} — {site.name}",
        'hidden_nos':     [],
    }
    config.cross_site_configs = list(config.cross_site_configs) + [entry]
    config.save(update_fields=['cross_site_configs', 'updated_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def remove_cross_site(request, pk):
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)
    try:
        body    = json.loads(request.body)
        site_no = body.get('site_no', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    config.cross_site_configs = [c for c in config.cross_site_configs if c['site_no'] != site_no]
    config.save(update_fields=['cross_site_configs', 'updated_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def update_cross_site(request, pk):
    """Update editable fields (offset_minutes, date_start, date_end) for a cross-site config entry."""
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)
    try:
        body    = json.loads(request.body)
        site_no = body.get('site_no', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    updates = {}
    if 'offset_minutes' in body:
        try:
            updates['offset_minutes'] = int(body['offset_minutes'])
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'Invalid offset.'}, status=400)
    for field in ('date_start', 'date_end'):
        if field in body:
            val = body[field]
            updates[field] = val.strip() if val else ''

    updated = []
    found = False
    for c in config.cross_site_configs:
        if c['site_no'] == site_no:
            updated.append({**c, **updates})
            found = True
        else:
            updated.append(c)

    if not found:
        return JsonResponse({'ok': False, 'error': 'Site not found in config.'}, status=404)

    config.cross_site_configs = updated
    config.save(update_fields=['cross_site_configs', 'updated_at'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def toggle_cross_site_measurement(request, pk):
    """Show/hide an individual transferred measurement point on the chart."""
    config = get_object_or_404(RatingConfig, pk=pk, user=request.user)
    try:
        body    = json.loads(request.body)
        site_no = body.get('site_no', '').strip()
        meas_no = str(body.get('measurement_no', ''))
        hide    = bool(body.get('hidden', False))
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    updated = []
    for c in config.cross_site_configs:
        if c['site_no'] == site_no:
            hidden = [str(n) for n in c.get('hidden_nos', [])]
            if hide and meas_no not in hidden:
                hidden.append(meas_no)
            elif not hide and meas_no in hidden:
                hidden.remove(meas_no)
            updated.append({**c, 'hidden_nos': hidden})
        else:
            updated.append(c)

    config.cross_site_configs = updated
    config.save(update_fields=['cross_site_configs', 'updated_at'])
    return JsonResponse({'ok': True})
