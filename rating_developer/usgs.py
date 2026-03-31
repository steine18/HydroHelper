"""
USGS data fetchers for the Rating Developer tool.
"""
import requests
from water_balance.usgs import USGSAPIError

RATINGS_URL = "https://waterdata.usgs.gov/nwisweb/get_ratings"
FIELD_MEASUREMENTS_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items"
CHANNEL_MEASUREMENTS_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/channel-measurements/items"

QUALITY_ORDER = ['Excellent', 'Good', 'Fair', 'Poor', 'Unspecified']
QUALITY_COLORS = {
    'Excellent': '#2ECC40',
    'Good': '#0074D9',
    'Fair': '#FF851B',
    'Poor': '#FF4136',
    'Unspecified': '#AAAAAA',
}


def fetch_rating_table(site_no: str, file_type: str = 'exsa') -> list[dict]:
    """
    Fetch the current rating table for a site.
    file_type='exsa'  — full shift-adjusted expanded table (for curve line)
    file_type='base'  — base control points only (for rating points table)
    Returns list of {stage, discharge} dicts sorted by stage.
    Raises USGSAPIError on failure or if no rating exists.
    """
    try:
        resp = requests.get(
            RATINGS_URL,
            params={'site_no': site_no, 'file_type': file_type},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise USGSAPIError(f"Rating table request failed: {exc}") from exc

    return _parse_rating_rdb(resp.text)


def _parse_rating_rdb(text: str) -> list[dict]:
    """Parse USGS rating RDB text into list of {stage, discharge} dicts."""
    rows = []
    header = None
    skip_next = False

    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        if header is None:
            header = [h.strip().lower() for h in line.split('\t')]
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        try:
            indep_idx = header.index('indep') if 'indep' in header else 0
            dep_idx = header.index('dep') if 'dep' in header else 1
            stage = float(parts[indep_idx])
            discharge = float(parts[dep_idx])
            rows.append({'stage': stage, 'discharge': discharge})
        except (ValueError, IndexError):
            continue

    if not rows:
        raise USGSAPIError("No rating data found for this site.")
    return sorted(rows, key=lambda r: r['stage'])


def parse_manual_rating(text: str) -> list[dict]:
    """
    Parse a manually pasted rating table (tab, comma, or space separated).
    Returns list of {stage, discharge} dicts sorted by stage.
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        for sep in ('\t', ',', None):
            parts = line.split(sep) if sep else line.split()
            if len(parts) >= 2:
                try:
                    rows.append({'stage': float(parts[0]), 'discharge': float(parts[1])})
                    break
                except ValueError:
                    continue
    return sorted(rows, key=lambda r: r['stage'])


def fetch_measurements(site_no: str) -> list[dict]:
    """
    Fetch all historical field measurements for a site using the USGS OGC API.
    Returns list of {number, date, stage, discharge, quality} dicts.
    Raises USGSAPIError on failure or if no measurements exist.
    """
    loc_id = f"USGS-{site_no}"
    params_base = {'monitoring_location_id': loc_id, 'f': 'json', 'limit': 10000}

    try:
        q_resp = requests.get(FIELD_MEASUREMENTS_URL, params={**params_base, 'parameter_code': '00060'}, timeout=30)
        q_resp.raise_for_status()
        gh_resp = requests.get(FIELD_MEASUREMENTS_URL, params={**params_base, 'parameter_code': '00065'}, timeout=30)
        gh_resp.raise_for_status()
        ch_resp = requests.get(CHANNEL_MEASUREMENTS_URL, params=params_base, timeout=30)
        ch_resp.raise_for_status()
    except requests.RequestException as exc:
        raise USGSAPIError(f"Measurements request failed: {exc}") from exc

    # Index discharge records by field_visit_id (take last if multiple)
    discharge_by_visit = {}
    for feat in q_resp.json().get('features', []):
        p = feat['properties']
        try:
            discharge_by_visit[p['field_visit_id']] = {
                'discharge': float(p['value']),
                'quality': _normalize_quality(p.get('measurement_rated') or ''),
                'time': p.get('time', ''),
            }
        except (ValueError, TypeError):
            continue

    # Index gage height by field_visit_id
    stage_by_visit = {}
    for feat in gh_resp.json().get('features', []):
        p = feat['properties']
        try:
            stage_by_visit[p['field_visit_id']] = float(p['value'])
        except (ValueError, TypeError):
            continue

    # Index measurement number by field_visit_id
    meas_no_by_visit = {}
    for feat in ch_resp.json().get('features', []):
        p = feat['properties']
        visit_id = p.get('field_visit_id', '')
        meas_no = p.get('measurement_number', '')
        if visit_id and meas_no and visit_id not in meas_no_by_visit:
            meas_no_by_visit[visit_id] = meas_no

    # Join on field_visit_id
    rows = []
    for visit_id, q_data in discharge_by_visit.items():
        stage = stage_by_visit.get(visit_id)
        if stage is None or q_data['discharge'] <= 0:
            continue
        date_str = q_data['time'][:10] if q_data['time'] else ''
        rows.append({
            'number': meas_no_by_visit.get(visit_id, visit_id[:8]),
            'date': date_str,
            'stage': stage,
            'discharge': q_data['discharge'],
            'quality': q_data['quality'],
        })

    if not rows:
        raise USGSAPIError("No measurement data found for this site.")

    return sorted(rows, key=lambda r: r['date'])


def _normalize_quality(raw: str) -> str:
    """Normalize a measurement_rated string to a QUALITY_COLORS key."""
    q = raw.strip().capitalize()
    return q if q in QUALITY_COLORS else 'Unspecified'
