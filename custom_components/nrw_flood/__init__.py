"""The NRW Flood integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import NRWApiClient
from .const import (
    CONF_FLOOD_AREAS,
    CONF_FORECAST_KEY,
    CONF_LEVELS_KEY,
    CONF_RADIUS_KM,
    CONF_STATIONS,
    CONF_WARNINGS_KEY,
    DOMAIN,
)
from .coordinator import ForecastCoordinator, LevelsCoordinator, WarningsCoordinator
from .dashboard import async_register_dashboard_strategy

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.IMAGE]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class NRWFloodRuntimeData:
    """The coordinators for whichever APIs have a key configured."""

    warnings: WarningsCoordinator | None
    levels: LevelsCoordinator | None
    forecast: ForecastCoordinator | None

    @property
    def coordinators(self) -> list[DataUpdateCoordinator]:
        return [c for c in (self.warnings, self.levels, self.forecast) if c]


type NRWFloodConfigEntry = ConfigEntry[NRWFloodRuntimeData]


def selected(entry: ConfigEntry, key: str) -> list[str]:
    """Areas or stations chosen in options, falling back to the initial setup."""
    return list(entry.options.get(key, entry.data.get(key, [])))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard strategy, once, however many entries there are."""
    await async_register_dashboard_strategy(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NRWFloodConfigEntry) -> bool:
    """Set up NRW Flood from a config entry."""
    data = entry.data
    client = NRWApiClient(
        async_get_clientsession(hass),
        warnings_key=data.get(CONF_WARNINGS_KEY),
        levels_key=data.get(CONF_LEVELS_KEY),
        forecast_key=data.get(CONF_FORECAST_KEY),
    )

    runtime = NRWFloodRuntimeData(
        warnings=(
            WarningsCoordinator(hass, entry, client, selected(entry, CONF_FLOOD_AREAS))
            if data.get(CONF_WARNINGS_KEY)
            else None
        ),
        levels=(
            LevelsCoordinator(
                hass,
                entry,
                client,
                data[CONF_LATITUDE],
                data[CONF_LONGITUDE],
                data[CONF_RADIUS_KM],
                selected(entry, CONF_STATIONS),
            )
            if data.get(CONF_LEVELS_KEY)
            else None
        ),
        forecast=(
            ForecastCoordinator(hass, entry, client)
            if data.get(CONF_FORECAST_KEY)
            else None
        ),
    )

    for coordinator in runtime.coordinators:
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NRWFloodConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: NRWFloodConfigEntry
) -> None:
    """Reload when the chosen areas or stations change."""
    await hass.config_entries.async_reload(entry.entry_id)
