"""
USGS Water Services IV API client.

Fetches instantaneous-value time series for one or more sites and returns
a Polars DataFrame with columns: site_no, datetime (UTC), value, unit.
"""

import polars as pl
import requests
from datetime import datetime, timezone

IV_URL = "https://waterservices.usgs.gov/nwis/iv/"

PARAM_DISCHARGE     = "00060"   # Discharge, cfs
PARAM_GAGE_HEIGHT   = "00065"   # Gage height, ft
PARAM_PRECIPITATION = "00045"   # Precipitation, inches (incremental per recording interval)


class USGSAPIError(Exception):
    pass


def _parse_tz_offset_min(dt_str: str) -> int:
    """
    Extract the UTC offset in minutes from a USGS datetime string.
    e.g. '2024-10-01T14:15:00.000-07:00' → -420
    Returns 0 if the offset cannot be parsed.
    """
    try:
        tz_part = dt_str[-6:]   # e.g. '-07:00'
        sign = 1 if tz_part[0] == '+' else -1
        return sign * (int(tz_part[1:3]) * 60 + int(tz_part[4:6]))
    except (ValueError, IndexError):
        return 0


def fetch_iv(
    site_nos: list[str],
    parameter_cd: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pl.DataFrame:
    """
    Fetch USGS instantaneous values for one or more sites.

    Args:
        site_nos:     List of USGS site numbers (e.g. ['09419800', '09419700']).
        parameter_cd: Parameter code — use PARAM_DISCHARGE or PARAM_GAGE_HEIGHT.
        start_dt:     Start of period (timezone-aware datetime).
        end_dt:       End of period (timezone-aware datetime).

    Returns:
        Polars DataFrame with columns:
            site_no  (str)
            datetime (Datetime[us, UTC])
            value    (Float64)  — null where value is masked/missing
            unit     (str)
    """
    params = {
        "format": "json",
        "sites": ",".join(site_nos),
        "parameterCd": parameter_cd,
        "startDT": start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDT": end_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    try:
        response = requests.get(IV_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise USGSAPIError(f"USGS API request failed: {exc}") from exc

    data = response.json()

    time_series = data.get("value", {}).get("timeSeries", [])
    if not time_series:
        # Return empty frame with correct schema
        return pl.DataFrame(
            schema={
                "site_no": pl.String,
                "datetime": pl.Datetime("us", "UTC"),
                "value": pl.Float64,
                "unit": pl.String,
                "qualifiers": pl.String,
                "tz_offset_min": pl.Int32,
            }
        )

    rows: list[dict] = []
    for series in time_series:
        site_no = series["sourceInfo"]["siteCode"][0]["value"]
        unit = series["variable"]["unit"]["unitCode"]
        for record in series["values"][0]["value"]:
            raw_value = record["value"]
            rows.append(
                {
                    "site_no": site_no,
                    "datetime": record["dateTime"],
                    "value": None if raw_value == "-999999" else float(raw_value),
                    "unit": unit,
                    "qualifiers": ",".join(record.get("qualifiers", [])),
                    "tz_offset_min": _parse_tz_offset_min(record["dateTime"]),
                }
            )

    df = pl.DataFrame(rows)
    df = df.with_columns(
        pl.col("datetime")
        .str.to_datetime("%Y-%m-%dT%H:%M:%S%.f%z")
        .dt.convert_time_zone("UTC")
    )
    return df


DV_URL = "https://waterservices.usgs.gov/nwis/dv/"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/"


def fetch_site_names(site_nos: list[str]) -> dict[str, str]:
    """
    Return a dict mapping site number → site name for the given sites.
    Uses the USGS site service endpoint. Unknown sites are omitted.
    """
    try:
        response = requests.get(
            SITE_URL,
            params={"format": "rdb", "sites": ",".join(site_nos), "siteOutput": "basic"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise USGSAPIError(f"USGS site info request failed: {exc}") from exc

    names = {}
    for line in response.text.splitlines():
        if line.startswith("#") or line.startswith("agency_cd") or line.startswith("5s"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            names[parts[1]] = parts[2]
    return names


def fetch_dv(
    site_nos: list[str],
    parameter_cd: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pl.DataFrame:
    """
    Fetch USGS official daily values for one or more sites.

    Returns a Polars DataFrame with columns:
        site_no  (str)
        date     (Date)
        value    (Float64)  — null where masked/missing
        unit     (str)
    """
    params = {
        "format": "json",
        "sites": ",".join(site_nos),
        "parameterCd": parameter_cd,
        "startDT": start_dt.astimezone(timezone.utc).strftime("%Y-%m-%d"),
        "endDT": end_dt.astimezone(timezone.utc).strftime("%Y-%m-%d"),
        "statCd": "00003",  # mean
    }

    try:
        response = requests.get(DV_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise USGSAPIError(f"USGS DV API request failed: {exc}") from exc

    data = response.json()
    time_series = data.get("value", {}).get("timeSeries", [])
    if not time_series:
        return pl.DataFrame(
            schema={"site_no": pl.String, "date": pl.Date, "value": pl.Float64, "unit": pl.String}
        )

    rows: list[dict] = []
    for series in time_series:
        site_no = series["sourceInfo"]["siteCode"][0]["value"]
        unit = series["variable"]["unit"]["unitCode"]
        for record in series["values"][0]["value"]:
            raw_value = record["value"]
            rows.append({
                "site_no": site_no,
                "date": record["dateTime"][:10],  # "YYYY-MM-DD"
                "value": None if raw_value == "-999999" else float(raw_value),
                "unit": unit,
            })

    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))
    return df


def fetch_discharge(
    site_nos: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> pl.DataFrame:
    """Fetch discharge (00060, cfs) for one or more sites."""
    return fetch_iv(site_nos, PARAM_DISCHARGE, start_dt, end_dt)


def fetch_gage_height(
    site_nos: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> pl.DataFrame:
    """Fetch gage height (00065, ft) for one or more sites."""
    return fetch_iv(site_nos, PARAM_GAGE_HEIGHT, start_dt, end_dt)


def fetch_precipitation(
    site_nos: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> pl.DataFrame:
    """Fetch precipitation (00045, inches incremental) for one or more sites."""
    return fetch_iv(site_nos, PARAM_PRECIPITATION, start_dt, end_dt)


def shift_time_of_travel(df: pl.DataFrame, offset_minutes: float) -> pl.DataFrame:
    """
    Shift the datetime column of a site's time series forward by offset_minutes.

    A positive offset moves readings forward in time, simulating travel time
    from an upstream site to a downstream site.
    """
    offset_us = int(offset_minutes * 60 * 1_000_000)
    return df.with_columns(
        (pl.col("datetime") + pl.duration(microseconds=offset_us)).alias("datetime")
    )