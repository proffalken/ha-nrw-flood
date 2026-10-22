"""Diagnostics support for the NRW Flood integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NRWFloodConfigEntry
from .const import API_KEYS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NRWFloodConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with every API key redacted."""
    runtime = entry.runtime_data
    result: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), set(API_KEYS)),
            "options": dict(entry.options),
        }
    }
    if runtime.warnings and runtime.warnings.data:
        data = runtime.warnings.data
        result["warnings"] = {
            "level": data.level,
            "warnings": [w.as_dict() for w in data.warnings],
        }
    if runtime.levels and runtime.levels.data is not None:
        result["levels"] = {
            key: {
                "title": d.station.title,
                "value": d.station.latest_value,
                "time": d.station.latest_time.isoformat()
                if d.station.latest_time
                else None,
                "nrw_status": d.station.trend_raw,
                "rate": d.rate,
            }
            for key, d in runtime.levels.data.items()
        }
    if runtime.forecast and runtime.forecast.data:
        data = runtime.forecast.data
        result["forecast"] = {
            "issued": data.forecast.issued.isoformat()
            if data.forecast.issued
            else None,
            "summary": data.forecast.summary,
            "days": data.forecast.days,
            "areas_at_risk": data.areas_at_risk,
        }
    return result
