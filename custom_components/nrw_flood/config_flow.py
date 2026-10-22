"""Config, reauth and options flows for the NRW Flood integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import selected
from .api import NRWApiClient, NRWAuthError, NRWConnectionError
from .const import (
    API_KEYS,
    CONF_FLOOD_AREAS,
    CONF_FORECAST_KEY,
    CONF_LEVELS_KEY,
    CONF_RADIUS_KM,
    CONF_STATIONS,
    CONF_WARNINGS_KEY,
    DEFAULT_RADIUS_KM,
    DOMAIN,
)
from .models import FloodArea, Station

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class _KeyRejected(Exception):
    """One of the API keys was rejected; carries the field it belongs to."""

    def __init__(self, field: str) -> None:
        self.field = field


def _client(hass, keys: Mapping[str, Any]) -> NRWApiClient:
    return NRWApiClient(
        async_get_clientsession(hass),
        warnings_key=keys.get(CONF_WARNINGS_KEY),
        levels_key=keys.get(CONF_LEVELS_KEY),
        forecast_key=keys.get(CONF_FORECAST_KEY),
    )


async def _check_keys(client: NRWApiClient, keys: Mapping[str, Any], lat, lon, radius):
    """Make one cheap call per given key. Returns nearby stations, if any."""
    stations: list[Station] = []
    checks = (
        (CONF_WARNINGS_KEY, client.async_get_warnings),
        (
            CONF_LEVELS_KEY,
            lambda: client.async_get_stations_near(lat, lon, radius_km=radius),
        ),
        (CONF_FORECAST_KEY, client.async_get_areas_at_risk),
    )
    for field, check in checks:
        if not keys.get(field):
            continue
        try:
            result = await check()
        except NRWAuthError as err:
            raise _KeyRejected(field) from err
        if field == CONF_LEVELS_KEY:
            stations = result
    return stations


def _area_options(areas: list[FloodArea]) -> list[SelectOptionDict]:
    ordered = sorted(areas, key=lambda a: (a.kind != "alert", a.name))
    return [
        SelectOptionDict(value=a.code, label=f"{a.name} ({a.kind} area)")
        for a in ordered
    ]


def _station_options(stations: list[Station]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=str(s.station_id), label=f"{s.title} ({s.station_id})")
        for s in sorted(stations, key=lambda s: s.title)
    ]


def _multi(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options, multiple=True))


def parse_codes(text: str) -> list[str]:
    """Split typed flood area codes on commas, dropping blanks."""
    return [code.strip() for code in text.split(",") if code.strip()]


def _keys_present(data: Mapping[str, Any]) -> dict[str, str]:
    return {k: data[k].strip() for k in API_KEYS if data.get(k, "").strip()}


class NRWFloodConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up NRW Flood: keys and location, then areas, then stations."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._areas: list[FloodArea] = []
        self._areas_unavailable = False
        self._stations: list[Station] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            keys = _keys_present(user_input)
            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]
            radius = user_input[CONF_RADIUS_KM]

            await self.async_set_unique_id(f"{lat:.3f},{lon:.3f}")
            self._abort_if_unique_id_configured()

            if not keys:
                errors["base"] = "no_keys"
            else:
                errors = await self._async_validate(keys, lat, lon, radius)

            if not errors:
                self._data = {
                    **keys,
                    CONF_LATITUDE: lat,
                    CONF_LONGITUDE: lon,
                    CONF_RADIUS_KM: radius,
                    CONF_FLOOD_AREAS: [],
                    CONF_STATIONS: [],
                }
                return await self._async_next_step()

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(user_input),
            errors=errors,
        )

    async def _async_validate(self, keys, lat, lon, radius) -> dict[str, str]:
        client = _client(self.hass, keys)
        self._areas_unavailable = False
        try:
            self._stations = await _check_keys(client, keys, lat, lon, radius)
            if keys.get(CONF_WARNINGS_KEY):
                try:
                    self._areas = await client.async_get_flood_areas(
                        lat, lon, radius_km=radius
                    )
                except NRWConnectionError:
                    # DataMapWales is down: let the user type codes instead.
                    _LOGGER.warning("DataMapWales unavailable; asking for area codes")
                    self._areas_unavailable = True
        except _KeyRejected as err:
            return {err.field: "invalid_auth"}
        except NRWConnectionError:
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error validating NRW keys")
            return {"base": "unknown"}

        if (
            keys.get(CONF_WARNINGS_KEY)
            and not self._areas_unavailable
            and not self._areas
        ):
            return {"base": "no_areas"}
        if keys.get(CONF_LEVELS_KEY) and not self._stations:
            return {"base": "no_stations"}
        return {}

    def _user_schema(self, user_input: dict[str, Any] | None) -> vol.Schema:
        defaults = user_input or {}
        return vol.Schema(
            {
                vol.Optional(
                    CONF_WARNINGS_KEY, default=defaults.get(CONF_WARNINGS_KEY, "")
                ): _PASSWORD,
                vol.Optional(
                    CONF_LEVELS_KEY, default=defaults.get(CONF_LEVELS_KEY, "")
                ): _PASSWORD,
                vol.Optional(
                    CONF_FORECAST_KEY, default=defaults.get(CONF_FORECAST_KEY, "")
                ): _PASSWORD,
                vol.Required(
                    CONF_LATITUDE,
                    default=defaults.get(CONF_LATITUDE, self.hass.config.latitude),
                ): cv.latitude,
                vol.Required(
                    CONF_LONGITUDE,
                    default=defaults.get(CONF_LONGITUDE, self.hass.config.longitude),
                ): cv.longitude,
                vol.Required(
                    CONF_RADIUS_KM,
                    default=defaults.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=50,
                        step=1,
                        unit_of_measurement="km",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )

    async def _async_next_step(self) -> ConfigFlowResult:
        if self._data.get(CONF_WARNINGS_KEY) and not self._data[CONF_FLOOD_AREAS]:
            if self._areas_unavailable:
                return await self.async_step_areas_manual()
            return await self.async_step_areas()
        if self._data.get(CONF_LEVELS_KEY) and not self._data[CONF_STATIONS]:
            return await self.async_step_stations()
        return self.async_create_entry(title="NRW Flood", data=self._data)

    async def async_step_areas(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None and user_input.get(CONF_FLOOD_AREAS):
            self._data[CONF_FLOOD_AREAS] = user_input[CONF_FLOOD_AREAS]
            return await self._async_next_step()

        options = _area_options(self._areas)
        return self.async_show_form(
            step_id="areas",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FLOOD_AREAS, default=[o["value"] for o in options]
                    ): _multi(options)
                }
            ),
        )

    async def async_step_areas_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Type flood area codes when DataMapWales can't list them."""
        errors: dict[str, str] = {}
        if user_input is not None:
            codes = parse_codes(user_input.get(CONF_FLOOD_AREAS, ""))
            if codes:
                self._data[CONF_FLOOD_AREAS] = codes
                return await self._async_next_step()
            errors[CONF_FLOOD_AREAS] = "no_codes"

        return self.async_show_form(
            step_id="areas_manual",
            data_schema=vol.Schema({vol.Required(CONF_FLOOD_AREAS): str}),
            errors=errors,
        )

    async def async_step_stations(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None and user_input.get(CONF_STATIONS):
            self._data[CONF_STATIONS] = user_input[CONF_STATIONS]
            return await self._async_next_step()

        options = _station_options(self._stations)
        return self.async_show_form(
            step_id="stations",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STATIONS, default=[o["value"] for o in options]
                    ): _multi(options)
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Started when NRW rejects one of the stored keys."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for replacement keys. Blank fields keep the stored key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            new_keys = _keys_present(user_input)
            data = entry.data
            client = _client(self.hass, new_keys)
            try:
                await _check_keys(
                    client,
                    new_keys,
                    data[CONF_LATITUDE],
                    data[CONF_LONGITUDE],
                    data[CONF_RADIUS_KM],
                )
            except _KeyRejected as err:
                errors[err.field] = "invalid_auth"
            except NRWConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating NRW keys")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, **new_keys}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Optional(key, default=""): _PASSWORD for key in API_KEYS}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NRWFloodOptionsFlow()


class NRWFloodOptionsFlow(OptionsFlow):
    """Re-pick the flood areas and stations to watch."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            areas = user_input.get(CONF_FLOOD_AREAS)
            if isinstance(areas, str):
                user_input = {**user_input, CONF_FLOOD_AREAS: parse_codes(areas)}
            return self.async_create_entry(data=user_input)

        entry = self.config_entry
        data = entry.data
        client = _client(self.hass, data)
        lat, lon, radius = (
            data[CONF_LATITUDE],
            data[CONF_LONGITUDE],
            data[CONF_RADIUS_KM],
        )
        schema: dict[Any, Any] = {}

        try:
            if data.get(CONF_WARNINGS_KEY):
                current = selected(entry, CONF_FLOOD_AREAS)
                try:
                    areas = await client.async_get_flood_areas(
                        lat, lon, radius_km=radius
                    )
                except NRWConnectionError:
                    # DataMapWales is down: edit the codes as text instead.
                    schema[
                        vol.Required(CONF_FLOOD_AREAS, default=", ".join(current))
                    ] = str
                else:
                    schema[vol.Required(CONF_FLOOD_AREAS, default=current)] = _multi(
                        _area_options(areas)
                    )
            if data.get(CONF_LEVELS_KEY):
                stations = await client.async_get_stations_near(
                    lat, lon, radius_km=radius
                )
                schema[
                    vol.Required(CONF_STATIONS, default=selected(entry, CONF_STATIONS))
                ] = _multi(_station_options(stations))
        except NRWAuthError, NRWConnectionError:
            return self.async_abort(reason="cannot_connect")

        if not schema:
            return self.async_abort(reason="nothing_to_choose")

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
