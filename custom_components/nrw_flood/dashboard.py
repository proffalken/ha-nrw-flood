"""Serve the NRW Flood dashboard strategy to the Home Assistant frontend."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

STRATEGY_URL: Final = "/nrw_flood_static/nrw-flood-strategy.js"
_STRATEGY_FILE: Final = Path(__file__).parent / "frontend" / "nrw-flood-strategy.js"


async def async_register_dashboard_strategy(hass: HomeAssistant) -> None:
    """Serve the strategy file and load it on every frontend page.

    The URL carries the integration version so browsers fetch the new file
    after an upgrade instead of using a cached copy.
    """
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STRATEGY_URL, str(_STRATEGY_FILE), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{STRATEGY_URL}?v={integration.version}")
