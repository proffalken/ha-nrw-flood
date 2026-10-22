"""NRW endpoint URLs shared by the tests."""

from custom_components.nrw_flood.const import API_BASE_URL

WARNINGS_URL = f"{API_BASE_URL}/floodwarnings/v3/all"
STATIONS_URL = f"{API_BASE_URL}/rivers-and-seas/v1/api/StationData/byLocation"
HISTORY_URL = f"{API_BASE_URL}/rivers-and-seas/v1/api/StationData/historical"
FORECAST_URL = f"{API_BASE_URL}/floodforecast/v2/summary"
AREAS_AT_RISK_URL = f"{API_BASE_URL}/floodforecast/v2/areasatrisk"
