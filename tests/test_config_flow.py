"""Tests for the NRW Flood config, reauth and options flows."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.data_entry_flow import FlowResultType

from custom_components.nrw_flood.api import NRWAuthError, NRWConnectionError
from custom_components.nrw_flood.const import (
    CONF_FLOOD_AREAS,
    CONF_FORECAST_KEY,
    CONF_LEVELS_KEY,
    CONF_RADIUS_KM,
    CONF_STATIONS,
    CONF_WARNINGS_KEY,
    DOMAIN,
)
from custom_components.nrw_flood.models import parse_flood_areas, parse_stations
from tests.conftest import LAT, LON, load_fixture


def _areas():
    return parse_flood_areas(
        load_fixture("flood_areas_alert.json"), kind="alert"
    ) + parse_flood_areas(load_fixture("flood_areas_warning.json"), kind="warning")


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Patch the API client used by the config flow."""
    client = MagicMock()
    client.async_get_warnings = AsyncMock(return_value=[])
    client.async_get_flood_areas = AsyncMock(return_value=_areas())
    client.async_get_stations_near = AsyncMock(
        return_value=parse_stations(load_fixture("stations_near.json"))
    )
    client.async_get_areas_at_risk = AsyncMock(return_value=[])
    with patch(
        "custom_components.nrw_flood.config_flow.NRWApiClient", return_value=client
    ):
        yield client


@pytest.fixture(autouse=True)
def no_setup() -> Generator[None]:
    """Don't actually set up the entry once the flow creates it."""
    with patch("custom_components.nrw_flood.async_setup_entry", return_value=True):
        yield


def _user_input(**overrides):
    data = {
        CONF_WARNINGS_KEY: "w",
        CONF_LEVELS_KEY: "l",
        CONF_FORECAST_KEY: "f",
        CONF_LATITUDE: LAT,
        CONF_LONGITUDE: LON,
        CONF_RADIUS_KM: 15,
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_flow_all_apis(hass, mock_client) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    assert result["step_id"] == "areas"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FLOOD_AREAS: ["103WAFwyemon", "103FWF011a"]}
    )
    assert result["step_id"] == "stations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["4023", "4024"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_WARNINGS_KEY: "w",
        CONF_LEVELS_KEY: "l",
        CONF_FORECAST_KEY: "f",
        CONF_LATITUDE: LAT,
        CONF_LONGITUDE: LON,
        CONF_RADIUS_KM: 15,
        CONF_FLOOD_AREAS: ["103WAFwyemon", "103FWF011a"],
        CONF_STATIONS: ["4023", "4024"],
    }
    assert result["result"].unique_id == f"{LAT:.3f},{LON:.3f}"
    mock_client.async_get_flood_areas.assert_awaited_with(LAT, LON, radius_km=15)


async def test_defaults_to_home_location(hass, mock_client) -> None:
    hass.config.latitude = 52.0
    hass.config.longitude = -3.0

    result = await _start(hass)
    schema = result["data_schema"].schema
    defaults = {str(k): k.default() for k in schema if hasattr(k, "default")}

    assert defaults[CONF_LATITUDE] == 52.0
    assert defaults[CONF_LONGITUDE] == -3.0


async def test_warnings_only_skips_stations(hass, mock_client) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(**{CONF_LEVELS_KEY: None, CONF_FORECAST_KEY: None}),
    )
    assert result["step_id"] == "areas"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FLOOD_AREAS: ["103WAFwyemon"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_LEVELS_KEY not in result["data"]
    assert result["data"][CONF_STATIONS] == []
    mock_client.async_get_stations_near.assert_not_awaited()


async def test_levels_only_skips_areas(hass, mock_client) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(**{CONF_WARNINGS_KEY: None, CONF_FORECAST_KEY: None}),
    )
    assert result["step_id"] == "stations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["4023"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FLOOD_AREAS] == []


async def test_forecast_only_creates_entry_immediately(hass, mock_client) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(**{CONF_WARNINGS_KEY: None, CONF_LEVELS_KEY: None}),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FORECAST_KEY] == "f"


async def test_no_keys(hass, mock_client) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _user_input(
            **{CONF_WARNINGS_KEY: None, CONF_LEVELS_KEY: None, CONF_FORECAST_KEY: None}
        ),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_keys"}


@pytest.mark.parametrize(
    ("method", "field"),
    [
        ("async_get_warnings", CONF_WARNINGS_KEY),
        ("async_get_stations_near", CONF_LEVELS_KEY),
        ("async_get_areas_at_risk", CONF_FORECAST_KEY),
    ],
)
async def test_invalid_key_is_reported_against_its_field(
    hass, mock_client, method, field
) -> None:
    getattr(mock_client, method).side_effect = NRWAuthError("bad")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: "invalid_auth"}


async def test_cannot_connect(hass, mock_client) -> None:
    mock_client.async_get_warnings.side_effect = NRWConnectionError("down")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_flood_areas_unavailable_falls_back_to_typed_codes(
    hass, mock_client
) -> None:
    mock_client.async_get_flood_areas.side_effect = NRWConnectionError("down")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    assert result["step_id"] == "areas_manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FLOOD_AREAS: " 103WAFwyemon, 103FWF011a ,,"}
    )
    assert result["step_id"] == "stations"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATIONS: ["4023"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FLOOD_AREAS] == ["103WAFwyemon", "103FWF011a"]


async def test_typed_codes_must_not_be_empty(hass, mock_client) -> None:
    mock_client.async_get_flood_areas.side_effect = NRWConnectionError("down")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FLOOD_AREAS: " , "}
    )

    assert result["step_id"] == "areas_manual"
    assert result["errors"] == {CONF_FLOOD_AREAS: "no_codes"}


async def test_no_flood_areas_in_radius(hass, mock_client) -> None:
    mock_client.async_get_flood_areas.return_value = []

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["errors"] == {"base": "no_areas"}


async def test_no_stations_in_radius(hass, mock_client) -> None:
    mock_client.async_get_stations_near.return_value = []

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["errors"] == {"base": "no_stations"}


async def test_unexpected_error(hass, mock_client) -> None:
    mock_client.async_get_warnings.side_effect = RuntimeError("bug")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["errors"] == {"base": "unknown"}


async def test_same_location_aborts(hass, mock_client, mock_config_entry) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _user_input()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_only_given_keys(
    hass, mock_client, mock_config_entry
) -> None:
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LEVELS_KEY: "new-levels"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_LEVELS_KEY] == "new-levels"
    assert mock_config_entry.data[CONF_WARNINGS_KEY] == "warnings-key"


async def test_reauth_invalid_key(hass, mock_client, mock_config_entry) -> None:
    mock_client.async_get_warnings.side_effect = NRWAuthError("bad")

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WARNINGS_KEY: "still-bad"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_WARNINGS_KEY: "invalid_auth"}


async def test_options_reselect_areas_and_stations(
    hass, mock_client, mock_config_entry
) -> None:
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FLOOD_AREAS: ["103FWF011"], CONF_STATIONS: ["4049"]},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_FLOOD_AREAS: ["103FWF011"],
        CONF_STATIONS: ["4049"],
    }


async def test_reauth_cannot_connect(hass, mock_client, mock_config_entry) -> None:
    mock_client.async_get_warnings.side_effect = NRWConnectionError("down")

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WARNINGS_KEY: "new"}
    )

    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_typed_codes_when_areas_unavailable(
    hass, mock_client, mock_config_entry
) -> None:
    mock_client.async_get_flood_areas.side_effect = NRWConnectionError("down")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    defaults = {str(k): k.default() for k in schema if hasattr(k, "default")}
    assert defaults[CONF_FLOOD_AREAS] == "103WAFwyemon, 103FWF011a, 103FWF010a"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FLOOD_AREAS: "103FWF011", CONF_STATIONS: ["4023"]},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_FLOOD_AREAS] == ["103FWF011"]


async def test_options_abort_when_nrw_unreachable(
    hass, mock_client, mock_config_entry
) -> None:
    mock_client.async_get_stations_near.side_effect = NRWConnectionError("down")

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_options_abort_when_forecast_only(hass, mock_client) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_FORECAST_KEY: "f",
            CONF_LATITUDE: LAT,
            CONF_LONGITUDE: LON,
            CONF_RADIUS_KM: 5,
            CONF_FLOOD_AREAS: [],
            CONF_STATIONS: [],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_to_choose"


async def test_user_step_links_to_api_portal(hass, mock_client) -> None:
    result = await _start(hass)

    assert result["description_placeholders"] == {
        "portal_url": "https://api-portal.naturalresources.wales"
    }
