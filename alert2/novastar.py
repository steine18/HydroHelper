import requests
from datetime import datetime

NOVA_HOST = "https://novastar5-secondary.ccrfcd.org"
NOVA_DATA_ENDPOINT = "/novastar/data/api/v1/data"


class NovastarAPIError(Exception):
    pass


def fetch_point_data(point_num_id: str, start_date: datetime, end_date: datetime) -> dict:
    """
    Fetch data for a single Novastar point locator.
    Returns the full JSON response dict.
    Raises NovastarAPIError on any failure.
    """
    params = {
        "pointNumId": point_num_id,
        "periodStart": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
        "periodEnd": end_date.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        response = requests.get(NOVA_HOST + NOVA_DATA_ENDPOINT, params=params, timeout=15)
    except requests.RequestException as exc:
        raise NovastarAPIError(f"Novastar API request failed: {exc}") from exc

    if not response.ok:
        try:
            data = response.json()
            errors = data.get("errors", [])
            if errors:
                detail = errors[0].get("details", ["Unknown error"])[0]
                raise NovastarAPIError(detail)
        except (ValueError, KeyError):
            pass
        raise NovastarAPIError(f"Novastar API returned HTTP {response.status_code}")

    return response.json()
