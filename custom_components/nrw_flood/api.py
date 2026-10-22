"""Async client for the Natural Resources Wales open data APIs."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    KEY_HEADER,
    WFS_LAYER_ALERT,
    WFS_LAYER_WARNING,
    WFS_URL,
)
from .models import (
    FloodArea,
    FloodWarning,
    Forecast,
    Reading,
    Station,
    parse_areas_at_risk,
    parse_flood_areas,
    parse_forecast,
    parse_history,
    parse_stations,
    parse_warnings,
)

_TIMEOUT = aiohttp.ClientTimeout(total=60)


class NRWError(Exception):
    """Base error for NRW API failures."""


class NRWAuthError(NRWError):
    """Raised when NRW rejects a subscription key."""


class NRWConnectionError(NRWError):
    """Raised when an API can't be reached, errors, or returns bad data."""


class NRWApiClient:
    """Client for the NRW flood warnings, river level and forecast APIs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        warnings_key: str | None,
        levels_key: str | None,
        forecast_key: str | None,
    ) -> None:
        self._session = session
        self._warnings_key = warnings_key
        self._levels_key = levels_key
        self._forecast_key = forecast_key

    async def async_get_warnings(self) -> list[FloodWarning]:
        """All flood warnings and alerts currently in the feed."""
        payload = await self._get_nrw("/floodwarnings/v3/all", self._warnings_key)
        return parse_warnings(payload)

    async def async_get_stations_near(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[Station]:
        """Latest river levels at stations within radius_km of a point."""
        payload = await self._get_nrw(
            "/rivers-and-seas/v1/api/StationData/byLocation",
            self._levels_key,
            # NRW's distance parameter is in metres.
            params={
                "distance": str(round(radius_km * 1000)),
                "lat": str(latitude),
                "lon": str(longitude),
            },
        )
        return parse_stations(payload)

    async def async_get_history(self, station_id: int, parameter: int) -> list[Reading]:
        """Historical readings for one station (about a year, so ~1.7MB)."""
        payload = await self._get_nrw(
            "/rivers-and-seas/v1/api/StationData/historical",
            self._levels_key,
            params={"location": str(station_id), "parameter": str(parameter)},
        )
        return parse_history(payload)

    async def async_get_forecast(self) -> Forecast:
        """The Wales-wide 5-day flood risk forecast summary."""
        payload = await self._get_nrw("/floodforecast/v2/summary", self._forecast_key)
        return parse_forecast(payload)

    async def async_get_areas_at_risk(self) -> list[Any]:
        """Local authorities currently at risk in the 5-day forecast."""
        payload = await self._get_nrw(
            "/floodforecast/v2/areasatrisk", self._forecast_key
        )
        return parse_areas_at_risk(payload)

    async def async_get_flood_areas(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[FloodArea]:
        """Flood alert and warning areas whose outline is within radius_km."""
        metres = round(radius_km * 1000)
        areas: list[FloodArea] = []
        for layer, kind in ((WFS_LAYER_ALERT, "alert"), (WFS_LAYER_WARNING, "warning")):
            payload = await self._get(
                WFS_URL,
                headers={},
                # DataMapWales takes no key, and serves its "Service
                # unavailable" page with a 403, so a refusal isn't an auth error.
                keyed=False,
                params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeNames": layer,
                    "outputFormat": "application/json",
                    "propertyName": "fwd_tacode,fwa_name,descrip,river_sea",
                    "cql_filter": (
                        f"DWITHIN(geom,SRID=4326;POINT({longitude} {latitude}),"
                        f"{metres},meters)"
                    ),
                },
            )
            areas.extend(parse_flood_areas(payload, kind=kind))
        return areas

    async def _get_nrw(
        self, path: str, key: str | None, params: dict[str, str] | None = None
    ) -> Any:
        if not key:
            raise ValueError(f"No API key configured for {path}")
        return await self._get(
            f"{API_BASE_URL}{path}", headers={KEY_HEADER: key}, params=params
        )

    async def _get(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        keyed: bool = True,
    ) -> Any:
        try:
            async with self._session.get(
                url, headers=headers, params=params, timeout=_TIMEOUT
            ) as response:
                if keyed and response.status in (401, 403):
                    raise NRWAuthError(f"Key rejected by {url}")
                if response.status >= 400:
                    raise NRWConnectionError(
                        f"Unexpected status {response.status} from {url}"
                    )
                text = await response.text()
        except NRWError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise NRWConnectionError(f"Error connecting to {url}: {err}") from err
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise NRWConnectionError(f"Bad JSON from {url}: {err}") from err
