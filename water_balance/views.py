from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import polars as pl
import plotly.graph_objects as go
import plotly.io as pio
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from sites.models import Site
from .models import FlowBalanceConfig
from .usgs import USGSAPIError, fetch_discharge, fetch_site_names, shift_time_of_travel


def _apply_discharge_offset(values, offset, offset_type):
    """Apply an absolute (cfs) or percentage discharge offset to a Polars Series."""
    if offset == 0:
        return values
    if offset_type == "pct":
        return values * (1 + offset / 100)
    return values + offset


def _fetch_and_process_member(member, start_dt, end_dt):
    """
    Fetch a single comparison member, apply time-of-travel shift and discharge
    offset, and return a two-column DataFrame (datetime, value).
    """
    buffered_start = start_dt - timedelta(minutes=member["offset_minutes"])
    df = fetch_discharge([member["site_no"]], buffered_start, end_dt)
    site_df = df.filter(df["site_no"] == member["site_no"])

    if member["offset_minutes"] != 0:
        site_df = shift_time_of_travel(site_df, member["offset_minutes"])

    if member["discharge_offset"] != 0:
        site_df = site_df.with_columns(
            _apply_discharge_offset(
                site_df["value"],
                member["discharge_offset"],
                member["offset_type"],
            ).alias("value")
        )

    return site_df.select(["datetime", "value"])


def _build_table(primary_df, comp_traces):
    """
    Build a table dict (headers + rows) aligned to primary timestamps.
    comp_traces is a list of (label, df) where df has (datetime, value) columns.
    Comparison values are joined to primary timestamps via join_asof (nearest).
    """
    table = primary_df.select([
        pl.col("datetime"),
        pl.col("value").alias("primary_cfs"),
    ]).sort("datetime")

    col_info = []
    for i, (label, df) in enumerate(comp_traces):
        cfs_col  = f"c{i}_cfs"
        diff_col = f"c{i}_diff"
        pct_col  = f"c{i}_pct"
        table = table.join_asof(
            df.sort("datetime").select([pl.col("datetime"), pl.col("value").alias(cfs_col)]),
            on="datetime",
            strategy="nearest",
        ).with_columns([
            (pl.col(cfs_col) - pl.col("primary_cfs")).alias(diff_col),
            pl.when(pl.col("primary_cfs") != 0)
              .then((pl.col(cfs_col) - pl.col("primary_cfs")) / pl.col("primary_cfs") * 100)
              .otherwise(None)
              .alias(pct_col),
        ])
        col_info.append((label, cfs_col, diff_col, pct_col))

    headers = ["Datetime (UTC)", "Primary (cfs)"]
    for label, _, _, _ in col_info:
        headers += [f"{label} (cfs)", "Diff (cfs)", "Diff (%)"]

    rows = []
    for row in table.iter_rows(named=True):
        r = [
            row["datetime"].strftime("%Y-%m-%d %H:%M"),
            f"{row['primary_cfs']:.1f}" if row["primary_cfs"] is not None else "—",
        ]
        for _, cfs_col, diff_col, pct_col in col_info:
            cfs  = row.get(cfs_col)
            diff = row.get(diff_col)
            pct  = row.get(pct_col)
            r.append(f"{cfs:.1f}"  if cfs  is not None else "—")
            r.append(f"{diff:+.1f}" if diff is not None else "—")
            r.append(f"{pct:+.1f}%" if pct  is not None else "—")
        rows.append(r)

    return {"headers": headers, "rows": rows}


def _build_composite(members, start_dt, end_dt):
    """
    Fetch all members of a composite group, apply their individual shifts and
    discharge offsets, then sum/subtract them into a single (datetime, value) DataFrame.
    Timestamps are outer-joined so every reading from any member is represented.
    Members with no reading at a given timestamp contribute 0.
    """
    frames = []
    for i, member in enumerate(members):
        col = f"v{i}"
        site_df = _fetch_and_process_member(member, start_dt, end_dt)
        sign = -1 if member["operation"] == "-" else 1
        frames.append(
            site_df.with_columns((pl.col("value") * sign).alias(col)).select(["datetime", col])
        )

    composite = frames[0]
    for frame in frames[1:]:
        composite = composite.join(frame, on="datetime", how="outer_coalesce").sort("datetime")

    value_cols = [f"v{i}" for i in range(len(frames))]
    composite = composite.with_columns(
        pl.sum_horizontal([pl.col(c).fill_null(0) for c in value_cols]).alias("value")
    ).select(["datetime", "value"])

    return composite


def flow_balance_index(request):
    site_number = request.GET.get("site", "").strip()
    if site_number:
        return redirect("flow_balance", site_number=site_number)
    saved_configs = []
    if request.user.is_authenticated:
        saved_configs = FlowBalanceConfig.objects.filter(user=request.user).select_related('primary_site')
    return render(request, "water_balance/flow_balance_index.html", {"saved_configs": saved_configs})


@login_required
@require_POST
def save_flow_balance(request, site_number):
    name = request.POST.get("config_name", "").strip()
    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)

    site = Site.get_or_fetch(site_number)

    comparison = []
    compare_sites   = request.POST.getlist("compare_site")
    compare_offsets = request.POST.getlist("compare_offset")
    compare_dis     = request.POST.getlist("compare_discharge_offset")
    compare_types   = request.POST.getlist("compare_offset_type")
    compare_ops     = request.POST.getlist("compare_operation")
    compare_groups  = request.POST.getlist("compare_group")

    for i, s in enumerate(compare_sites):
        s = s.strip()
        if not s:
            continue
        comparison.append({
            "site_no":          s,
            "offset_minutes":   float(compare_offsets[i]) if i < len(compare_offsets) else 0,
            "discharge_offset": float(compare_dis[i])     if i < len(compare_dis)     else 0,
            "offset_type":      compare_types[i]          if i < len(compare_types)   else "abs",
            "operation":        compare_ops[i]            if i < len(compare_ops)     else "+",
            "group":            compare_groups[i].strip() if i < len(compare_groups)  else "",
        })

    start_str = request.POST.get("start", "")
    end_str   = request.POST.get("end",   "")

    config, created = FlowBalanceConfig.objects.update_or_create(
        user=request.user,
        name=name,
        defaults=dict(
            primary_site     = site,
            start_date       = start_str or None,
            end_date         = end_str   or None,
            show_band        = bool(request.POST.get("show_band")),
            error_pct        = float(request.POST.get("error_pct", 10)),
            comparison_sites = comparison,
        ),
    )
    return JsonResponse({"ok": True, "created": created, "id": config.pk, "name": config.name})


def load_flow_balance(request, config_id):
    config = get_object_or_404(FlowBalanceConfig, pk=config_id, user=request.user)
    params = config.to_querystring()
    # Build query string manually to support repeated keys
    parts = []
    for key, val in params.items():
        if isinstance(val, list):
            for v in val:
                parts.append((key, v))
        elif val:
            parts.append((key, val))
    qs = urlencode(parts)
    return redirect(f"/flowbalance/{config.primary_site.site_no}/?{qs}")


@login_required
@require_POST
def delete_flow_balance(request, config_id):
    config = get_object_or_404(FlowBalanceConfig, pk=config_id, user=request.user)
    config.delete()
    return JsonResponse({"ok": True})


def flow_balance(request, site_number):
    # --- Date range ---
    now = datetime.now(timezone.utc)
    default_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    default_end = now.strftime("%Y-%m-%d")

    start_str = request.GET.get("start", default_start)
    end_str = request.GET.get("end", default_end)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        start_dt = datetime.strptime(default_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(default_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_str, end_str = default_start, default_end

    # --- Error band ---
    band_submitted = "band_submitted" in request.GET
    show_band = (not band_submitted) or ("show_band" in request.GET)
    try:
        error_pct = float(request.GET.get("error_pct", 10))
        if error_pct < 0:
            error_pct = 0.0
    except ValueError:
        error_pct = 10.0

    # --- Parse comparison sites ---
    compare_sites        = request.GET.getlist("compare_site")
    compare_offsets      = request.GET.getlist("compare_offset")
    compare_dis_offsets  = request.GET.getlist("compare_discharge_offset")
    compare_offset_types = request.GET.getlist("compare_offset_type")
    compare_operations   = request.GET.getlist("compare_operation")
    compare_groups       = request.GET.getlist("compare_group")

    comparison = []
    for i, (site, offset) in enumerate(zip(compare_sites, compare_offsets)):
        site = site.strip()
        if not site:
            continue
        try:
            offset_min = float(offset)
        except (ValueError, TypeError):
            offset_min = 0.0
        try:
            dis_offset = float(compare_dis_offsets[i]) if i < len(compare_dis_offsets) else 0.0
        except (ValueError, TypeError):
            dis_offset = 0.0

        offset_type = compare_offset_types[i] if i < len(compare_offset_types) else "abs"
        if offset_type not in ("abs", "pct"):
            offset_type = "abs"

        operation = compare_operations[i] if i < len(compare_operations) else "+"
        if operation not in ("+", "-"):
            operation = "+"

        group = compare_groups[i].strip() if i < len(compare_groups) else ""

        comparison.append({
            "site_no": site,
            "offset_minutes": offset_min,
            "discharge_offset": dis_offset,
            "offset_type": offset_type,
            "operation": operation,
            "group": group,
        })

    # --- Fetch and plot ---
    error = None
    plot_html = None
    site_name = None
    table_data = None

    try:
        site_name = fetch_site_names([site_number]).get(site_number)

        # Primary site
        primary_df = fetch_discharge([site_number], start_dt, end_dt)
        primary = primary_df.filter(primary_df["site_no"] == site_number)
        datetimes = primary["datetime"].to_list()
        values = primary["value"].to_list()

        fig = go.Figure()

        # Error band — rendered first so it sits behind everything
        if show_band:
            lower = (primary["value"] * (1 - error_pct / 100)).to_list()
            upper = (primary["value"] * (1 + error_pct / 100)).to_list()
            band_color = "rgba(31, 119, 180, 0.15)"
            line_invisible = dict(width=0)
            fig.add_trace(go.Scatter(
                x=datetimes, y=lower,
                mode="lines", line=line_invisible,
                showlegend=False, hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=datetimes, y=upper,
                mode="lines", line=line_invisible,
                fill="tonexty", fillcolor=band_color,
                name=f"±{error_pct:g}% band", hoverinfo="skip",
            ))

        fig.add_trace(go.Scatter(
            x=datetimes, y=values,
            name=f"{site_number} (primary)",
            mode="lines", line=dict(width=2),
        ))

        # Separate individuals from composite groups
        individuals = [c for c in comparison if not c["group"]]
        groups = {}
        for c in comparison:
            if c["group"]:
                groups.setdefault(c["group"], []).append(c)

        comp_traces = []  # (label, df) for table building

        # Individual comparison sites
        for comp in individuals:
            site_df = _fetch_and_process_member(comp, start_dt, end_dt)
            label_parts = []
            if comp["offset_minutes"]:
                label_parts.append(f"{comp['offset_minutes']:+.0f} min")
            if comp["discharge_offset"] != 0:
                if comp["offset_type"] == "pct":
                    label_parts.append(f"{comp['discharge_offset']:+.1f}%")
                else:
                    label_parts.append(f"{comp['discharge_offset']:+.1f} cfs")
            label = comp["site_no"]
            if label_parts:
                label += f" ({', '.join(label_parts)})"
            fig.add_trace(go.Scatter(
                x=site_df["datetime"].to_list(),
                y=site_df["value"].to_list(),
                name=label, mode="lines", line=dict(width=2),
            ))
            comp_traces.append((label, site_df))

        # Composite groups
        for group_name, members in groups.items():
            composite_df = _build_composite(members, start_dt, end_dt)
            fig.add_trace(go.Scatter(
                x=composite_df["datetime"].to_list(),
                y=composite_df["value"].to_list(),
                name=group_name, mode="lines", line=dict(width=2),
            ))
            comp_traces.append((group_name, composite_df))

        fig.update_layout(
            xaxis=dict(title="Date / Time (UTC)", range=[start_dt, end_dt]),
            yaxis_title="Discharge (ft³/s)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(t=60, b=40, l=60, r=20),
            hovermode="x unified",
        )

        plot_html = pio.to_html(fig, full_html=False, include_plotlyjs="cdn")
        table_data = _build_table(primary, comp_traces)

    except USGSAPIError as exc:
        error = str(exc)

    # --- Site map ---
    map_html = None
    all_site_nos = {site_number} | {c["site_no"] for c in comparison if c["site_no"]}
    site_meta = {}
    for sno in all_site_nos:
        try:
            s = Site.get_or_fetch(sno)
            if s.latitude and s.longitude:
                site_meta[sno] = {"name": s.name, "lat": s.latitude, "lon": s.longitude}
        except USGSAPIError:
            pass

    if site_meta:
        map_fig = go.Figure()

        if site_number in site_meta:
            m = site_meta[site_number]
            map_fig.add_trace(go.Scattermap(
                lat=[m["lat"]], lon=[m["lon"]],
                text=[f"{site_number}: {m['name']}"],
                mode="markers+text",
                marker=dict(size=14, color="#00843D"),
                textposition="top right",
                showlegend=False,
                hovertemplate="%{text}<extra></extra>",
            ))

        comp_lats, comp_lons, comp_texts = [], [], []
        for comp in comparison:
            sno = comp["site_no"]
            if sno in site_meta and sno != site_number:
                m = site_meta[sno]
                comp_lats.append(m["lat"])
                comp_lons.append(m["lon"])
                comp_texts.append(f"{sno}: {m['name']}")

        if comp_lats:
            map_fig.add_trace(go.Scattermap(
                lat=comp_lats, lon=comp_lons, text=comp_texts,
                mode="markers+text",
                marker=dict(size=10, color="#1f77b4"),
                textposition="top right",
                showlegend=False,
                hovertemplate="%{text}<extra></extra>",
            ))

        # Compute center and zoom from site bounds
        all_lats = [v["lat"] for v in site_meta.values()]
        all_lons = [v["lon"] for v in site_meta.values()]
        center_lat = (max(all_lats) + min(all_lats)) / 2
        center_lon = (max(all_lons) + min(all_lons)) / 2
        lat_span = max(all_lats) - min(all_lats)
        lon_span = max(all_lons) - min(all_lons)
        span = max(lat_span, lon_span, 0.05)
        import math
        zoom = max(1, min(13, round(math.log2(360 / span) - 1)))

        map_fig.update_layout(
            map=dict(
                style="open-street-map",
                center=dict(lat=center_lat, lon=center_lon),
                zoom=zoom,
            ),
            margin=dict(t=10, b=10, l=10, r=10),
            height=350,
        )
        map_html = pio.to_html(map_fig, full_html=False, include_plotlyjs=False)

    context = {
        "site_number": site_number,
        "start": start_str,
        "end": end_str,
        "comparison": comparison,
        "show_band": show_band,
        "error_pct": error_pct,
        "plot_html": plot_html,
        "map_html": map_html,
        "table_data": table_data,
        "error": error,
        "site_name": site_name,
    }
    return render(request, "water_balance/flow_balance.html", context)