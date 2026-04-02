import json

import plotly.graph_objects as go
import plotly.io as pio
from django.contrib.auth.decorators import login_required
from accounts.decorators import advanced_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from sites.models import Site
from water_balance.usgs import USGSAPIError

from .models import RatingConfig
from .usgs import (
    QUALITY_COLORS,
    QUALITY_ORDER,
    fetch_measurements,
    fetch_rating_table,
    parse_manual_rating,
)


def _build_rating_chart(rating_curve, rating_points, measurements, hidden_nos):
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

    # Traces 1–N: one per quality group
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

    fig.update_layout(
        margin=dict(l=60, r=20, t=30, b=60),
        height=500,
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
        legend=dict(x=1.02, xanchor='left', y=1, yanchor='top'),
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

    # Build chart
    chart_html = _build_rating_chart(rating_curve, rating_points, measurements, config.hidden_measurement_nos)

    # Date filter (table only, client-side — passed through for form persistence)
    filter_start = request.GET.get('filter_start', '')
    filter_end = request.GET.get('filter_end', '')

    hidden_set = set(str(n) for n in config.hidden_measurement_nos)

    return render(request, 'rating_developer/detail.html', {
        'config': config,
        'chart_html': chart_html,
        'rating_points': rating_points,
        'rating_curve': rating_curve,
        'measurements': measurements,
        'all_measurements_json': json.dumps(measurements),
        'hidden_nos_json': json.dumps(list(hidden_set)),
        'quality_colors': QUALITY_COLORS,
        'quality_order': QUALITY_ORDER,
        'quality_colors_json': json.dumps(QUALITY_COLORS),
        'quality_order_json': json.dumps(QUALITY_ORDER),
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
