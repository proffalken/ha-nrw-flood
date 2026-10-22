"""Constants for the NRW Flood integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "nrw_flood"

# One key per NRW API product: each product on the NRW API portal issues its
# own subscription key, and a key for one product is rejected by the others.
CONF_WARNINGS_KEY: Final = "warnings_api_key"
CONF_LEVELS_KEY: Final = "levels_api_key"
CONF_FORECAST_KEY: Final = "forecast_api_key"
API_KEYS: Final = (CONF_WARNINGS_KEY, CONF_LEVELS_KEY, CONF_FORECAST_KEY)

CONF_RADIUS_KM: Final = "radius_km"
CONF_FLOOD_AREAS: Final = "flood_areas"
CONF_STATIONS: Final = "stations"

DEFAULT_RADIUS_KM: Final = 5

API_BASE_URL: Final = "https://api.naturalresources.wales"
KEY_HEADER: Final = "Ocp-Apim-Subscription-Key"

# DataMapWales GeoServer: open (no key). Holds the outlines of NRW's flood
# warning and flood alert areas, which the warnings feed refers to by code.
WFS_URL: Final = "https://datamap.gov.wales/geoserver/ows"
WFS_LAYER_WARNING: Final = "inspire-nrw:NRW_FLOOD_WARNING"
WFS_LAYER_ALERT: Final = "inspire-nrw:NRW_FLOOD_WATCH_AREAS"

STATION_URL: Final = "https://rivers-and-seas.naturalresources.wales/station/{}"

# Warnings change within minutes of being issued; river readings are every
# 15 minutes; the forecast is issued daily.
WARNINGS_INTERVAL: Final = timedelta(minutes=5)
LEVELS_INTERVAL: Final = timedelta(minutes=15)
FORECAST_INTERVAL: Final = timedelta(hours=1)

# NRW SEVERITYVALUE: 1 severe flood warning, 2 flood warning, 3 flood alert,
# 4 warning no longer in force.
LEVEL_NONE: Final = "none"
LEVEL_ALERT: Final = "alert"
LEVEL_WARNING: Final = "warning"
LEVEL_SEVERE: Final = "severe"
LEVELS: Final = (LEVEL_NONE, LEVEL_ALERT, LEVEL_WARNING, LEVEL_SEVERE)
SEVERITY_TO_LEVEL: Final = {1: LEVEL_SEVERE, 2: LEVEL_WARNING, 3: LEVEL_ALERT}

TRENDS: Final = ("rising", "steady", "falling")

EVENT_WARNING_CHANGED: Final = "nrw_flood_warning_changed"

ATTRIBUTION: Final = (
    "Contains Natural Resources Wales information © Natural Resources Wales "
    "and Database Right. All rights Reserved."
)
