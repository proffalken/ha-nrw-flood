"""Sensors for the NRW Flood integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NRWFloodConfigEntry, selected
from .const import CONF_STATIONS, LEVELS, STATION_URL, TRENDS
from .coordinator import (
    ForecastCoordinator,
    ForecastData,
    LevelsCoordinator,
    StationData,
    WarningsCoordinator,
    WarningsData,
)
from .entity import NRWFloodEntity

type StateValue = str | int | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class WarningsSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WarningsData], StateValue]
    attrs_fn: Callable[[WarningsData], dict[str, Any]] = lambda _: {}


@dataclass(frozen=True, kw_only=True)
class StationSensorDescription(SensorEntityDescription):
    value_fn: Callable[[StationData], StateValue]


@dataclass(frozen=True, kw_only=True)
class ForecastSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ForecastData], StateValue]
    attrs_fn: Callable[[ForecastData], dict[str, Any]] = lambda _: {}


WARNING_SENSORS = (
    WarningsSensorDescription(
        key="warning_level",
        translation_key="warning_level",
        device_class=SensorDeviceClass.ENUM,
        options=list(LEVELS),
        value_fn=lambda d: d.level,
        attrs_fn=lambda d: {"warnings": [w.as_dict() for w in d.warnings]},
    ),
    WarningsSensorDescription(
        key="active_warnings",
        translation_key="active_warnings",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.warnings),
    ),
)

STATION_SENSORS = (
    StationSensorDescription(
        key="level",
        translation_key="level",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda d: d.station.latest_value,
    ),
    StationSensorDescription(
        key="rate_of_change",
        translation_key="rate_of_change",
        native_unit_of_measurement="m/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda d: d.rate,
    ),
    StationSensorDescription(
        key="trend",
        translation_key="trend",
        device_class=SensorDeviceClass.ENUM,
        options=list(TRENDS),
        value_fn=lambda d: d.station.trend,
    ),
    StationSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.station.latest_time,
    ),
)

FORECAST_SENSORS = (
    ForecastSensorDescription(
        key="forecast_issued",
        translation_key="forecast_issued",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.forecast.issued,
        attrs_fn=lambda d: {"summary": d.forecast.summary, "days": d.forecast.days},
    ),
    ForecastSensorDescription(
        key="areas_at_risk",
        translation_key="areas_at_risk",
        value_fn=lambda d: len(d.areas_at_risk),
        attrs_fn=lambda d: {"areas": d.areas_at_risk},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NRWFloodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for whichever APIs are configured."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = []

    if runtime.warnings:
        entities += [
            WarningsSensor(runtime.warnings, entry, d) for d in WARNING_SENSORS
        ]
    if runtime.levels:
        for station_id in selected(entry, CONF_STATIONS):
            entities += [
                StationSensor(runtime.levels, entry, station_id, d)
                for d in STATION_SENSORS
            ]
    if runtime.forecast:
        entities += [
            ForecastSensor(runtime.forecast, entry, d) for d in FORECAST_SENSORS
        ]

    async_add_entities(entities)


class WarningsSensor(NRWFloodEntity[WarningsCoordinator], SensorEntity):
    """A sensor summarising warnings in force in the chosen areas."""

    entity_description: WarningsSensorDescription

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
    def native_value(self) -> StateValue:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)


class StationSensor(NRWFloodEntity[LevelsCoordinator], SensorEntity):
    """A sensor for one reading at one river level station."""

    entity_description: StationSensorDescription

    def __init__(self, coordinator, entry, station_id: str, description) -> None:
        current = (coordinator.data or {}).get(station_id)
        super().__init__(
            coordinator,
            entry,
            device_key=f"station_{station_id}",
            device_name=current.station.title if current else f"Station {station_id}",
            model="River level station",
            key=f"{station_id}_{description.key}",
            configuration_url=STATION_URL.format(station_id),
        )
        self.entity_description = description
        self._station_id = station_id

    @property
    def _station_data(self) -> StationData | None:
        return (self.coordinator.data or {}).get(self._station_id)

    @property
    def available(self) -> bool:
        return super().available and self._station_data is not None

    @property
    def native_value(self) -> StateValue:
        data = self._station_data
        return self.entity_description.value_fn(data) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._station_data
        if data is None or self.entity_description.key != "level":
            return None
        return {
            "station_id": data.station.station_id,
            "station_url": data.station.url,
            "station_status": data.station.status,
            "nrw_status": data.station.trend_raw,
        }


class ForecastSensor(NRWFloodEntity[ForecastCoordinator], SensorEntity):
    """A sensor for the Wales-wide 5-day flood risk forecast."""

    entity_description: ForecastSensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(
            coordinator,
            entry,
            device_key="forecast",
            device_name="NRW flood risk forecast",
            model="5-day flood risk forecast",
            key=description.key,
        )
        self.entity_description = description

    @property
    def native_value(self) -> StateValue:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data)
