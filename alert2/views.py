from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import polars as pl
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

PACIFIC = ZoneInfo("America/Los_Angeles")

from sites.models import LocatorGroup, NovaPointLocator, Site
from water_balance.usgs import USGSAPIError
from .novastar import NovastarAPIError, fetch_point_data


# ---------------------------------------------------------------------------
# Transmit summary helpers
# ---------------------------------------------------------------------------

def _parse_report_time(time_str):
    """Extract local YYYY-MM-DDTHH:MM from a Novastar reportTime string.

    Novastar timestamps include a timezone offset (e.g. "2026-03-15T01:23:09-07:00").
    We keep the local date/time as-is so that comparisons stay in the station's
    local timezone, matching the user-entered offset which is relative to local midnight.
    """
    try:
        return time_str[:16]  # "2026-03-15T01:23"
    except (TypeError, IndexError):
        return None



def _expected_times_for_date(d, interval_hours, offset_minutes):
    """All scheduled local transmit time strings (YYYY-MM-DDTHH:MM) for a given date."""
    interval_min = interval_hours * 60
    start_min = offset_minutes % interval_min
    times = []
    m = start_min
    while m < 24 * 60:
        h, mn = divmod(m, 60)
        times.append(f"{d.isoformat()}T{h:02d}:{mn:02d}")
        m += interval_min
    return times


def _compute_daily_stats(received_set, start_date, end_date, interval_hours, offset_minutes):
    """Return list of per-day dicts over [start_date, end_date] (inclusive)."""
    rows = []
    current = start_date
    while current <= end_date:
        expected = _expected_times_for_date(current, interval_hours, offset_minutes)
        received = sum(1 for t in expected if t in received_set)
        pct = round(received / len(expected) * 100) if expected else 0
        rows.append({
            "date": current.strftime("%Y-%m-%d"),
            "expected": len(expected),
            "received": received,
            "pct": pct,
        })
        current += timedelta(days=1)
    return rows


def _rolling_24h_summary(received_set, now, interval_hours, offset_minutes):
    """Transmit reliability for the rolling 24-hour window ending at now (local time).
    Expected slots are those scheduled within the last 24 hours, so a partial day
    never inflates the denominator with future slots."""
    window_end_str = now.strftime("%Y-%m-%dT%H:%M")
    window_start = now - timedelta(hours=24)
    window_start_str = window_start.strftime("%Y-%m-%dT%H:%M")

    interval_min = interval_hours * 60
    start_min = offset_minutes % interval_min

    expected_times = []
    for d in [window_start.date(), now.date()]:
        m = start_min
        while m < 24 * 60:
            h, mn = divmod(m, 60)
            t_str = f"{d.isoformat()}T{h:02d}:{mn:02d}"
            if window_start_str <= t_str <= window_end_str:
                expected_times.append(t_str)
            m += interval_min

    received = sum(1 for t in expected_times if t in received_set)
    total_exp = len(expected_times)
    return {
        "expected": total_exp,
        "received": received,
        "pct": round(received / total_exp * 100) if total_exp else 0,
    }


def _window_summary(daily_rows, end_date_str, days):
    """Aggregate stats for the last `days` days up to end_date."""
    cutoff = (datetime.strptime(end_date_str, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    window = [r for r in daily_rows if r["date"] >= cutoff]
    total_exp = sum(r["expected"] for r in window)
    total_rec = sum(r["received"] for r in window)
    return {
        "expected": total_exp,
        "received": total_rec,
        "pct": round(total_rec / total_exp * 100) if total_exp else 0,
        "days": len(window),
    }


@login_required
def index(request):
    site_no = request.GET.get("site", "").strip()
    if site_no:
        return redirect("alert2_site_data", site_no=site_no)
    return render(request, "alert2/index.html")


@login_required
def site_data(request, site_no):
    # Handle POST: superuser adding a new point locator
    if request.method == "POST" and not request.user.is_superuser:
        return HttpResponseForbidden()
    if request.method == "POST":
        point_locator = request.POST.get("point_locator", "").strip()
        parameter_type = request.POST.get("parameter_type", "").strip()
        label = request.POST.get("label", "").strip()
        start = request.POST.get("start", "")
        end = request.POST.get("end", "")
        if point_locator and parameter_type:
            try:
                site = Site.get_or_fetch(site_no)
                NovaPointLocator.objects.get_or_create(
                    site=site,
                    point_locator=point_locator,
                    defaults={"parameter_type": parameter_type, "label": label},
                )
            except USGSAPIError:
                pass
        url = reverse("alert2_site_data", kwargs={"site_no": site_no})
        qs = f"?start={start}&end={end}" if start and end else ""
        return redirect(url + qs)

    now = datetime.now(PACIFIC)
    default_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    default_end = now.strftime("%Y-%m-%d")

    start_str = request.GET.get("start", default_start)
    end_str = request.GET.get("end", default_end)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
    except ValueError:
        start_dt = datetime.strptime(default_start, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(default_end, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        start_str, end_str = default_start, default_end

    error = None
    site_name = None
    table_rows = []
    sensors = []

    try:
        site = Site.get_or_fetch(site_no)
        site_name = site.name
        locators = list(NovaPointLocator.objects.filter(site=site).order_by("parameter_type"))

        if not locators:
            error = f"No Novastar point locators are configured for site {site_no}."
        else:
            frames = []
            fetch_end_dt = end_dt + timedelta(days=1)
            for locator in locators:
                label = locator.label or locator.parameter_type
                data = fetch_point_data(locator.point_locator, start_dt, fetch_end_dt)
                rows = data.get("data", [])
                sensors.append({
                    "label": label,
                    "point_locator": locator.point_locator,
                    "point_name": data.get("point", {}).get("name", ""),
                })
                if rows:
                    df = pl.DataFrame({
                        "reportTime": [r["reportTime"] for r in rows],
                        f"{label}__raw": [float(r["valueRaw"]) for r in rows],
                        f"{label}__scaled": [float(r["valueScaled"]) for r in rows],
                        f"{label}__flags": [str(r["flags"]) for r in rows],
                    })
                else:
                    df = pl.DataFrame({
                        "reportTime": pl.Series([], dtype=pl.String),
                        f"{label}__raw": pl.Series([], dtype=pl.Float64),
                        f"{label}__scaled": pl.Series([], dtype=pl.Float64),
                        f"{label}__flags": pl.Series([], dtype=pl.String),
                    })
                frames.append(df)

            combined = frames[0]
            for frame in frames[1:]:
                combined = combined.join(frame, on="reportTime", how="outer_coalesce")
            combined = combined.sort("reportTime", descending=True)

            for row in combined.to_dicts():
                report_time = row["reportTime"][:19].replace("T", " ") if row["reportTime"] else ""
                values = []
                for locator in locators:
                    label = locator.label or locator.parameter_type
                    raw = row.get(f"{label}__raw")
                    scaled = row.get(f"{label}__scaled")
                    flags = row.get(f"{label}__flags", "")
                    values.append({
                        "raw": f"{raw:.3f}" if raw is not None else "—",
                        "scaled": f"{scaled:.3f}" if scaled is not None else "—",
                        "flags": flags or "",
                    })
                table_rows.append({"report_time": report_time, "values": values})

    except (USGSAPIError, NovastarAPIError) as exc:
        error = str(exc)

    context = {
        "site_no": site_no,
        "site_name": site_name,
        "start": start_str,
        "end": end_str,
        "sensors": sensors,
        "table_rows": table_rows,
        "error": error,
        "summary_url": reverse("alert2_summary", kwargs={"site_no": site_no}),
    }
    return render(request, "alert2/site_data.html", context)


def _build_sensor_rows(locators, interval_hours, offset_minutes, start_dt, end_dt, end_str, now):
    """Build sensor_rows list for overview — shared between site and group rows."""
    sensor_rows = []
    for locator in locators:
        label = locator.label or locator.parameter_type
        row = {
            "label": label,
            "point_locator": locator.point_locator,
            "summary_1d": None,
            "summary_7d": None,
            "summary_30d": None,
            "error": None,
        }
        if interval_hours:
            try:
                data = fetch_point_data(locator.point_locator, start_dt, end_dt + timedelta(days=1))
                received_set = set()
                for r in data.get("data", []):
                    t = _parse_report_time(r["reportTime"])
                    if t:
                        received_set.add(t)
                daily_rows = _compute_daily_stats(
                    received_set,
                    start_dt.date(), end_dt.date(),
                    interval_hours,
                    offset_minutes,
                )
                row["summary_1d"] = _rolling_24h_summary(received_set, now, interval_hours, offset_minutes)
                row["summary_7d"] = _window_summary(daily_rows, end_str, 7)
                row["summary_30d"] = _window_summary(daily_rows, end_str, 30)
            except NovastarAPIError as exc:
                row["error"] = str(exc)
        sensor_rows.append(row)
    return sensor_rows


@login_required
def overview(request):
    now = datetime.now(PACIFIC)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = today_midnight
    start_dt = end_dt - timedelta(days=30)
    end_str = now.strftime("%Y-%m-%d")

    # Sites with at least one locator
    sites = (
        Site.objects.filter(nova_point_locators__isnull=False)
        .distinct()
        .order_by("site_no")
        .prefetch_related("nova_point_locators")
    )

    # Groups with at least one locator
    groups = (
        LocatorGroup.objects.filter(nova_point_locators__isnull=False)
        .distinct()
        .order_by("name")
        .prefetch_related("nova_point_locators")
    )

    all_rows = []

    for site in sites:
        locators = list(site.nova_point_locators.order_by("parameter_type"))
        sensor_rows = _build_sensor_rows(
            locators, site.transmit_interval_hours, site.transmit_offset_minutes,
            start_dt, end_dt, end_str, now,
        )
        all_rows.append({
            "display_name": site.site_no,
            "display_subtitle": site.name,
            "detail_url": reverse("alert2_site_data", kwargs={"site_no": site.site_no}),
            "summary_url": reverse("alert2_summary", kwargs={"site_no": site.site_no}),
            "transmit_interval_hours": site.transmit_interval_hours,
            "transmit_offset_minutes": site.transmit_offset_minutes,
            "sensor_rows": sensor_rows,
        })

    for group in groups:
        locators = list(group.nova_point_locators.order_by("parameter_type"))
        sensor_rows = _build_sensor_rows(
            locators, group.transmit_interval_hours, group.transmit_offset_minutes,
            start_dt, end_dt, end_str, now,
        )
        all_rows.append({
            "display_name": group.name,
            "display_subtitle": "",
            "detail_url": reverse("alert2_group_data", kwargs={"pk": group.pk}),
            "summary_url": reverse("alert2_group_summary", kwargs={"pk": group.pk}),
            "transmit_interval_hours": group.transmit_interval_hours,
            "transmit_offset_minutes": group.transmit_offset_minutes,
            "sensor_rows": sensor_rows,
        })

    return render(request, "alert2/overview.html", {"all_rows": all_rows})


@login_required
def summary(request, site_no):
    # Handle POST: superuser saving site-level transmit schedule
    if request.method == "POST" and request.user.is_superuser:
        interval = request.POST.get("transmit_interval_hours", "").strip()
        offset = request.POST.get("transmit_offset_minutes", "0").strip()
        try:
            site = Site.get_or_fetch(site_no)
            site.transmit_interval_hours = int(interval) if interval else None
            site.transmit_offset_minutes = int(offset) if offset else 0
            site.save()
        except (USGSAPIError, ValueError):
            pass
        return redirect("alert2_summary", site_no=site_no)

    now = datetime.now(PACIFIC)
    default_end = now.strftime("%Y-%m-%d")
    default_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    start_str = request.GET.get("start", default_start)
    end_str = request.GET.get("end", default_end)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
    except ValueError:
        start_dt = datetime.strptime(default_start, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(default_end, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        start_str, end_str = default_start, default_end

    error = None
    site_name = None
    locator_stats = []

    try:
        site = Site.get_or_fetch(site_no)
        site_name = site.name
        locators = list(NovaPointLocator.objects.filter(site=site).order_by("parameter_type"))

        for locator in locators:
            label = locator.label or locator.parameter_type
            entry = {
                "locator": locator,
                "label": label,
                "daily_rows": None,
                "summary_7d": None,
                "summary_30d": None,
                "fetch_error": None,
            }

            if site.transmit_interval_hours:
                try:
                    data = fetch_point_data(locator.point_locator, start_dt, end_dt + timedelta(days=1))
                    raw_rows = data.get("data", [])

                    received_set = set()
                    for r in raw_rows:
                        t = _parse_report_time(r["reportTime"])
                        if t:
                            received_set.add(t)

                    daily_rows = _compute_daily_stats(
                        received_set,
                        start_dt.date(), end_dt.date(),
                        site.transmit_interval_hours,
                        site.transmit_offset_minutes,
                    )
                    entry["daily_rows"] = daily_rows
                    entry["summary_7d"] = _window_summary(daily_rows, end_str, 7)
                    entry["summary_30d"] = _window_summary(daily_rows, end_str, 30)

                except NovastarAPIError as exc:
                    entry["fetch_error"] = str(exc)

            locator_stats.append(entry)

    except USGSAPIError as exc:
        error = str(exc)

    context = {
        "site_no": site_no,
        "site_name": site_name,
        "site": site,
        "start": start_str,
        "end": end_str,
        "locator_stats": locator_stats,
        "error": error,
        "data_url": reverse("alert2_site_data", kwargs={"site_no": site_no}),
    }
    return render(request, "alert2/summary.html", context)


# ---------------------------------------------------------------------------
# LocatorGroup views (non-USGS sensor groups)
# ---------------------------------------------------------------------------

def _fetch_locator_table(locators, start_dt, end_dt):
    """Fetch and join data from multiple point locators; return (sensors, table_rows, error)."""
    sensors = []
    table_rows = []
    error = None
    frames = []
    fetch_end_dt = end_dt + timedelta(days=1)

    for locator in locators:
        label = locator.label or locator.parameter_type
        try:
            data = fetch_point_data(locator.point_locator, start_dt, fetch_end_dt)
        except NovastarAPIError as exc:
            error = str(exc)
            continue
        rows = data.get("data", [])
        sensors.append({
            "label": label,
            "point_locator": locator.point_locator,
            "point_name": data.get("point", {}).get("name", ""),
        })
        if rows:
            df = pl.DataFrame({
                "reportTime": [r["reportTime"] for r in rows],
                f"{label}__raw": [float(r["valueRaw"]) for r in rows],
                f"{label}__scaled": [float(r["valueScaled"]) for r in rows],
                f"{label}__flags": [str(r["flags"]) for r in rows],
            })
        else:
            df = pl.DataFrame({
                "reportTime": pl.Series([], dtype=pl.String),
                f"{label}__raw": pl.Series([], dtype=pl.Float64),
                f"{label}__scaled": pl.Series([], dtype=pl.Float64),
                f"{label}__flags": pl.Series([], dtype=pl.String),
            })
        frames.append((label, df))

    if frames:
        combined = frames[0][1]
        for _, frame in frames[1:]:
            combined = combined.join(frame, on="reportTime", how="outer_coalesce")
        combined = combined.sort("reportTime", descending=True)

        for row in combined.to_dicts():
            report_time = row["reportTime"][:19].replace("T", " ") if row["reportTime"] else ""
            values = []
            for locator in locators:
                label = locator.label or locator.parameter_type
                raw = row.get(f"{label}__raw")
                scaled = row.get(f"{label}__scaled")
                flags = row.get(f"{label}__flags", "")
                values.append({
                    "raw": f"{raw:.3f}" if raw is not None else "—",
                    "scaled": f"{scaled:.3f}" if scaled is not None else "—",
                    "flags": flags or "",
                })
            table_rows.append({"report_time": report_time, "values": values})

    return sensors, table_rows, error


@login_required
def group_data(request, pk):
    from django.shortcuts import get_object_or_404

    # Handle POST: superuser adding a new point locator to the group
    if request.method == "POST" and not request.user.is_superuser:
        return HttpResponseForbidden()

    group = get_object_or_404(LocatorGroup, pk=pk)

    if request.method == "POST":
        point_locator = request.POST.get("point_locator", "").strip()
        parameter_type = request.POST.get("parameter_type", "").strip()
        label = request.POST.get("label", "").strip()
        start = request.POST.get("start", "")
        end = request.POST.get("end", "")
        if point_locator and parameter_type:
            NovaPointLocator.objects.get_or_create(
                group=group,
                point_locator=point_locator,
                defaults={"parameter_type": parameter_type, "label": label},
            )
        url = reverse("alert2_group_data", kwargs={"pk": pk})
        qs = f"?start={start}&end={end}" if start and end else ""
        return redirect(url + qs)

    now = datetime.now(PACIFIC)
    default_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    default_end = now.strftime("%Y-%m-%d")

    start_str = request.GET.get("start", default_start)
    end_str = request.GET.get("end", default_end)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
    except ValueError:
        start_dt = datetime.strptime(default_start, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(default_end, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        start_str, end_str = default_start, default_end

    locators = list(group.nova_point_locators.order_by("parameter_type"))
    if locators:
        sensors, table_rows, error = _fetch_locator_table(locators, start_dt, end_dt)
    else:
        sensors, table_rows = [], []
        error = f"No Novastar point locators are configured for group '{group.name}'."

    context = {
        "group": group,
        "display_name": group.name,
        "start": start_str,
        "end": end_str,
        "sensors": sensors,
        "table_rows": table_rows,
        "error": error,
        "summary_url": reverse("alert2_group_summary", kwargs={"pk": pk}),
    }
    return render(request, "alert2/group_data.html", context)


@login_required
def group_summary(request, pk):
    from django.shortcuts import get_object_or_404

    group = get_object_or_404(LocatorGroup, pk=pk)

    # Handle POST: superuser saving group-level transmit schedule
    if request.method == "POST" and request.user.is_superuser:
        interval = request.POST.get("transmit_interval_hours", "").strip()
        offset = request.POST.get("transmit_offset_minutes", "0").strip()
        try:
            group.transmit_interval_hours = int(interval) if interval else None
            group.transmit_offset_minutes = int(offset) if offset else 0
            group.save()
        except ValueError:
            pass
        return redirect("alert2_group_summary", pk=pk)

    now = datetime.now(PACIFIC)
    default_end = now.strftime("%Y-%m-%d")
    default_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    start_str = request.GET.get("start", default_start)
    end_str = request.GET.get("end", default_end)

    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=PACIFIC)
    except ValueError:
        start_dt = datetime.strptime(default_start, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        end_dt = datetime.strptime(default_end, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        start_str, end_str = default_start, default_end

    locators = list(group.nova_point_locators.order_by("parameter_type"))
    locator_stats = []

    for locator in locators:
        label = locator.label or locator.parameter_type
        entry = {
            "locator": locator,
            "label": label,
            "daily_rows": None,
            "summary_7d": None,
            "summary_30d": None,
            "fetch_error": None,
        }
        if group.transmit_interval_hours:
            try:
                data = fetch_point_data(locator.point_locator, start_dt, end_dt + timedelta(days=1))
                received_set = set()
                for r in data.get("data", []):
                    t = _parse_report_time(r["reportTime"])
                    if t:
                        received_set.add(t)
                daily_rows = _compute_daily_stats(
                    received_set,
                    start_dt.date(), end_dt.date(),
                    group.transmit_interval_hours,
                    group.transmit_offset_minutes,
                )
                entry["daily_rows"] = daily_rows
                entry["summary_7d"] = _window_summary(daily_rows, end_str, 7)
                entry["summary_30d"] = _window_summary(daily_rows, end_str, 30)
            except NovastarAPIError as exc:
                entry["fetch_error"] = str(exc)
        locator_stats.append(entry)

    context = {
        "group": group,
        "display_name": group.name,
        "start": start_str,
        "end": end_str,
        "locator_stats": locator_stats,
        "data_url": reverse("alert2_group_data", kwargs={"pk": pk}),
    }
    return render(request, "alert2/group_summary.html", context)
