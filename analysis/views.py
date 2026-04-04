import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
from django.conf import settings
from django.contrib.auth.decorators import login_required
from accounts.decorators import advanced_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from rating_developer.usgs import QUALITY_COLORS, fetch_measurements
from sites.models import Site
from water_balance.usgs import USGSAPIError, fetch_discharge, fetch_dv, fetch_gage_height, fetch_precipitation

from .forms import NewReportForm
from .models import AnalysisReport, PrecipCalibration, PrecipComparisonSite, StageQComparisonSite
from .report_types import REPORT_TYPES_BY_ID

# Colours for comparison sites on the chart (primary site always uses #0074D9)
_COMPARISON_COLORS = ['#FF4136', '#2ECC40', '#FF851B', '#B10DC9', '#FFDC00']

# Example report files per report type (relative to project root)
_EXAMPLE_FILES = {
    'precipitation': 'examples/precip/Precip Example.txt',
    'stage_discharge': 'examples/Stage_Q/Stage_Q_Analysis.txt',
    'groundwater': 'examples/GW/GW_Analysis.txt',
}
_BASE_DIR = Path(__file__).resolve().parent.parent


def _load_example(report_type: str) -> str:
    """Return the contents of the example file for a report type, or ''."""
    rel_path = _EXAMPLE_FILES.get(report_type, '')
    if not rel_path:
        return ''
    try:
        return (_BASE_DIR / rel_path).read_text(encoding='utf-8')
    except OSError:
        return ''


def _process_precip_site(site_no, start_dt, end_dt):
    """
    Fetch and process precipitation data for one site. Returns a dict with
    stats and daily totals, or sets 'error' on failure.
    """
    try:
        df = fetch_precipitation([site_no], start_dt, end_dt)
    except USGSAPIError as exc:
        return {'site_no': site_no, 'error': str(exc)}

    if df.is_empty():
        return {'site_no': site_no, 'error': 'No data found.'}

    unit = df['unit'][0]

    # Gap detection before filtering nulls
    df_sorted = df.sort('datetime')
    gaps_df = (
        df_sorted
        .with_columns([
            pl.col('datetime').shift(1).alias('gap_start'),
            pl.col('datetime').diff().dt.total_seconds().alias('gap_seconds'),
        ])
        .filter(pl.col('gap_seconds') > 2 * 3600)
        .select(['gap_start', 'gap_seconds'])
    )
    gaps = [
        {
            'start': row['gap_start'].strftime('%Y-%m-%d %H:%M UTC'),
            'duration_hours': f"{row['gap_seconds'] / 3600:.1f}",
        }
        for row in gaps_df.to_dicts()
        if row['gap_start'] is not None
    ]

    # Detect contiguous estimated periods (qualifier 'e') before filtering
    est_df = (
        df_sorted
        .filter(pl.col('qualifiers').str.contains(r'(?i)\be\b'))
        .sort('datetime')
    )
    estimated_periods = []
    if not est_df.is_empty():
        # Group into contiguous runs: new period when gap > 1 hour
        est_rows = est_df['datetime'].to_list()
        period_start = est_rows[0]
        period_end = est_rows[0]
        for dt in est_rows[1:]:
            gap_s = (dt - period_end).total_seconds()
            if gap_s > 3600:
                estimated_periods.append({
                    'start': period_start.strftime('%Y-%m-%d %H:%M UTC'),
                    'end': period_end.strftime('%Y-%m-%d %H:%M UTC'),
                    'duration_hours': f"{(period_end - period_start).total_seconds() / 3600:.1f}",
                })
                period_start = dt
            period_end = dt
        estimated_periods.append({
            'start': period_start.strftime('%Y-%m-%d %H:%M UTC'),
            'end': period_end.strftime('%Y-%m-%d %H:%M UTC'),
            'duration_hours': f"{(period_end - period_start).total_seconds() / 3600:.1f}",
        })

    # Drop nulls and negatives
    df = df.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))

    daily = (
        df.with_columns(pl.col('datetime').dt.date().alias('date'))
        .group_by('date')
        .agg(pl.col('value').sum().alias('total'))
        .sort('date')
    )

    if daily.is_empty():
        return {
            'site_no': site_no, 'unit': unit, 'total_precip': '0.00',
            'days_with_precip': 0, 'max_day': None, 'max_day_total': '0.00',
            'num_events': 0, 'min_event': '0.00', 'max_event': '0.00',
            'gaps': gaps, 'estimated_periods': estimated_periods,
            'daily_dates': [], 'daily_totals': [], 'table_rows': [], 'error': None,
        }

    total_precip = daily['total'].sum()
    days_with_precip = daily.filter(pl.col('total') > 0).height
    max_row = daily.sort('total', descending=True).row(0, named=True)

    # Compute rain events — contiguous runs of days with precip > 0
    daily_rows = daily.to_dicts()
    events = []
    current_event = 0.0
    in_event = False
    for row in daily_rows:
        if row['total'] > 0:
            current_event += row['total']
            in_event = True
        else:
            if in_event:
                events.append(current_event)
                current_event = 0.0
                in_event = False
    if in_event:
        events.append(current_event)

    num_events = len(events)
    min_event = f"{min(events):.2f}" if events else '0.00'
    max_event = f"{max(events):.2f}" if events else '0.00'

    return {
        'site_no': site_no,
        'unit': unit,
        'total_precip': f"{total_precip:.2f}",
        'days_with_precip': days_with_precip,
        'max_day': str(max_row['date']),
        'max_day_total': f"{max_row['total']:.2f}",
        'num_events': num_events,
        'min_event': min_event,
        'max_event': max_event,
        'gaps': gaps,
        'estimated_periods': estimated_periods,
        'daily_dates': [str(d) for d in daily['date'].to_list()],
        'daily_totals': daily['total'].to_list(),
        'table_rows': [
            {'date': str(r['date']), 'total': f"{r['total']:.2f}"}
            for r in daily.to_dicts()
            if r['total'] > 0
        ],
        'error': None,
    }


def _water_year_start(d):
    """Return the Oct 1 start date of the water year containing date d."""
    if d.month >= 10:
        return d.replace(month=10, day=1)
    return d.replace(year=d.year - 1, month=10, day=1)


def _water_years_intersecting(start_date, end_date):
    """
    Return list of (wy_start, wy_end, wy_label) for every water year that
    overlaps with the date range, regardless of whether it is 'closed out'.
    """
    result = []
    wy_s = _water_year_start(start_date)
    while wy_s <= end_date:
        wy_end = date(wy_s.year + 1, 9, 30)
        label = f"WY{(wy_s.year + 1) % 100:02d}"
        result.append((wy_s, wy_end, label))
        wy_s = date(wy_s.year + 1, 10, 1)
    return result


def _water_years_in_range(start_date, end_date):
    """
    Return list of (clip_start, wy_end, wy_label) for each water year that is
    'closed out' by the analysis period — i.e. the period includes Sep 30 of that WY.
    A period from 9/25/25 to 3/1/26 closes out WY25 (Sep 30, 2025 is within range).
    A period from 10/2/25 to 3/1/26 closes out nothing (Sep 30, 2026 is beyond range).
    """
    result = []
    wy_s = _water_year_start(start_date)
    while wy_s <= end_date:
        wy_end = date(wy_s.year + 1, 9, 30)
        # Only include this WY if its closing date (Sep 30) falls within the analysis period
        if start_date <= wy_end <= end_date:
            label = f"WY{(wy_s.year + 1) % 100:02d}"
            result.append((wy_s, wy_end, label))
        wy_s = date(wy_s.year + 1, 10, 1)
    return result


def _process_stage_q_site(site_no, start_dt, end_dt):
    """
    Fetch discharge IV and DV data for one comparison site.
    Returns a dict with stats and chart data, or sets 'error' on failure.
    """
    try:
        df_q = fetch_discharge([site_no], start_dt, end_dt)
        df_q_dv = fetch_dv([site_no], '00060', start_dt, end_dt)
    except USGSAPIError as exc:
        return {'site_no': site_no, 'error': str(exc)}

    df_clean = df_q.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))
    if df_clean.is_empty():
        return {'site_no': site_no, 'error': 'No data found.'}

    unit = df_clean['unit'][0]
    peak_row = df_clean.sort('value', descending=True).row(0, named=True)
    min_row = df_clean.sort('value').row(0, named=True)

    dv_clean = df_q_dv.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))
    if not dv_clean.is_empty():
        min_daily_row = dv_clean.sort('value').row(0, named=True)
        min_daily_value = f"{min_daily_row['value']:.2f}"
        min_daily_date = min_daily_row['date'].strftime('%m/%d/%Y')
    else:
        daily = (
            df_clean.with_columns(pl.col('datetime').dt.date().alias('date'))
            .group_by('date')
            .agg(pl.col('value').mean().alias('mean_val'))
            .sort('date')
        )
        min_daily_row = daily.sort('mean_val').row(0, named=True)
        min_daily_value = f"{min_daily_row['mean_val']:.2f}"
        min_daily_date = min_daily_row['date'].strftime('%m/%d/%Y')

    return {
        'site_no': site_no,
        'unit': unit,
        'peak_value': f"{peak_row['value']:.2f}",
        'peak_datetime': peak_row['datetime'].strftime('%m/%d/%Y %H:%M UTC'),
        'min_value': f"{min_row['value']:.2f}",
        'min_datetime': min_row['datetime'].strftime('%m/%d/%Y %H:%M UTC'),
        'min_daily_value': min_daily_value,
        'min_daily_date': min_daily_date,
        'datetimes': df_clean['datetime'].to_list(),
        'values': df_clean['value'].to_list(),
        'error': None,
    }


def _stage_q_context(report, comparison_sites=None):
    """
    Fetch stage and discharge IV data for a stage/discharge report.
    If the analysis period crosses a water-year boundary (Oct 1), the fetch
    is extended back to the start of the water year containing period_start.
    Returns a dict with stats for both parameters, or sets 'error'.
    """
    period_start = report.period_start
    period_end = report.period_end

    wy_start = _water_year_start(period_start)
    # Always extend to Oct 1 of the WY containing period_start so that
    # extremes computations (peak, min daily) cover the full water year.
    data_start = wy_start

    start_dt = datetime(data_start.year, data_start.month, data_start.day, tzinfo=timezone.utc)
    end_dt = datetime(period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc)
    site_no = report.site.site_no

    try:
        df_q = fetch_discharge([site_no], start_dt, end_dt)
        df_gh = fetch_gage_height([site_no], start_dt, end_dt)
        df_q_dv = fetch_dv([site_no], '00060', start_dt, end_dt)
        df_gh_dv = fetch_dv([site_no], '00065', start_dt, end_dt)
    except USGSAPIError as exc:
        return {'error': str(exc)}

    def _stats(df, label, unit_label, df_dv=None):
        df_clean = df.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))
        if df_clean.is_empty():
            return {'label': label, 'unit': unit_label, 'error': 'No data found.'}
        peak_row = df_clean.sort('value', descending=True).row(0, named=True)
        min_row = df_clean.sort('value').row(0, named=True)
        unit = df_clean['unit'][0]
        # Use official USGS daily values if available; fall back to IV-computed mean
        dv_clean = None
        if df_dv is not None:
            dv_clean = df_dv.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))
        if dv_clean is not None and not dv_clean.is_empty():
            min_daily_row = dv_clean.sort('value').row(0, named=True)
            min_daily_value = f"{min_daily_row['value']:.2f}"
            min_daily_date = min_daily_row['date'].strftime('%m/%d/%Y')
        else:
            daily = (
                df_clean.with_columns(pl.col('datetime').dt.date().alias('date'))
                .group_by('date')
                .agg(pl.col('value').mean().alias('mean_val'))
                .sort('date')
            )
            min_daily_row = daily.sort('mean_val').row(0, named=True)
            min_daily_value = f"{min_daily_row['mean_val']:.2f}"
            min_daily_date = min_daily_row['date'].strftime('%m/%d/%Y')
        return {
            'label': label,
            'unit': unit,
            'peak_value': f"{peak_row['value']:.2f}",
            'peak_datetime': peak_row['datetime'].strftime('%m/%d/%Y %H:%M UTC'),
            'min_value': f"{min_row['value']:.2f}",
            'min_datetime': min_row['datetime'].strftime('%m/%d/%Y %H:%M UTC'),
            'min_daily_value': min_daily_value,
            'min_daily_date': min_daily_date,
            'error': None,
        }

    # Analysis period stats (period_start to period_end only)
    period_start_dt = datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc)
    period_end_dt = datetime(period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc)
    df_q_period = df_q.filter((pl.col('datetime') >= period_start_dt) & (pl.col('datetime') <= period_end_dt))
    df_gh_period = df_gh.filter((pl.col('datetime') >= period_start_dt) & (pl.col('datetime') <= period_end_dt))
    df_q_dv_period = df_q_dv.filter((pl.col('date') >= period_start) & (pl.col('date') <= period_end))
    df_gh_dv_period = df_gh_dv.filter((pl.col('date') >= period_start) & (pl.col('date') <= period_end))
    discharge_stats = _stats(df_q_period, 'Discharge', 'cfs', df_dv=df_q_dv_period)
    stage_stats = _stats(df_gh_period, 'Gage Height', 'ft', df_dv=df_gh_dv_period)

    df_q_clean = df_q.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))
    df_gh_clean = df_gh.filter(pl.col('value').is_not_null() & (pl.col('value') >= 0))

    # Per-water-year stats for all WYs intersecting the analysis period
    wy_stats = []
    for wy_s, wy_e, wy_label in _water_years_intersecting(period_start, period_end):
        wy_start_dt = datetime(wy_s.year, wy_s.month, wy_s.day, tzinfo=timezone.utc)
        wy_end_dt = datetime(wy_e.year, wy_e.month, wy_e.day, 23, 59, 59, tzinfo=timezone.utc)
        df_q_wy = df_q.filter((pl.col('datetime') >= wy_start_dt) & (pl.col('datetime') <= wy_end_dt))
        df_gh_wy = df_gh.filter((pl.col('datetime') >= wy_start_dt) & (pl.col('datetime') <= wy_end_dt))
        df_q_dv_wy = df_q_dv.filter((pl.col('date') >= wy_s) & (pl.col('date') <= wy_e))
        df_gh_dv_wy = df_gh_dv.filter((pl.col('date') >= wy_s) & (pl.col('date') <= wy_e))
        q_stats = _stats(df_q_wy, 'Discharge', 'cfs', df_dv=df_q_dv_wy)
        gh_stats = _stats(df_gh_wy, 'Gage Height', 'ft', df_dv=df_gh_dv_wy)
        wy_stats.append({'wy_label': wy_label, 'discharge': q_stats, 'stage': gh_stats})

    # Build per-water-year extremes sentences
    extremes_by_wy = []
    if not df_q_clean.is_empty() and not df_gh_clean.is_empty():
        def fmt_q(v):
            return f"{v:,.0f}"

        for wy_start_d, wy_end_d, wy_label in _water_years_in_range(period_start, period_end):
            wy_start_dt = datetime(wy_start_d.year, wy_start_d.month, wy_start_d.day, tzinfo=timezone.utc)
            wy_end_dt = datetime(wy_end_d.year, wy_end_d.month, wy_end_d.day, 23, 59, 59, tzinfo=timezone.utc)
            df_q_wy = df_q_clean.filter(
                (pl.col('datetime') >= wy_start_dt) & (pl.col('datetime') <= wy_end_dt)
            )
            df_gh_wy = df_gh_clean.filter(
                (pl.col('datetime') >= wy_start_dt) & (pl.col('datetime') <= wy_end_dt)
            )
            if df_q_wy.is_empty() or df_gh_wy.is_empty():
                continue

            peak_q_row = df_q_wy.sort('value', descending=True).row(0, named=True)
            peak_q_dt_utc = peak_q_row['datetime']
            peak_q_val = peak_q_row['value']
            peak_q_dt_local = peak_q_dt_utc + timedelta(minutes=int(peak_q_row['tz_offset_min']))

            gh_sorted = df_gh_wy.with_columns(
                (pl.col('datetime') - peak_q_dt_utc).dt.total_seconds().abs().alias('diff_s')
            ).sort('diff_s')
            gh_at_peak_row = gh_sorted.row(0, named=True)
            gh_at_peak_q = gh_at_peak_row['value']

            df_dv_wy = df_q_dv.filter(
                (pl.col('date') >= wy_start_d) & (pl.col('date') <= wy_end_d)
                & pl.col('value').is_not_null()
            )
            if df_dv_wy.is_empty():
                continue
            daily_q = df_dv_wy.sort('value').row(0, named=True)

            peak_gh_row = df_gh_wy.sort('value', descending=True).row(0, named=True)
            peak_gh_dt_utc = peak_gh_row['datetime']
            peak_gh_val = peak_gh_row['value']
            peak_gh_dt_local = peak_gh_dt_utc + timedelta(minutes=int(peak_gh_row['tz_offset_min']))

            def _fmt_date(dt):
                return f"{dt.strftime('%b.')} {dt.day}"

            parts = [
                f"Maximum discharge, {fmt_q(peak_q_val)} ft\u00b3/s, "
                f"{_fmt_date(peak_q_dt_local)}, "
                f"gage height, {gh_at_peak_q:.2f} ft.",
                f"Maximum gage height, {peak_gh_val:.2f} ft, "
                f"{_fmt_date(peak_gh_dt_local)}.",
                f"Minimum daily discharge, {fmt_q(daily_q['value'])} ft\u00b3/s, "
                f"{_fmt_date(daily_q['date'])}.",
            ]
            extremes_by_wy.append({'wy_label': wy_label, 'sentence': ' '.join(parts)})

    # Fetch comparison site data
    comparisons = []
    if comparison_sites:
        for cs in comparison_sites:
            comparisons.append(_process_stage_q_site(cs.site.site_no, start_dt, end_dt))

    # Field measurements filtered to the analysis period
    measurements = []
    measurements_summary = None
    period_start_str = period_start.strftime('%Y-%m-%d')
    period_end_str = period_end.strftime('%Y-%m-%d')
    try:
        all_meas = fetch_measurements(site_no)
        measurements = [
            {**m, 'stage': f"{m['stage']:.2f}", 'quality_color': QUALITY_COLORS.get(m['quality'], '#AAAAAA')}
            for m in all_meas
            if period_start_str <= m['date'] <= period_end_str
        ]
        if measurements:
            discharges = [m['discharge'] for m in measurements]
            measurements_summary = {
                'count': len(measurements),
                'min_q': f"{min(discharges):,.2f}",
                'max_q': f"{max(discharges):,.2f}",
            }
    except USGSAPIError:
        pass

    # Build dual-axis chart
    fig = go.Figure()
    if not df_q_clean.is_empty():
        fig.add_trace(go.Scatter(
            x=df_q_clean['datetime'].to_list(),
            y=df_q_clean['value'].to_list(),
            name=f'{site_no} Discharge (cfs)',
            mode='lines',
            line=dict(color='#0074D9', width=1.5),
            yaxis='y1',
        ))
    for i, comp in enumerate(comparisons):
        if not comp['error']:
            color = _COMPARISON_COLORS[i % len(_COMPARISON_COLORS)]
            fig.add_trace(go.Scatter(
                x=comp['datetimes'],
                y=comp['values'],
                name=f"{comp['site_no']} Discharge (cfs)",
                mode='lines',
                line=dict(color=color, width=1.5),
                yaxis='y1',
            ))
    if not df_gh_clean.is_empty():
        fig.add_trace(go.Scatter(
            x=df_gh_clean['datetime'].to_list(),
            y=df_gh_clean['value'].to_list(),
            name=f'{site_no} Gage Height (ft)',
            mode='lines',
            line=dict(color='#FF851B', width=1.5),
            yaxis='y2',
        ))
    # Shade the analysis period if data was extended
    if data_start < period_start:
        analysis_start_dt = datetime(
            period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc
        )
        fig.add_vrect(
            x0=start_dt, x1=analysis_start_dt,
            fillcolor='#AAAAAA', opacity=0.12,
            layer='below', line_width=0,
            annotation_text='Prior WY', annotation_position='top left',
            annotation_font_size=11, annotation_font_color='#666',
        )
    fig.update_layout(
        margin=dict(l=60, r=60, t=20, b=40),
        height=300,
        xaxis=dict(showgrid=True, gridcolor='#eee'),
        yaxis=dict(title='Discharge (cfs)', showgrid=True, gridcolor='#eee', zeroline=False),
        yaxis2=dict(title='Gage Height (ft)', overlaying='y', side='right', zeroline=False, showgrid=False),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
    )
    chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn', config={'displayModeBar': False})

    return {
        'data_start': data_start.strftime('%m/%d/%Y'),
        'data_end': period_end.strftime('%m/%d/%Y'),
        'period_start': period_start.strftime('%m/%d/%Y'),
        'period_end': period_end.strftime('%m/%d/%Y'),
        'extended': data_start < period_start,
        'discharge': discharge_stats,
        'stage': stage_stats,
        'wy_stats': wy_stats,
        'extremes_by_wy': extremes_by_wy,
        'comparisons': comparisons,
        'measurements': measurements,
        'measurements_summary': measurements_summary,
        'chart_html': chart_html,
        'error': None,
    }


def _precip_context(report, comparison_sites):
    """
    Fetch precipitation data for the primary site and all comparison sites.
    Returns a dict with a combined chart and per-site stats.
    """
    start_dt = datetime(
        report.period_start.year, report.period_start.month, report.period_start.day,
        tzinfo=timezone.utc,
    )
    end_dt = datetime(
        report.period_end.year, report.period_end.month, report.period_end.day,
        23, 59, 59, tzinfo=timezone.utc,
    )

    primary = _process_precip_site(report.site.site_no, start_dt, end_dt)
    if primary['error']:
        return {'error': primary['error']}

    comparisons = [
        _process_precip_site(cs.site.site_no, start_dt, end_dt)
        for cs in comparison_sites
    ]

    # Build combined grouped bar chart
    unit = primary['unit']
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=f"{report.site.site_no} (primary)",
        x=primary['daily_dates'],
        y=primary['daily_totals'],
        marker_color='#0074D9',
    ))
    for i, comp in enumerate(comparisons):
        if not comp['error']:
            color = _COMPARISON_COLORS[i % len(_COMPARISON_COLORS)]
            fig.add_trace(go.Bar(
                name=comp['site_no'],
                x=comp['daily_dates'],
                y=comp['daily_totals'],
                marker_color=color,
            ))
    fig.update_layout(
        barmode='group',
        margin=dict(l=40, r=20, t=20, b=40),
        height=260,
        xaxis_title='Date',
        yaxis_title=f'Precipitation ({unit})',
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor='#eee'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
    )
    chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn', config={'displayModeBar': False})

    # Build combined daily totals table across all sites
    all_dates = sorted(set(primary['daily_dates']) | {
        d for comp in comparisons if not comp['error'] for d in comp['daily_dates']
    })
    primary_by_date = dict(zip(primary['daily_dates'], primary['daily_totals']))
    comp_by_date = [
        dict(zip(comp['daily_dates'], comp['daily_totals']))
        for comp in comparisons if not comp['error']
    ]
    active_comparisons = [comp for comp in comparisons if not comp['error']]
    daily_table_rows = []
    for date in all_dates:
        primary_val = primary_by_date.get(date, 0)
        comp_vals = [f"{d.get(date, 0):.2f}" for d in comp_by_date]
        # Only include rows where at least one site has precip
        if primary_val > 0 or any(float(v) > 0 for v in comp_vals):
            daily_table_rows.append({
                'date': date,
                'primary': f"{primary_val:.2f}",
                'comparisons': comp_vals,
            })

    return {
        'chart_html': chart_html,
        'unit': unit,
        'primary': primary,
        'comparisons': comparisons,
        'daily_table_rows': daily_table_rows,
        'error': None,
    }


def _get_precip_data(report):
    """
    Fetch precipitation data for a report's primary site and all comparison sites.
    Returns (primary_dict, comparisons_list, calibrations_list).
    primary_dict will have an 'error' key if data is unavailable.
    """
    start_dt = datetime(
        report.period_start.year, report.period_start.month, report.period_start.day,
        tzinfo=timezone.utc,
    )
    end_dt = datetime(
        report.period_end.year, report.period_end.month, report.period_end.day,
        23, 59, 59, tzinfo=timezone.utc,
    )
    primary = _process_precip_site(report.site.site_no, start_dt, end_dt)
    calibrations = list(report.precip_calibrations.all())
    comparison_site_objs = list(
        report.precip_comparison_sites.select_related('site').all()
    )
    comparisons = [
        _process_precip_site(cs.site.site_no, start_dt, end_dt)
        for cs in comparison_site_objs
    ]
    return primary, comparisons, calibrations


def _stream_ai_response(prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    with client.messages.stream(
        model='claude-opus-4-5',
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}],
    ) as stream:
        for text in stream.text_stream:
            escaped = text.replace('\n', '\\n')
            yield f'data: {escaped}\n\n'
    yield 'data: [DONE]\n\n'


def _stream_ai_all_sections(prompt):
    """
    Stream all-sections AI response. Scans for [SECTION:key] markers in the
    output and emits a special §SECTION:key control line so the frontend can
    route text into the correct textarea.
    """
    import anthropic
    import re
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    MARKER_RE = re.compile(r'\[SECTION:([^\]]+)\]')
    buffer = ''

    with client.messages.stream(
        model='claude-opus-4-5',
        max_tokens=4096,
        messages=[{'role': 'user', 'content': prompt}],
    ) as stream:
        for text in stream.text_stream:
            buffer += text
            # Flush complete markers from the front of the buffer
            while True:
                m = MARKER_RE.search(buffer)
                if not m:
                    break
                before = buffer[:m.start()]
                if before:
                    yield f'data: {before.replace(chr(10), "\\n")}\n\n'
                yield f'data: \u00a7SECTION:{m.group(1)}\n\n'
                buffer = buffer[m.end():]

    if buffer:
        yield f'data: {buffer.replace(chr(10), "\\n")}\n\n'
    yield 'data: [DONE]\n\n'


@login_required
@advanced_required
def index(request):
    return render(request, 'analysis/index.html', {
        'in_progress': AnalysisReport.objects.filter(user=request.user, is_complete=False).select_related('site'),
        'completed': AnalysisReport.objects.filter(user=request.user, is_complete=True).select_related('site'),
    })


@login_required
def new_report(request):
    if request.method == 'POST':
        form = NewReportForm(request.POST)
        if form.is_valid():
            site_no = form.cleaned_data['site_no'].strip()
            try:
                site = Site.get_or_fetch(site_no)
            except USGSAPIError as exc:
                form.add_error('site_no', str(exc))
            else:
                existing = AnalysisReport.objects.filter(
                    user=request.user,
                    site=site,
                    period_start=form.cleaned_data['period_start'],
                    period_end=form.cleaned_data['period_end'],
                ).first()
                if existing:
                    form.add_error(None, f"A report already exists for this site and date range. "
                                        f"Opening the existing report.")
                    return redirect('analysis_detail', pk=existing.pk)
                report = AnalysisReport.objects.create(
                    user=request.user,
                    site=site,
                    report_type=form.cleaned_data['report_type'],
                    period_start=form.cleaned_data['period_start'],
                    period_end=form.cleaned_data['period_end'],
                )
                return redirect('analysis_detail', pk=report.pk)
    else:
        form = NewReportForm()
    return render(request, 'analysis/new_report.html', {'form': form})


@login_required
def report_detail(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    sections = [
        {
            'key': s['key'],
            'title': s['title'],
            'guidance': s['guidance'],
            'text': report.section_data.get(s['key'], ''),
        }
        for s in rt.get('sections', [])
    ]

    site_data = None
    calibrations = []
    comparison_sites = []
    if report.report_type == 'stage_discharge':
        comparison_sites = list(
            report.stage_q_comparison_sites.select_related('site').all()
        )
        site_data = _stage_q_context(report, comparison_sites)
    elif report.report_type == 'precipitation':
        comparison_sites = list(
            report.precip_comparison_sites.select_related('site').all()
        )
        site_data = _precip_context(report, comparison_sites)
        calibrations = [
            {
                'id': c.pk,
                'date': str(c.date),
                'desired_tips': c.desired_tips,
                'actual_tips': c.actual_tips,
                'error_pct': f"{c.error_pct():+.1f}%" if c.error_pct() is not None else '—',
            }
            for c in report.precip_calibrations.all()
        ]

    return render(request, 'analysis/report_detail.html', {
        'report': report,
        'sections': sections,
        'completion_pct': report.completion_pct(),
        'can_ai_assist': request.user.has_perm('analysis.can_use_ai_assist'),
        'site_data': site_data,
        'calibrations': calibrations,
        'comparison_sites': comparison_sites,
    })


@login_required
@require_POST
def toggle_complete(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    report.is_complete = not report.is_complete
    report.save(update_fields=['is_complete', 'updated_at'])
    return redirect('analysis_detail', pk=report.pk)


@login_required
@require_POST
def delete_report(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    report.delete()
    return redirect('analysis_index')


@login_required
@require_POST
def update_dates(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    period_start = request.POST.get('period_start', '').strip()
    period_end = request.POST.get('period_end', '').strip()
    if period_start and period_end:
        conflict = AnalysisReport.objects.filter(
            user=request.user,
            site=report.site,
            period_start=period_start,
            period_end=period_end,
        ).exclude(pk=pk).first()
        if conflict:
            return redirect('analysis_detail', pk=conflict.pk)
        report.period_start = period_start
        report.period_end = period_end
        report.save(update_fields=['period_start', 'period_end', 'updated_at'])
    return redirect('analysis_detail', pk=report.pk)


@login_required
@require_POST
def add_comparison_site(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    try:
        body = json.loads(request.body)
        site_no = body.get('site_no', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    if not site_no:
        return JsonResponse({'ok': False, 'error': 'Site number required.'}, status=400)

    if site_no == report.site.site_no:
        return JsonResponse({'ok': False, 'error': 'That is the primary site.'}, status=400)

    try:
        site = Site.get_or_fetch(site_no)
    except USGSAPIError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    comp, created = PrecipComparisonSite.objects.get_or_create(report=report, site=site)
    if not created:
        return JsonResponse({'ok': False, 'error': f'{site_no} is already in the comparison list.'}, status=400)

    return JsonResponse({'ok': True, 'id': comp.pk, 'site_no': site.site_no, 'site_name': site.name})


@login_required
@require_POST
def delete_comparison_site(request, pk, comp_pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    comp = get_object_or_404(PrecipComparisonSite, pk=comp_pk, report=report)
    comp.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def add_stage_q_comparison_site(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    try:
        body = json.loads(request.body)
        site_no = body.get('site_no', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    if not site_no:
        return JsonResponse({'ok': False, 'error': 'Site number required.'}, status=400)

    if site_no == report.site.site_no:
        return JsonResponse({'ok': False, 'error': 'That is the primary site.'}, status=400)

    try:
        site = Site.get_or_fetch(site_no)
    except USGSAPIError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    comp, created = StageQComparisonSite.objects.get_or_create(report=report, site=site)
    if not created:
        return JsonResponse({'ok': False, 'error': f'{site_no} is already in the comparison list.'}, status=400)

    return JsonResponse({'ok': True, 'id': comp.pk, 'site_no': site.site_no, 'site_name': site.name})


@login_required
@require_POST
def delete_stage_q_comparison_site(request, pk, comp_pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    comp = get_object_or_404(StageQComparisonSite, pk=comp_pk, report=report)
    comp.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def add_calibration(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    try:
        body = json.loads(request.body)
        date_val = datetime.strptime(body['date'], '%Y-%m-%d').date()
        desired_tips = float(body['desired_tips'])
        actual_tips = float(body['actual_tips'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    cal = PrecipCalibration.objects.create(
        report=report,
        date=date_val,
        desired_tips=desired_tips,
        actual_tips=actual_tips,
    )
    error_pct = cal.error_pct()
    return JsonResponse({
        'ok': True,
        'id': cal.pk,
        'date': str(cal.date),
        'desired_tips': cal.desired_tips,
        'actual_tips': cal.actual_tips,
        'error_pct': f"{error_pct:+.1f}%" if error_pct is not None else '—',
    })


@login_required
@require_POST
def delete_calibration(request, pk, cal_pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    cal = get_object_or_404(PrecipCalibration, pk=cal_pk, report=report)
    cal.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def autosave(request, pk):
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    valid_keys = {s['key'] for s in rt.get('sections', [])}

    try:
        body = json.loads(request.body)
        section_key = body.get('section_key', '')
        text = body.get('text', '')
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    if section_key not in valid_keys:
        return JsonResponse({'ok': False, 'error': 'Invalid section key'}, status=400)

    report.section_data[section_key] = text
    report.save(update_fields=['section_data', 'updated_at'])
    return JsonResponse({'ok': True, 'completion_pct': report.completion_pct()})


@login_required
@require_POST
def ai_assist(request, pk, section_key):
    if not request.user.has_perm('analysis.can_use_ai_assist'):
        return HttpResponseForbidden('AI assist permission required.')

    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    sections = rt.get('sections', [])
    valid_keys = {s['key'] for s in sections}

    if section_key not in valid_keys:
        return HttpResponseForbidden('Invalid section key.')

    section_def = next(s for s in sections if s['key'] == section_key)

    # Build context from other completed sections
    other_sections = []
    for s in sections:
        if s['key'] != section_key:
            text = report.section_data.get(s['key'], '').strip()
            if text:
                other_sections.append(f"--- {s['title']} ---\n{text}")
    other_sections_text = '\n\n'.join(other_sections) if other_sections else 'None yet.'

    # For precipitation reports, include observed data in the prompt
    precip_data_text = ''
    if report.report_type == 'precipitation':
        primary, _, calibrations = _get_precip_data(report)

        if not primary.get('error'):
            lines = [
                "PRECIPITATION DATA SUMMARY",
                f"  Total precipitation: {primary['total_precip']} {primary['unit']}",
                f"  Days with precipitation: {primary['days_with_precip']}",
                f"  Largest single day: {primary['max_day']} ({primary['max_day_total']} {primary['unit']})",
            ]

            # Daily totals (non-zero days only)
            if primary['table_rows']:
                lines.append("  Daily totals (non-zero days):")
                for row in primary['table_rows']:
                    lines.append(f"    {row['date']}: {row['total']} {primary['unit']}")

            # Data gaps
            if primary['gaps']:
                lines.append(f"  Data gaps (>{2}h with no readings): {len(primary['gaps'])}")
                for g in primary['gaps']:
                    lines.append(f"    Starting {g['start']}, duration {g['duration_hours']} hours")
            else:
                lines.append("  Data gaps: none")

            # Estimated periods
            if primary['estimated_periods']:
                lines.append(f"  Estimated data periods: {len(primary['estimated_periods'])}")
                for ep in primary['estimated_periods']:
                    lines.append(f"    {ep['start']} to {ep['end']} ({ep['duration_hours']} hours)")
            else:
                lines.append("  Estimated data periods: none")

            # Calibrations
            if calibrations:
                lines.append("  Tipping-bucket calibrations:")
                for cal in calibrations:
                    err = cal.error_pct()
                    err_str = f"{err:+.1f}%" if err is not None else "N/A"
                    lines.append(
                        f"    {cal.date}: desired {cal.desired_tips} tips, "
                        f"actual {cal.actual_tips} tips, error {err_str}"
                    )
            else:
                lines.append("  Tipping-bucket calibrations: none recorded")

            precip_data_text = '\n'.join(lines)

    data_section = f"\nObserved data:\n{precip_data_text}\n\n" if precip_data_text else ''

    prompt = (
        f"You are assisting a USGS hydrographer in writing a formal station analysis report.\n\n"
        f"Site: {report.site.site_no} — {report.site.name}\n"
        f"Report type: {report.get_report_type_display()}\n"
        f"Analysis period: {report.period_start} to {report.period_end}\n"
        f"{data_section}"
        f"You are drafting the section: \"{section_def['title']}\"\n\n"
        f"Section guidance:\n{section_def['guidance']}\n\n"
        f"Previously completed sections for context:\n{other_sections_text}\n\n"
        f"Write a professional draft for this section. Use plain prose appropriate for an "
        f"official USGS hydrological report. Do not include a section heading — write only "
        f"the body text. Where specific data or field observations would normally be cited, "
        f"indicate them with bracketed placeholders like [measurement number] or [date]. "
        f"Where actual observed data has been provided above, use those specific values."
    )

    return StreamingHttpResponse(
        _stream_ai_response(prompt),
        content_type='text/event-stream',
    )


def _build_all_sections_prompt(report):
    """Build the full AI prompt for all sections of a report."""
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    sections = rt.get('sections', [])

    # Stage/discharge data block
    stage_q_data_text = ''
    if report.report_type == 'stage_discharge':
        ctx = _stage_q_context(report)
        if not ctx.get('error'):
            lines = [f"STAGE/DISCHARGE DATA ({ctx['data_start']} to {ctx['data_end']})"]
            if ctx['extended']:
                lines.append(
                    f"  Note: data extended back to water year start "
                    f"({ctx['data_start']}) because the analysis period crosses Oct 1."
                )
            for key in ('discharge', 'stage'):
                s = ctx[key]
                if s.get('error'):
                    lines.append(f"  {s['label']}: {s['error']}")
                else:
                    lines.append(f"  {s['label']} ({s['unit']}):")
                    lines.append(f"    Peak: {s['peak_value']} on {s['peak_datetime']}")
                    lines.append(f"    Minimum instantaneous: {s['min_value']} on {s['min_datetime']}")
                    lines.append(f"    Minimum daily mean: {s['min_daily_value']} on {s['min_daily_date']}")
            if ctx.get('extremes_by_wy'):
                lines.append("\n  AUTO-GENERATED EXTREMES (use only this text for the Extremes section — do not alter or add to it):")
                for wy in ctx['extremes_by_wy']:
                    lines.append(f"  Extremes for {wy['wy_label']}: {wy['sentence']}")
            else:
                lines.append("\n  EXTREMES: The analysis period does not close out any water year. Leave the Extremes section blank.")
            stage_q_data_text = '\n'.join(lines)

    # Precipitation data block
    precip_data_text = ''
    if report.report_type == 'precipitation':
        primary, comparisons, calibrations = _get_precip_data(report)

        if not primary.get('error'):
            lines = [
                "PRECIPITATION DATA SUMMARY",
                f"  Primary site: {report.site.site_no} — {report.site.name}",
                f"  Total precipitation: {primary['total_precip']} {primary['unit']}",
                f"  Rain events: {primary['num_events']} (ranging from {primary['min_event']} to {primary['max_event']} {primary['unit']})",
                f"  Days with precipitation: {primary['days_with_precip']}",
                f"  Largest single day: {primary['max_day']} ({primary['max_day_total']} {primary['unit']})",
            ]
            if primary['table_rows']:
                lines.append("  Daily totals (non-zero days):")
                for row in primary['table_rows']:
                    lines.append(f"    {row['date']}: {row['total']} {primary['unit']}")
            lines.append(f"  Data gaps (>2h): {len(primary['gaps'])}" if primary['gaps'] else "  Data gaps: none")
            for g in primary['gaps']:
                lines.append(f"    Starting {g['start']}, duration {g['duration_hours']} hours")
            lines.append(f"  Estimated data periods: {len(primary['estimated_periods'])}" if primary['estimated_periods'] else "  Estimated data periods: none")
            for ep in primary['estimated_periods']:
                lines.append(f"    {ep['start']} to {ep['end']} ({ep['duration_hours']} hours)")
            if calibrations:
                lines.append("  Tipping-bucket calibrations:")
                for cal in calibrations:
                    err = cal.error_pct()
                    err_str = f"{err:+.1f}%" if err is not None else "N/A"
                    lines.append(
                        f"    {cal.date}: desired {cal.desired_tips} tips, "
                        f"actual {cal.actual_tips} tips, error {err_str}"
                    )
            else:
                lines.append("  Tipping-bucket calibrations: none recorded")

            # Comparison sites
            if comparisons:
                lines.append("\nCOMPARISON SITES (for hyetographic comparison):")
                for comp in comparisons:
                    if comp.get('error'):
                        lines.append(f"  Site {comp['site_no']}: data unavailable ({comp['error']})")
                    else:
                        lines.append(f"  Site {comp['site_no']}:")
                        lines.append(f"    Total precipitation: {comp['total_precip']} {comp['unit']}")
                        lines.append(f"    Days with precipitation: {comp['days_with_precip']}")
                        lines.append(f"    Largest single day: {comp['max_day']} ({comp['max_day_total']} {comp['unit']})")
                        if comp['table_rows']:
                            lines.append("    Daily totals (non-zero days):")
                            for row in comp['table_rows']:
                                lines.append(f"      {row['date']}: {row['total']} {comp['unit']}")
            else:
                lines.append("\nCOMPARISON SITES: none added")

            precip_data_text = '\n'.join(lines)

    observed_data = stage_q_data_text or precip_data_text
    data_section = f"\nObserved data:\n{observed_data}\n\n" if observed_data else ''

    section_instructions = []
    for s in sections:
        existing = report.section_data.get(s['key'], '').strip()
        existing_text = existing if existing else '(empty — generate from scratch)'
        section_instructions.append(
            f"[SECTION:{s['key']}]\n"
            f"Title: {s['title']}\n"
            f"Guidance: {s['guidance']}\n"
            f"Current text: {existing_text}"
        )
    sections_block = '\n\n'.join(section_instructions)

    # Example / guidance file for this report type
    example_text = _load_example(report.report_type)
    if example_text:
        label = (
            "EXAMPLE REPORT (for tone and style reference only — do not copy its data)"
            if report.report_type == 'precipitation'
            else "SECTION GUIDANCE (use this to understand what each section should contain)"
        )
        example_block = f"\n{label}:\n{example_text}\n"
    else:
        example_block = ''

    return (
        f"You are assisting a USGS hydrographer in writing a formal station analysis report.\n\n"
        f"Site: {report.site.site_no} — {report.site.name}\n"
        f"Report type: {report.get_report_type_display()}\n"
        f"Analysis period: {report.period_start} to {report.period_end}\n"
        f"{data_section}"
        f"{example_block}\n"
        f"Your task is to write or improve ALL sections of this report. "
        f"For sections that already have text, refine and improve it. "
        f"For empty sections, generate appropriate content from scratch.\n\n"
        f"CRITICAL RULES:\n"
        f"1. Only use data values that are explicitly provided in the 'Observed data' section above. "
        f"Do not invent, estimate, or assume any numbers, dates, or measurements.\n"
        f"2. Where information is genuinely not available in the provided data, use a bracketed "
        f"placeholder such as [value], [date], or [describe here].\n"
        f"3. Match the concise, factual tone of the example report above. Sections should be "
        f"short and direct — typically one to three sentences.\n"
        f"4. Do not include section headings in the output text.\n"
        f"5. For the Hyetographic Comparison section, use the comparison site totals and daily "
        f"data provided above to describe how the primary site compares to nearby sites. "
        f"If no comparison sites are listed, use a [site number] placeholder.\n"
        f"6. Format all dates as mm/dd/yyyy (e.g. 03/26/2026) or mm/dd where the year is clear "
        f"from context. Do not use ISO format (yyyy-mm-dd).\n"
        f"7. The Precipitation Record section must include a summary sentence in this form: "
        f"\"Total rain was X.XX inches during this period with Y rain events occurring ranging "
        f"from A.AA to Z.ZZ in.\" Use the actual values from the observed data.\n\n"
        f"OUTPUT FORMAT: For each section, output the marker (e.g. [SECTION:precipitation_record]) "
        f"on its own line, then immediately write the section body text.\n\n"
        f"Sections to write:\n\n{sections_block}"
    )


@login_required
@require_POST
def ai_assist_all(request, pk):
    if not request.user.has_perm('analysis.can_use_ai_assist'):
        return HttpResponseForbidden('AI assist permission required.')

    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    if not rt.get('sections'):
        return HttpResponseForbidden('No sections for this report type.')

    prompt = _build_all_sections_prompt(report)
    return StreamingHttpResponse(
        _stream_ai_all_sections(prompt),
        content_type='text/event-stream',
    )


@login_required
def export_prompt(request, pk):
    """Return the AI prompt as plain text so it can be pasted into Claude.ai."""
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    prompt = _build_all_sections_prompt(report)
    filename = f"prompt_{report.site.site_no}_{report.period_start}_{report.period_end}.txt"
    response = HttpResponse(prompt, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _build_copilot_prompt(report):
    """
    Build a prompt optimised for Microsoft Copilot (GPT-based).
    Differences from the Claude prompt:
    - No [SECTION:key] routing markers
    - Markdown ## headings for each section so output is easy to copy
    - Explicit instruction to suppress preamble / closing remarks
    - Plain formatting instead of XML or ALL-CAPS blocks
    """
    rt = REPORT_TYPES_BY_ID.get(report.report_type, {})
    sections = rt.get('sections', [])

    # ---- Reuse the same data-gathering logic as the Claude prompt ----
    stage_q_data_text = ''
    if report.report_type == 'stage_discharge':
        ctx = _stage_q_context(report)
        if not ctx.get('error'):
            lines = [f"## Observed Stage/Discharge Data ({ctx['data_start']} to {ctx['data_end']})"]
            if ctx['extended']:
                lines.append(
                    f"*Data extended back to water year start ({ctx['data_start']}) "
                    f"because the analysis period crosses Oct 1.*"
                )
            for key in ('discharge', 'stage'):
                s = ctx[key]
                if s.get('error'):
                    lines.append(f"- **{s['label']}:** {s['error']}")
                else:
                    lines.append(f"\n**{s['label']} ({s['unit']}):**")
                    lines.append(f"- Peak: {s['peak_value']} on {s['peak_datetime']}")
                    lines.append(f"- Minimum instantaneous: {s['min_value']} on {s['min_datetime']}")
                    lines.append(f"- Minimum daily mean: {s['min_daily_value']} on {s['min_daily_date']}")
            if ctx.get('extremes_by_wy'):
                lines.append("\n**Auto-generated Extremes (use only this text for the Extremes section — do not alter or add to it):**")
                for wy in ctx['extremes_by_wy']:
                    lines.append(f"- Extremes for {wy['wy_label']}: {wy['sentence']}")
            else:
                lines.append("\n**Extremes:** The analysis period does not close out any water year. Leave the Extremes section blank.")
            stage_q_data_text = '\n'.join(lines)

    precip_data_text = ''
    if report.report_type == 'precipitation':
        primary, comparisons, calibrations = _get_precip_data(report)

        if not primary.get('error'):
            lines = [
                "## Observed Precipitation Data",
                f"**Primary site:** {report.site.site_no} — {report.site.name}",
                f"- Total precipitation: {primary['total_precip']} {primary['unit']}",
                f"- Rain events: {primary['num_events']} (ranging from {primary['min_event']} to {primary['max_event']} {primary['unit']})",
                f"- Days with precipitation: {primary['days_with_precip']}",
                f"- Largest single day: {primary['max_day']} ({primary['max_day_total']} {primary['unit']})",
            ]
            if primary['table_rows']:
                lines.append("\nDaily totals (non-zero days):")
                for row in primary['table_rows']:
                    lines.append(f"- {row['date']}: {row['total']} {primary['unit']}")
            lines.append(f"\nData gaps (>2 h): {len(primary['gaps'])}" if primary['gaps'] else "\nData gaps: none")
            for g in primary['gaps']:
                lines.append(f"- Starting {g['start']}, duration {g['duration_hours']} h")
            lines.append(f"\nEstimated data periods: {len(primary['estimated_periods'])}" if primary['estimated_periods'] else "\nEstimated data periods: none")
            for ep in primary['estimated_periods']:
                lines.append(f"- {ep['start']} to {ep['end']} ({ep['duration_hours']} h)")
            if calibrations:
                lines.append("\nTipping-bucket calibrations:")
                for cal in calibrations:
                    err = cal.error_pct()
                    err_str = f"{err:+.1f}%" if err is not None else "N/A"
                    lines.append(f"- {cal.date}: desired {cal.desired_tips} tips, actual {cal.actual_tips} tips, error {err_str}")
            else:
                lines.append("\nTipping-bucket calibrations: none recorded")

            if comparisons:
                lines.append("\n**Comparison sites (for hyetographic comparison):**")
                for comp in comparisons:
                    if comp.get('error'):
                        lines.append(f"- Site {comp['site_no']}: data unavailable ({comp['error']})")
                    else:
                        lines.append(f"\n**Site {comp['site_no']}:**")
                        lines.append(f"- Total precipitation: {comp['total_precip']} {comp['unit']}")
                        lines.append(f"- Days with precipitation: {comp['days_with_precip']}")
                        lines.append(f"- Largest single day: {comp['max_day']} ({comp['max_day_total']} {comp['unit']})")
                        if comp['table_rows']:
                            lines.append("  Daily totals (non-zero days):")
                            for row in comp['table_rows']:
                                lines.append(f"  - {row['date']}: {row['total']} {comp['unit']}")
            else:
                lines.append("\nComparison sites: none added")

            precip_data_text = '\n'.join(lines)

    observed_data = stage_q_data_text or precip_data_text
    data_section = f"\n{observed_data}\n\n" if observed_data else ''

    # ---- Section instructions with markdown headings ----
    section_instructions = []
    for s in sections:
        existing = report.section_data.get(s['key'], '').strip()
        existing_text = existing if existing else '(empty — generate from scratch)'
        section_instructions.append(
            f"### {s['title']}\n"
            f"**Guidance:** {s['guidance']}\n"
            f"**Current text:** {existing_text}"
        )
    sections_block = '\n\n'.join(section_instructions)

    # ---- Example / guidance block ----
    example_text = _load_example(report.report_type)
    if example_text:
        label = (
            "## Example Report (tone and style reference only — do not copy its data)"
            if report.report_type == 'precipitation'
            else "## Section Guidance (use this to understand what each section should contain)"
        )
        example_block = f"{label}\n\n{example_text}\n\n"
    else:
        example_block = ''

    return (
        f"You are assisting a USGS hydrographer in writing a formal station analysis report.\n\n"
        f"**Site:** {report.site.site_no} — {report.site.name}\n"
        f"**Report type:** {report.get_report_type_display()}\n"
        f"**Analysis period:** {report.period_start} to {report.period_end}\n"
        f"{data_section}"
        f"{example_block}"
        f"## Instructions\n\n"
        f"Write or improve all sections of this report. "
        f"For sections that already have text, refine and improve it. "
        f"For empty sections, generate appropriate content from scratch.\n\n"
        f"**Rules:**\n"
        f"1. Only use data values explicitly provided in the observed data above. Do not invent, estimate, or assume any numbers, dates, or measurements.\n"
        f"2. Where information is not available, use a bracketed placeholder such as [value], [date], or [describe here].\n"
        f"3. Match the concise, factual tone of the example above. Sections should be short and direct — typically one to three sentences.\n"
        f"4. For the Hyetographic Comparison section, use the comparison site data provided above.\n"
        f"5. Output each section using a markdown heading (## Section Title) followed immediately by the body text.\n"
        f"6. Do not include any introductory remarks, summaries, or closing text — output only the sections.\n"
        f"7. Format all dates as mm/dd/yyyy (e.g. 03/26/2026) or mm/dd where the year is clear "
        f"from context. Do not use ISO format (yyyy-mm-dd).\n"
        f"8. The Precipitation Record section must include a summary sentence in this form: "
        f"\"Total rain was X.XX inches during this period with Y rain events occurring ranging "
        f"from A.AA to Z.ZZ in.\" Use the actual values from the observed data.\n\n"
        f"## Sections to Write\n\n{sections_block}"
    )


@login_required
def export_prompt_copilot(request, pk):
    """Return a Copilot-optimised prompt as plain text."""
    report = get_object_or_404(AnalysisReport, pk=pk, user=request.user)
    prompt = _build_copilot_prompt(report)
    filename = f"prompt_copilot_{report.site.site_no}_{report.period_start}_{report.period_end}.txt"
    response = HttpResponse(prompt, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
