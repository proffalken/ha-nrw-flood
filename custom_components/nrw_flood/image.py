"""Image entities for the daily maps in the NRW flood risk forecast.

The forecast summary text covers the whole of Wales and doesn't name areas.
Its maps are the only place NRW shows the risk area by area.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import NRWFloodConfigEntry
from .coordinator import ForecastCoordinator
from .entity import NRWFloodEntity

FORECAST_DAYS = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NRWFloodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one map per forecast day, if the forecast API is configured."""
    forecast = entry.runtime_data.forecast
    if forecast:
        async_add_entities(
            ForecastMap(hass, forecast, entry, day) for day in range(FORECAST_DAYS)
        )


class ForecastMap(NRWFloodEntity[ForecastCoordinator], ImageEntity):
    """NRW's flood risk map for one day of the 5-day forecast."""

    _attr_content_type = "image/png"

    def __init__(self, hass, coordinator, entry, day: int) -> None:
        key = f"forecast_map_day_{day + 1}"
        super().__init__(
            coordinator,
            entry,
            device_key="forecast",
            device_name="NRW flood risk forecast",
            model="5-day flood risk forecast",
            key=key,
        )
        ImageEntity.__init__(self, hass)
        self._attr_translation_key = key
        self._day = day
        self._image_last_updated()

    def _map(self) -> bytes | None:
        maps = self.coordinator.data.forecast.maps if self.coordinator.data else []
        return maps[self._day] if self._day < len(maps) else None

    def _image_last_updated(self) -> None:
        data = self.coordinator.data
        issued: datetime | None = data.forecast.issued if data else None
        self._attr_image_last_updated = issued or dt_util.utcnow()

    @property
    def available(self) -> bool:
        return super().available and self._map() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        days = self.coordinator.data.forecast.days if self.coordinator.data else []
        return {"day": days[self._day] if self._day < len(days) else None}

    @callback
    def _handle_coordinator_update(self) -> None:
        self._image_last_updated()
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self._map()
