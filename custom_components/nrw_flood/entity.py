"""Shared base entity for NRW Flood platforms."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import ATTRIBUTION, DOMAIN

MANUFACTURER = "Natural Resources Wales"


class NRWFloodEntity[CoordinatorT: DataUpdateCoordinator](
    CoordinatorEntity[CoordinatorT]
):
    """Base entity: one device per data source, unique IDs scoped to the entry."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: CoordinatorT,
        entry: ConfigEntry,
        device_key: str,
        device_name: str,
        model: str,
        key: str,
        configuration_url: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{device_key}")},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=model,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=configuration_url,
        )
