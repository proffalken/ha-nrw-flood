"""Tests for the NRW Flood data update coordinators."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.nrw_flood.api import NRWAuthError, NRWConnectionError
from custom_components.nrw_flood.const import EVENT_WARNING_CHANGED
from custom_components.nrw_flood.coordinator import (
    ForecastCoordinator,
    LevelsCoordinator,
    WarningsCoordinator,
)
from custom_components.nrw_flood.models import (
    Reading,
    parse_forecast,
    parse_history,
    parse_stations,
    parse_warnings,
)
from tests.conftest import LAT, LON, load_fixture

MONMOUTH_AREAS = ["103WAFwyemon", "103FWF011a", "103FWF010a"]


def _warnings_client(payload_name: str) -> AsyncMock:
    client = AsyncMock()
    client.async_get_warnings.return_value = parse_warnings(load_fixture(payload_name))
    return client


async def test_warnings_filtered_to_chosen_areas_and_in_force(
    hass, mock_config_entry
) -> None:
    coordinator = WarningsCoordinator(
        hass,
        mock_config_entry,
        _warnings_client("warnings_active.json"),
        MONMOUTH_AREAS,
    )

    data = await coordinator._async_update_data()

    # The Taff severe warning is outside the chosen areas, and Forge Road
    # is "no longer in force".
    assert [w.code for w in data.warnings] == ["103WAFwyemon", "103FWF011a"]
    assert data.level == "warning"


async def test_no_warnings(hass, mock_config_entry) -> None:
    coordinator = WarningsCoordinator(
        hass, mock_config_entry, _warnings_client("warnings_empty.json"), MONMOUTH_AREAS
    )

    data = await coordinator._async_update_data()

    assert data.warnings == []
    assert data.level == "none"


async def test_warnings_auth_error(hass, mock_config_entry) -> None:
    client = AsyncMock()
    client.async_get_warnings.side_effect = NRWAuthError("nope")
    coordinator = WarningsCoordinator(hass, mock_config_entry, client, MONMOUTH_AREAS)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_warnings_connection_error(hass, mock_config_entry) -> None:
    client = AsyncMock()
    client.async_get_warnings.side_effect = NRWConnectionError("down")
    coordinator = WarningsCoordinator(hass, mock_config_entry, client, MONMOUTH_AREAS)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_events_not_fired_on_first_refresh(hass, mock_config_entry) -> None:
    events = async_capture_events(hass, EVENT_WARNING_CHANGED)
    coordinator = WarningsCoordinator(
        hass,
        mock_config_entry,
        _warnings_client("warnings_active.json"),
        MONMOUTH_AREAS,
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert events == []


async def test_events_for_issued_updated_removed(hass, mock_config_entry) -> None:
    events = async_capture_events(hass, EVENT_WARNING_CHANGED)
    warnings = parse_warnings(load_fixture("warnings_active.json"))
    alert, warning = warnings[0], warnings[1]
    client = AsyncMock()
    coordinator = WarningsCoordinator(hass, mock_config_entry, client, MONMOUTH_AREAS)

    # First poll: just the alert. No events.
    client.async_get_warnings.return_value = [alert]
    await coordinator.async_refresh()

    # Second poll: the alert is upgraded to a warning, and a new warning appears.
    upgraded = replace(alert, severity_value=2)
    client.async_get_warnings.return_value = [upgraded, warning]
    await coordinator.async_refresh()

    # Third poll: everything removed.
    client.async_get_warnings.return_value = []
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    changes = [(e.data["change"], e.data["code"], e.data["level"]) for e in events]
    assert changes == [
        ("updated", "103WAFwyemon", "warning"),
        ("issued", "103FWF011a", "warning"),
        ("removed", "103WAFwyemon", None),
        ("removed", "103FWF011a", None),
    ]
    assert events[0].data["previous_level"] == "alert"
    assert events[0].data["config_entry_id"] == mock_config_entry.entry_id
    assert events[1].data["description"] == (
        "Rivers Wye and Monnow at Monmouth, defended areas"
    )


async def test_event_when_message_changes(hass, mock_config_entry) -> None:
    events = async_capture_events(hass, EVENT_WARNING_CHANGED)
    alert = parse_warnings(load_fixture("warnings_active.json"))[0]
    client = AsyncMock()
    coordinator = WarningsCoordinator(hass, mock_config_entry, client, MONMOUTH_AREAS)

    client.async_get_warnings.return_value = [alert]
    await coordinator.async_refresh()
    client.async_get_warnings.return_value = [
        replace(alert, message="Levels still rising.")
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [(e.data["change"], e.data["message"]) for e in events] == [
        ("updated", "Levels still rising.")
    ]


def _levels_client() -> AsyncMock:
    client = AsyncMock()
    client.async_get_stations_near.return_value = parse_stations(
        load_fixture("stations_near.json")
    )
    client.async_get_history.side_effect = lambda station_id, parameter: parse_history(
        load_fixture(f"history_{station_id}.json")
    )
    return client


async def test_levels_only_chosen_stations(hass, mock_config_entry) -> None:
    client = _levels_client()
    coordinator = LevelsCoordinator(
        hass, mock_config_entry, client, LAT, LON, 15, ["4023", "4024"]
    )

    data = await coordinator._async_update_data()

    assert set(data) == {"4023", "4024"}
    assert data["4023"].station.title == "Wye at Monmouth"
    client.async_get_stations_near.assert_awaited_with(LAT, LON, radius_km=15)


async def test_levels_seeds_history_once_so_rate_is_known(
    hass, mock_config_entry
) -> None:
    client = _levels_client()
    coordinator = LevelsCoordinator(
        hass, mock_config_entry, client, LAT, LON, 15, ["4023", "4024"]
    )

    data = await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert data["4023"].rate is not None
    assert client.async_get_history.await_count == 2  # once per station, ever


async def test_levels_rate_uses_new_readings(hass, mock_config_entry) -> None:
    base = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    station = next(
        s
        for s in parse_stations(load_fixture("stations_near.json"))
        if s.station_id == 4023
    )
    client = AsyncMock()
    client.async_get_history.side_effect = lambda *_: [
        Reading(base + timedelta(minutes=15 * i), 1.0) for i in range(5)
    ]
    client.async_get_stations_near.return_value = [
        replace(station, latest_value=1.6, latest_time=base + timedelta(minutes=75))
    ]
    coordinator = LevelsCoordinator(
        hass, mock_config_entry, client, LAT, LON, 15, ["4023"]
    )

    data = await coordinator._async_update_data()

    # 1.0m at 12:15 -> 1.6m at 13:15
    assert data["4023"].rate == pytest.approx(0.6)


async def test_levels_history_failure_is_not_fatal(hass, mock_config_entry) -> None:
    client = _levels_client()
    client.async_get_history.side_effect = NRWConnectionError("slow")
    coordinator = LevelsCoordinator(
        hass, mock_config_entry, client, LAT, LON, 15, ["4023"]
    )

    data = await coordinator._async_update_data()

    assert data["4023"].station.latest_value is not None
    assert data["4023"].rate is None


async def test_levels_auth_error(hass, mock_config_entry) -> None:
    client = AsyncMock()
    client.async_get_stations_near.side_effect = NRWAuthError("nope")
    coordinator = LevelsCoordinator(
        hass, mock_config_entry, client, LAT, LON, 15, ["4023"]
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_forecast(hass, mock_config_entry) -> None:
    client = AsyncMock()
    client.async_get_forecast.return_value = parse_forecast(
        load_fixture("forecast_summary.json")
    )
    client.async_get_areas_at_risk.return_value = []
    coordinator = ForecastCoordinator(hass, mock_config_entry, client)

    data = await coordinator._async_update_data()

    assert data.forecast.summary.startswith("Local inland flooding")
    assert data.areas_at_risk == []


async def test_forecast_connection_error(hass, mock_config_entry) -> None:
    client = AsyncMock()
    client.async_get_forecast.side_effect = NRWConnectionError("down")
    coordinator = ForecastCoordinator(hass, mock_config_entry, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
