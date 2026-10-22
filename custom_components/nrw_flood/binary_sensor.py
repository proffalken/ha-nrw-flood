"""Binary sensors for the NRW Flood integration.

Each one is on when a warning at *or above* its level is in force in the
chosen areas, so "Flood alert" is also on during a flood warning.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NRWFloodConfigEntry
from .const import LEVEL_ALERT, LEVEL_SEVERE, LEVEL_WARNING, LEVELS
from .coordinator import WarningsCoordinator
from .entity import NRWFloodEntity


@dataclass(frozen=True, kw_only=True)
class FloodBinarySensorDescription(BinarySensorEntityDescription):
    min_level: str


BINARY_SENSORS = (
    FloodBinarySensorDescription(
        key="flood_alert", translation_key="flood_alert", min_level=LEVEL_ALERT
    ),
    FloodBinarySensorDescription(
        key="flood_warning", translation_key="flood_warning", min_level=LEVEL_WARNING
    ),
    FloodBinarySensorDescription(
        key="severe_flood_warning",
        translation_key="severe_flood_warning",
        min_level=LEVEL_SEVERE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NRWFloodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors if the warnings API is configured."""
    coordinator = entry.runtime_data.warnings
    if coordinator is None:
        return
    async_add_entities(
        FloodBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class FloodBinarySensor(NRWFloodEntity[WarningsCoordinator], BinarySensorEntity):
    """On while a warning at or above min_level is in force nearby."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    entity_description: FloodBinarySensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(
            coordinator,
            entry,
            device_key="warnings",
            device_name="NRW flood warnings",
            model="Live flood warnings and alerts",
            key=description.key,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        level = self.coordinator.data.level
        return LEVELS.index(level) >= LEVELS.index(self.entity_description.min_level)
