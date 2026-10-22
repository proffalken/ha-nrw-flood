"""Tests for the NRW API client."""

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.nrw_flood.api import (
    NRWApiClient,
    NRWAuthError,
    NRWConnectionError,
)
from custom_components.nrw_flood.const import (
    KEY_HEADER,
    WFS_LAYER_ALERT,
    WFS_LAYER_WARNING,
    WFS_URL,
)
from tests.conftest import LAT, LON, load_fixture
from tests.urls import (
    AREAS_AT_RISK_URL,
    FORECAST_URL,
    HISTORY_URL,
    STATIONS_URL,
    WARNINGS_URL,
)


@pytest.fixture
async def client(hass, aioclient_mock) -> NRWApiClient:
    return NRWApiClient(
        async_get_clientsession(hass),
        warnings_key="w-key",
        levels_key="l-key",
        forecast_key="f-key",
    )


def _headers(aioclient_mock, index=0) -> dict:
    return aioclient_mock.mock_calls[index][3]


def _url(aioclient_mock, index=0):
    return aioclient_mock.mock_calls[index][1]


async def test_get_warnings_uses_warnings_key(client, aioclient_mock) -> None:
    aioclient_mock.get(WARNINGS_URL, json=load_fixture("warnings_active.json"))

    warnings = await client.async_get_warnings()

    assert len(warnings) == 4
    assert _headers(aioclient_mock)[KEY_HEADER] == "w-key"


async def test_get_stations_near_sends_metres(client, aioclient_mock) -> None:
    aioclient_mock.get(STATIONS_URL, json=load_fixture("stations_near.json"))

    stations = await client.async_get_stations_near(LAT, LON, radius_km=15)

    assert len(stations) == 5
    url = _url(aioclient_mock)
    assert url.query["distance"] == "15000"
    assert url.query["lat"] == str(LAT)
    assert url.query["lon"] == str(LON)
    assert _headers(aioclient_mock)[KEY_HEADER] == "l-key"


async def test_get_history(client, aioclient_mock) -> None:
    aioclient_mock.get(HISTORY_URL, json=load_fixture("history_4023.json"))

    readings = await client.async_get_history(4023, 199)

    assert len(readings) == 24
    url = _url(aioclient_mock)
    assert url.query["location"] == "4023"
    assert url.query["parameter"] == "199"


async def test_get_forecast_uses_forecast_key(client, aioclient_mock) -> None:
    aioclient_mock.get(FORECAST_URL, json=load_fixture("forecast_summary.json"))

    forecast = await client.async_get_forecast()

    assert forecast.summary
    assert _headers(aioclient_mock)[KEY_HEADER] == "f-key"


async def test_get_areas_at_risk(client, aioclient_mock) -> None:
    aioclient_mock.get(AREAS_AT_RISK_URL, json=[])

    assert await client.async_get_areas_at_risk() == []


async def test_get_flood_areas_queries_both_layers_without_key(
    client, aioclient_mock
) -> None:
    aioclient_mock.get(
        WFS_URL,
        params={"typeNames": WFS_LAYER_WARNING},
        json=load_fixture("flood_areas_warning.json"),
    )
    aioclient_mock.get(
        WFS_URL,
        params={"typeNames": WFS_LAYER_ALERT},
        json=load_fixture("flood_areas_alert.json"),
    )

    areas = await client.async_get_flood_areas(LAT, LON, radius_km=3)

    assert {a.kind for a in areas} == {"warning", "alert"}
    assert len(areas) == 5
    assert aioclient_mock.call_count == 2
    for index in range(2):
        assert KEY_HEADER not in (_headers(aioclient_mock, index) or {})
        cql = _url(aioclient_mock, index).query["cql_filter"]
        assert "3000,meters" in cql
        assert f"POINT({LON} {LAT})" in cql


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_error(client, aioclient_mock, status) -> None:
    aioclient_mock.get(WARNINGS_URL, status=status)

    with pytest.raises(NRWAuthError):
        await client.async_get_warnings()


async def test_server_error(client, aioclient_mock) -> None:
    aioclient_mock.get(WARNINGS_URL, status=500)

    with pytest.raises(NRWConnectionError):
        await client.async_get_warnings()


async def test_connection_error(client, aioclient_mock) -> None:
    aioclient_mock.get(WARNINGS_URL, exc=aiohttp.ClientConnectionError("boom"))

    with pytest.raises(NRWConnectionError):
        await client.async_get_warnings()


async def test_timeout(client, aioclient_mock) -> None:
    aioclient_mock.get(WARNINGS_URL, exc=TimeoutError())

    with pytest.raises(NRWConnectionError):
        await client.async_get_warnings()


async def test_bad_json(client, aioclient_mock) -> None:
    aioclient_mock.get(WARNINGS_URL, text="<html>nope</html>")

    with pytest.raises(NRWConnectionError):
        await client.async_get_warnings()


async def test_missing_key_is_a_programming_error(hass) -> None:
    client = NRWApiClient(
        async_get_clientsession(hass),
        warnings_key=None,
        levels_key=None,
        forecast_key=None,
    )

    with pytest.raises(ValueError):
        await client.async_get_warnings()


@pytest.mark.parametrize("status", [401, 403, 503])
async def test_datamapwales_refusal_is_unavailable_not_auth(
    client, aioclient_mock, status
) -> None:
    # DataMapWales serves its "Service unavailable" page with a 403, and it
    # takes no key, so a refusal must never be reported as a bad key.
    aioclient_mock.get(WFS_URL, status=status, text="<html>Service unavailable</html>")

    with pytest.raises(NRWConnectionError):
        await client.async_get_flood_areas(LAT, LON, radius_km=3)
