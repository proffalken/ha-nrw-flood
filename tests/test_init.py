"""Tests for setting up the integration and its entities end to end."""

from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nrw_flood.const import (
    CONF_FORECAST_KEY,
    CONF_LEVELS_KEY,
    CONF_STATIONS,
    DOMAIN,
)
from custom_components.nrw_flood.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.conftest import load_fixture
from tests.urls import (
    AREAS_AT_RISK_URL,
    FORECAST_URL,
    HISTORY_URL,
    STATIONS_URL,
    WARNINGS_URL,
)


def _mock_all(aioclient_mock, warnings="warnings_active.json") -> None:
    aioclient_mock.get(WARNINGS_URL, json=load_fixture(warnings))
    aioclient_mock.get(STATIONS_URL, json=load_fixture("stations_near.json"))
    for station in ("4023", "4024"):
        aioclient_mock.get(
            HISTORY_URL,
            params={"location": station},
            json=load_fixture(f"history_{station}.json"),
        )
    # Any other station: no history available.
    aioclient_mock.get(HISTORY_URL, status=503)
    aioclient_mock.get(FORECAST_URL, json=load_fixture("forecast_summary.json"))
    aioclient_mock.get(AREAS_AT_RISK_URL, json=[])


async def _setup(hass, entry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_id(hass, unique_suffix: str, platform: str) -> str:
    registry = er.async_get(hass)
    for entity in registry.entities.values():
        # Unique IDs are "<entry_id>_<key>", and entry IDs have no underscores.
        if (
            entity.platform == DOMAIN
            and entity.domain == platform
            and entity.unique_id.partition("_")[2] == unique_suffix.lstrip("_")
        ):
            return entity.entity_id
    raise AssertionError(f"No {platform} entity ending {unique_suffix}")


def _state(hass, unique_suffix: str, platform: str = "sensor"):
    return hass.states.get(_entity_id(hass, unique_suffix, platform))


async def test_setup_creates_all_entities(
    hass, mock_config_entry, aioclient_mock
) -> None:
    _mock_all(aioclient_mock)
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    level = _state(hass, "_warning_level")
    assert level.state == "warning"
    assert [w["code"] for w in level.attributes["warnings"]] == [
        "103WAFwyemon",
        "103FWF011a",
    ]
    assert _state(hass, "_active_warnings").state == "2"
    assert _state(hass, "_flood_alert", "binary_sensor").state == "on"
    assert _state(hass, "_flood_warning", "binary_sensor").state == "on"
    assert _state(hass, "_severe_flood_warning", "binary_sensor").state == "off"

    wye_level = _state(hass, "_4023_level")
    assert float(wye_level.state) > 0
    assert wye_level.attributes["unit_of_measurement"] == "m"
    assert wye_level.attributes["station_url"].endswith("/station/4023")
    assert _state(hass, "_4023_trend").state in {"rising", "falling", "steady"}
    rate = _state(hass, "_4023_rate_of_change")
    assert rate.attributes["unit_of_measurement"] == "m/h"
    assert rate.state not in ("unknown", "unavailable")
    last = _state(hass, "_4023_last_reading")
    assert datetime.fromisoformat(last.state).tzinfo is not None

    issued = _state(hass, "_forecast_issued")
    assert datetime.fromisoformat(issued.state) == datetime(
        2026, 10, 22, 8, 30, tzinfo=UTC
    )
    assert issued.attributes["summary"].startswith("Local inland flooding")
    assert len(issued.attributes["days"]) == 5
    assert _state(hass, "_areas_at_risk").state == "0"


async def test_quiet_day(hass, mock_config_entry, aioclient_mock) -> None:
    _mock_all(aioclient_mock, warnings="warnings_empty.json")
    await _setup(hass, mock_config_entry)

    assert _state(hass, "_warning_level").state == "none"
    assert _state(hass, "_flood_alert", "binary_sensor").state == "off"


async def test_only_configured_apis_are_polled(hass, aioclient_mock) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="NRW Flood",
        data={
            CONF_FORECAST_KEY: "f",
            "latitude": 51.8,
            "longitude": -2.7,
            "radius_km": 5,
            "flood_areas": [],
            "stations": [],
        },
        unique_id="51.800,-2.700",
    )
    entry.add_to_hass(hass)
    _mock_all(aioclient_mock)

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert all("floodforecast" in str(c[1]) for c in aioclient_mock.mock_calls)
    registry = er.async_get(hass)
    assert not [
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "binary_sensor"
    ]


async def test_options_override_stations(
    hass, mock_config_entry, aioclient_mock
) -> None:
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_STATIONS: ["4049"]}
    )
    _mock_all(aioclient_mock)

    await _setup(hass, mock_config_entry)

    assert _state(hass, "_4049_level").state not in ("unknown", "unavailable")
    # No history for Skenfrith, so no rate yet - but setup still succeeds.
    assert _state(hass, "_4049_rate_of_change").state == "unknown"
    registry = er.async_get(hass)
    assert not [
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN and "_4023_" in e.unique_id
    ]


async def test_auth_failure_starts_reauth(
    hass, mock_config_entry, aioclient_mock
) -> None:
    aioclient_mock.get(WARNINGS_URL, status=401)
    _mock_all(aioclient_mock)

    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_connection_failure_retries_setup(
    hass, mock_config_entry, aioclient_mock
) -> None:
    aioclient_mock.get(WARNINGS_URL, status=503)
    _mock_all(aioclient_mock)

    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass, mock_config_entry, aioclient_mock) -> None:
    _mock_all(aioclient_mock)
    await _setup(hass, mock_config_entry)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redacts_keys(
    hass, mock_config_entry, aioclient_mock
) -> None:
    _mock_all(aioclient_mock)
    await _setup(hass, mock_config_entry)

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    text = str(diag)
    assert "warnings-key" not in text
    assert "levels-key" not in text
    assert "forecast-key" not in text
    assert diag["entry"]["data"][CONF_LEVELS_KEY] == "**REDACTED**"
    assert diag["warnings"]["level"] == "warning"
    assert set(diag["levels"]) == {"4023", "4024"}
    assert diag["forecast"]["summary"].startswith("Local inland flooding")
