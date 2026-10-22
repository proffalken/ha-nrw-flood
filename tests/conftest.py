"""Shared fixtures for the NRW Flood test suite."""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nrw_flood.const import (
    CONF_FLOOD_AREAS,
    CONF_FORECAST_KEY,
    CONF_LEVELS_KEY,
    CONF_RADIUS_KM,
    CONF_STATIONS,
    CONF_WARNINGS_KEY,
    DOMAIN,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

LAT = 51.811
LON = -2.714

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for every test in this suite."""
    yield


def load_fixture(name: str) -> Any:
    """Load a JSON fixture by file name."""
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Config entry data with all three APIs configured."""
    return {
        CONF_WARNINGS_KEY: "warnings-key",
        CONF_LEVELS_KEY: "levels-key",
        CONF_FORECAST_KEY: "forecast-key",
        "latitude": LAT,
        "longitude": LON,
        CONF_RADIUS_KM: 15,
        CONF_FLOOD_AREAS: ["103WAFwyemon", "103FWF011a", "103FWF010a"],
        CONF_STATIONS: ["4023", "4024"],
    }


@pytest.fixture
def mock_config_entry(hass, entry_data) -> MockConfigEntry:
    """Return a MockConfigEntry already registered with hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="NRW Flood",
        data=entry_data,
        unique_id=f"{LAT:.3f},{LON:.3f}",
    )
    entry.add_to_hass(hass)
    return entry
