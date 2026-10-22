"""Run the client against the live NRW APIs and optionally save fixtures.

Keys come from environment variables and are never written anywhere:

    NRW_WARNINGS_KEY, NRW_LEVELS_KEY, NRW_FORECAST_KEY

Usage:
    uv run python scripts/capture_fixtures.py LAT LON RADIUS_KM [--save]

With --save, any response that has content worth testing against (for
example, warnings in force) is written to tests/fixtures/captured/ with a
timestamp, ready to be trimmed and promoted to a test fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.nrw_flood.api import NRWApiClient, NRWConnectionError  # noqa: E402
from custom_components.nrw_flood.const import API_BASE_URL, KEY_HEADER  # noqa: E402
from custom_components.nrw_flood.models import rate_of_change  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "captured"


async def _raw(session, path, key):
    async with session.get(f"{API_BASE_URL}{path}", headers={KEY_HEADER: key}) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


def _save(name: str, payload) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"{name}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"  saved {path.relative_to(OUT.parent.parent.parent)}")


async def main(lat: float, lon: float, radius: float, save: bool) -> None:
    keys = {
        "warnings": os.environ.get("NRW_WARNINGS_KEY"),
        "levels": os.environ.get("NRW_LEVELS_KEY"),
        "forecast": os.environ.get("NRW_FORECAST_KEY"),
    }
    async with aiohttp.ClientSession() as session:
        client = NRWApiClient(
            session,
            warnings_key=keys["warnings"],
            levels_key=keys["levels"],
            forecast_key=keys["forecast"],
        )

        try:
            areas = await client.async_get_flood_areas(lat, lon, radius_km=radius)
        except NRWConnectionError as err:
            print(f"Flood areas: DataMapWales unavailable ({err})")
        else:
            print(f"Flood areas within {radius} km: {len(areas)}")
            for area in areas:
                print(f"  {area.code:14} {area.kind:8} {area.name}")

        if keys["warnings"]:
            warnings = await client.async_get_warnings()
            in_force = [w for w in warnings if w.in_force]
            print(f"Warnings in Wales: {len(in_force)} in force, {len(warnings)} total")
            for w in warnings:
                print(f"  {w.code:14} {str(w.level):8} {w.description}")
            if save and warnings:
                _save(
                    "warnings",
                    await _raw(session, "/floodwarnings/v3/all", keys["warnings"]),
                )

        if keys["levels"]:
            stations = await client.async_get_stations_near(lat, lon, radius_km=radius)
            print(f"River level stations within {radius} km: {len(stations)}")
            for s in stations:
                history = await client.async_get_history(s.station_id, s.parameter)
                rate = rate_of_change(history[-8:])
                print(
                    f"  {s.station_id} {s.title:32} {s.latest_value} m "
                    f"{s.trend} rate={rate} m/h at {s.latest_time}"
                )

        if keys["forecast"]:
            forecast = await client.async_get_forecast()
            at_risk = await client.async_get_areas_at_risk()
            print(f"Forecast issued {forecast.issued}: {forecast.summary!r:.100}")
            print(f"Areas at risk: {len(at_risk)}")
            if save and at_risk:
                _save("areas_at_risk", at_risk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("radius_km", type=float)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.lat, args.lon, args.radius_km, args.save))
