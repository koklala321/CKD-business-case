"""
api_client.py
=============
Wrapper around the CVDPrevent REST API 
------------------
  GET /area?timePeriodID={id}&systemLevelID={id}
  GET /indicator?timePeriodID={id}&systemLevelID={id}&areaID={id}
"""

from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

#Constants
BASE_URL = "https://api.cvdprevent.nhs.uk"
# systemLevelID=7 → ICB granularity
ICB_SYSTEM_LEVEL_ID = 7   
# Default indicator codes — can be overridden in the notebook
CKD_INDICATOR_CODES = {"CVDP001CKD", "CVDP002CKD", "CVDP004CKD", "CVDP006CKD"}
# Default time period — can be overridden in the notebook
TARGET_PERIOD_ID = 31
REQUEST_TIMEOUT = (5, 30)   

#Custom exception
class CVDPApiError(Exception):
    """Raised for any unrecoverable API error."""

#HTTP session with retry
def _build_session() -> requests.Session:
    """Return a Session with automatic retry on transient server errors."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,                       
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session

#Helpers
def _get(session: requests.Session, endpoint: str, params: dict) -> dict:
    """
    Execute a GET request and return the parsed JSON.
    Raises CVDPApiError on network failures, non-200 responses, or API errors.
    """
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    logger.info("GET %s  params=%s", endpoint, params)
    try:
        res = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.ConnectionError as exc:
        raise CVDPApiError(f"Connection failed: {url}") from exc
    except requests.Timeout as exc:
        raise CVDPApiError(f"Request timed out: {url}") from exc
    except requests.RequestException as exc:
        raise CVDPApiError(f"Request error: {url} — {exc}") from exc

    if res.status_code != 200:
        raise CVDPApiError(f"HTTP {res.status_code} from {url}: {res.text[:300]}")

    try:
        data = res.json()
    except ValueError as exc:
        raise CVDPApiError(f"Non-JSON response from {url}: {res.text[:300]}") from exc

    if isinstance(data, dict) and data.get("success") is False:
        raise CVDPApiError(f"API error from {url}: {data.get('error_message', data)}")
    if isinstance(data, dict) and "errorCode" in data:
        raise CVDPApiError(f"API error {data['errorCode']} from {url}: {data.get('message')}")

    return data


#Public client
class CVDPreventClient:
    """
    Fetches CKD indicator data from the CVDPrevent API at ICB level.
    """

    def __init__(self) -> None:
        self._session = _build_session()

    def _get(self, endpoint: str, params: dict) -> dict:
        return _get(self._session, endpoint, params)

    #ICB areas
    def get_icb_areas(self, time_period_id: int) -> list[dict]:
        """Return all ICB areas for a given time period."""
        data = self._get("/area", {"timePeriodID": time_period_id, "systemLevelID": ICB_SYSTEM_LEVEL_ID})
        areas = data.get("areaList", [])
        if not areas:
            raise CVDPApiError(f"No ICB areas returned for timePeriodID={time_period_id}.")
        return areas

    #Indicators for one ICB
    def _get_indicators(self, time_period_id: int, area_id: int) -> list[dict]:
        """Fetch all indicators for one ICB and period (API returns all in one payload)."""
        data = self._get("/indicator", {
            "timePeriodID": time_period_id,
            "systemLevelID": ICB_SYSTEM_LEVEL_ID,
            "areaID": area_id,
        })
        return data.get("indicatorList", [])

    #Main fetch
    def fetch_ckd_icb_data(
        self,
        time_period_id: int = TARGET_PERIOD_ID,
        indicator_codes = CKD_INDICATOR_CODES,
        area_ids: set[int] | None = None,
    ) -> list[dict]:
        """
        Fetch all category rows for CKD indicators at ICB level.
            Examples
            --------
            # Single ICB — fast iteration during exploration
            client.fetch_ckd_icb_data(area_ids={8036})

            # Subset of ICBs
            client.fetch_ckd_icb_data(area_ids={8036, 8067, 8052})

            # All ICBs (default)
            client.fetch_ckd_icb_data()
        """
        records: list[dict] = []
        all_areas = self.get_icb_areas(time_period_id)

        #Filter to requested area_ids if supplied; otherwise use all
        if area_ids is not None:
            areas = [a for a in all_areas if a["AreaID"] in area_ids]
            #raise warning if any requested area_ids were not found in the API response
            unknown = area_ids - {a["AreaID"] for a in all_areas}
            if unknown:
                logger.warning("area_ids not found for period %s: %s", time_period_id, unknown)
        else:
            areas = all_areas

        logger.info(
            "Fetching period_id=%s — %d ICB(s), indicators=%s",
            time_period_id, len(areas), set(indicator_codes),
        )
        for area in areas:
            area_id   = area["AreaID"]
            area_name = area.get("AreaName", "").strip()

            try:
                indicators = self._get_indicators(time_period_id, area_id)
            except CVDPApiError as exc:
                logger.warning("Skipping ICB '%s' (period=%s): %s", area_name, time_period_id, exc)
                continue

            for ind in indicators:
                code = ind.get("IndicatorCode", "")
                if code not in indicator_codes:
                    continue

                for cat in ind.get("Categories", []):
                    d = cat.get("Data") or {}
                    # TimePeriodName lives in the TimeSeries list, not in Data
                    ts_entry = next(
                        (t for t in cat.get("TimeSeries", [])
                         if t.get("TimePeriodID") == time_period_id),
                        {},
                    )
                    #getting all fields in Data plus some key fields from the parent indicator and category levels
                    record = {
                        k.lower(): v for k, v in d.items()
                        if k not in ("AreaID", "TimePeriodID")
                    }
                    record.update({
                        "area_id":                   area_id,
                        "area_name":                 area_name,
                        "time_period_id":            time_period_id,
                        "time_period_name":          ts_entry.get("TimePeriodName", str(time_period_id)),
                        "indicator_code":            code,
                        "indicator_name":            ind.get("IndicatorName", "").strip(),
                        "category_attribute":        cat.get("CategoryAttribute"),
                        "metric_category_name":      cat.get("MetricCategoryName"),
                        "metric_category_type_name": cat.get("MetricCategoryTypeName"),
                    })
                    records.append(record)

        logger.info("Fetched %d raw records for period %s (before cleaning)", len(records), time_period_id)
        return records

