"""Data update coordinators for the NRW Flood integration.

Each NRW API has its own key and its own natural update rate, so each gets
its own coordinator. Only the APIs with a configured key are set up.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NRWApiClient, NRWAuthError, NRWConnectionError, NRWError
from .const import (
    DOMAIN,
    EVENT_WARNING_CHANGED,
    FORECAST_INTERVAL,
    LEVELS_INTERVAL,
    WARNINGS_INTERVAL,
)
from .models import (
    FloodWarning,
    Forecast,
    Reading,
    Station,
    highest_level,
    rate_of_change,
    trend_from_rate,
)

_LOGGER = logging.getLogger(__name__)

# Keep a little more than the rate window so a missed poll doesn't blank it.
_BUFFER_READINGS = 16


@dataclass(frozen=True, slots=True)
class WarningsData:
    """Warnings in force in the chosen areas, and the highest level among them."""

    warnings: list[FloodWarning]
    level: str


@dataclass(frozen=True, slots=True)
class StationData:
    """The latest reading at a station, plus its rate of change."""

    station: Station
    rate: float | None

    @property
    def trend(self) -> str | None:
        """rising / steady / falling from the hourly rate, or NRW's status
        until there's an hour of readings. NRW's status only compares the
        last two readings, so it flips with every few millimetres of jitter."""
        if self.rate is None:
            return self.station.trend
        return trend_from_rate(self.rate)


@dataclass(frozen=True, slots=True)
class ForecastData:
    """The 5-day forecast summary and the raw areas-at-risk list."""

    forecast: Forecast
    areas_at_risk: list[Any]


@contextmanager
def _translate_errors(name: str) -> Iterator[None]:
    """Map client errors onto the exceptions HA's coordinator understands."""
    try:
        yield
    except NRWAuthError as err:
        raise ConfigEntryAuthFailed(f"NRW rejected the {name} API key") from err
    except NRWConnectionError as err:
        raise UpdateFailed(f"Error fetching NRW {name}: {err}") from err


class WarningsCoordinator(DataUpdateCoordinator[WarningsData]):
    """Polls the live warnings feed and filters it to the chosen areas.

    Fires an event whenever a warning in the chosen areas is issued, changes
    level or message, or is removed. Nothing is fired for the first poll, so
    a restart doesn't re-announce warnings that were already in force.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: NRWApiClient,
        area_codes: list[str],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} warnings",
            update_interval=WARNINGS_INTERVAL,
        )
        self._client = client
        self._area_codes = set(area_codes)
        self._previous: dict[str, FloodWarning] | None = None

    async def _async_update_data(self) -> WarningsData:
        with _translate_errors("flood warnings"):
            all_warnings = await self._client.async_get_warnings()

        current = [w for w in all_warnings if w.code in self._area_codes and w.in_force]
        by_code = {w.code: w for w in current}
        if self._previous is not None:
            self._fire_changes(self._previous, by_code)
        self._previous = by_code
        return WarningsData(warnings=current, level=highest_level(current))

    def _fire_changes(
        self, before: dict[str, FloodWarning], after: dict[str, FloodWarning]
    ) -> None:
        for code, warning in after.items():
            old = before.get(code)
            if old is None:
                self._fire("issued", warning, previous=None)
            elif (old.level, old.message) != (warning.level, warning.message):
                self._fire("updated", warning, previous=old)
        for code, old in before.items():
            if code not in after:
                self._fire("removed", old, previous=old, removed=True)

    def _fire(
        self,
        change: str,
        warning: FloodWarning,
        previous: FloodWarning | None,
        removed: bool = False,
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_WARNING_CHANGED,
            {
                "config_entry_id": self.config_entry.entry_id,
                "change": change,
                "code": warning.code,
                "description": warning.description,
                "level": None if removed else warning.level,
                "previous_level": previous.level if previous else None,
                "message": None if removed else warning.message,
            },
        )


class LevelsCoordinator(DataUpdateCoordinator[dict[str, StationData]]):
    """Polls the latest river levels near home for the chosen stations.

    Keeps a short buffer of readings per station to work out the rate of
    change. The buffer is seeded once per station from the history endpoint,
    so the rate is available straight after a restart.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: NRWApiClient,
        latitude: float,
        longitude: float,
        radius_km: float,
        station_ids: list[str],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} river levels",
            update_interval=LEVELS_INTERVAL,
        )
        self._client = client
        self._latitude = latitude
        self._longitude = longitude
        self._radius_km = radius_km
        self._station_ids = set(station_ids)
        self._readings: dict[str, list[Reading]] = {}
        self._seeded: set[str] = set()

    async def _async_update_data(self) -> dict[str, StationData]:
        with _translate_errors("river levels"):
            stations = await self._client.async_get_stations_near(
                self._latitude, self._longitude, radius_km=self._radius_km
            )

        data: dict[str, StationData] = {}
        for station in stations:
            key = str(station.station_id)
            if key not in self._station_ids:
                continue
            if key not in self._seeded:
                await self._seed(key, station)
            self._add_latest(key, station)
            data[key] = StationData(
                station=station, rate=rate_of_change(self._readings.get(key, []))
            )
        return data

    async def _seed(self, key: str, station: Station) -> None:
        self._seeded.add(key)
        try:
            history = await self._client.async_get_history(
                station.station_id, station.parameter
            )
        except NRWError as err:
            _LOGGER.debug("No history for station %s yet: %s", key, err)
            return
        self._readings[key] = history[-_BUFFER_READINGS:]

    def _add_latest(self, key: str, station: Station) -> None:
        if station.latest_time is None or station.latest_value is None:
            return
        readings = self._readings.setdefault(key, [])
        if readings and readings[-1].time >= station.latest_time:
            return
        readings.append(Reading(station.latest_time, station.latest_value))
        del readings[:-_BUFFER_READINGS]


class ForecastCoordinator(DataUpdateCoordinator[ForecastData]):
    """Polls the Wales-wide 5-day flood risk forecast."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, client: NRWApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} forecast",
            update_interval=FORECAST_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> ForecastData:
        with _translate_errors("flood forecast"):
            forecast = await self._client.async_get_forecast()
            areas = await self._client.async_get_areas_at_risk()
        return ForecastData(forecast=forecast, areas_at_risk=areas)
