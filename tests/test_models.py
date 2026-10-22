"""Tests for parsing NRW API payloads into models."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.nrw_flood.models import (
    Reading,
    highest_level,
    parse_areas_at_risk,
    parse_flood_areas,
    parse_forecast,
    parse_history,
    parse_nrw_time,
    parse_stations,
    parse_warnings,
    rate_of_change,
    trend_from_status,
)
from tests.conftest import load_fixture


def test_parse_warnings_empty() -> None:
    assert parse_warnings(load_fixture("warnings_empty.json")) == []


def test_parse_warnings_active() -> None:
    warnings = parse_warnings(load_fixture("warnings_active.json"))

    assert [w.code for w in warnings] == [
        "103WAFwyemon",
        "103FWF011a",
        "103FWF010a",
        "102FWF043",
    ]
    alert, warning, removed, severe = warnings
    assert alert.level == "alert"
    assert warning.level == "warning"
    assert severe.level == "severe"
    assert removed.level is None
    assert removed.in_force is False
    assert alert.in_force is True
    assert alert.description == "Rivers Wye and Monnow in Monmouthshire"
    assert alert.message == "River levels are rising on the Wye and Monnow."
    assert alert.tidal is False
    assert severe.tidal is True


def test_warning_times_are_uk_local() -> None:
    alert = parse_warnings(load_fixture("warnings_active.json"))[0]

    # 06:30 in October is BST (UTC+1).
    assert alert.raised == datetime(2026, 10, 22, 5, 30, tzinfo=UTC)


def test_warning_as_dict_is_json_friendly() -> None:
    alert = parse_warnings(load_fixture("warnings_active.json"))[0]

    data = alert.as_dict()

    assert data["code"] == "103WAFwyemon"
    assert data["level"] == "alert"
    assert data["raised"] == "2026-10-22T05:30:00+00:00"


def test_parse_warnings_skips_features_without_code() -> None:
    payload = {"features": [{"properties": {"SEVERITYVALUE": 2}}, {"nope": 1}]}

    assert parse_warnings(payload) == []


def test_highest_level() -> None:
    warnings = parse_warnings(load_fixture("warnings_active.json"))

    assert highest_level([]) == "none"
    assert highest_level(warnings[:1]) == "alert"
    assert highest_level(warnings[:2]) == "warning"
    assert highest_level(warnings) == "severe"
    assert highest_level(warnings[2:3]) == "none"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-15T06:30:00", datetime(2026, 1, 15, 6, 30, tzinfo=UTC)),
        ("2026-10-22T15:00:00Z", datetime(2026, 10, 22, 15, 0, tzinfo=UTC)),
        ("10/22/2026 09:30:00 AM", datetime(2026, 10, 22, 8, 30, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_nrw_time(raw, expected) -> None:
    assert parse_nrw_time(raw) == expected


def test_parse_stations_keeps_river_levels() -> None:
    stations = parse_stations(load_fixture("stations_near.json"))

    by_id = {s.station_id: s for s in stations}
    assert set(by_id) == {4021, 4023, 4024, 4028, 4049}
    wye = by_id[4023]
    assert wye.title == "Wye at Monmouth"
    assert wye.parameter == 199
    assert wye.units == "m"
    assert isinstance(wye.latest_value, float)
    assert wye.latest_time.tzinfo is not None
    assert wye.url == "https://rivers-and-seas.naturalresources.wales/station/4023"


def test_parse_stations_ignores_rainfall() -> None:
    payload = [
        {
            "location": 1000,
            "titleEn": "Some raingauge",
            "nameEN": "Some",
            "statusEN": "Online",
            "parameters": [
                {
                    "parameter": 10095,
                    "paramNameEN": "Rainfall",
                    "units": "mm",
                    "latestValue": 0.0,
                    "latestTime": "2026-10-22T15:00:00Z",
                }
            ],
        }
    ]

    assert parse_stations(payload) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Level Rising", "rising"),
        ("Level Falling", "falling"),
        ("Level Steady", "steady"),
        ("Something new", None),
        (None, None),
    ],
)
def test_trend_from_status(raw, expected) -> None:
    assert trend_from_status(raw) == expected


def test_parse_history() -> None:
    readings = parse_history(load_fixture("history_4023.json"))

    assert len(readings) == 24
    assert readings == sorted(readings, key=lambda r: r.time)
    assert readings[-1].time == datetime(2026, 10, 22, 15, 0, tzinfo=UTC)


def _readings(start: datetime, values: list[float]) -> list[Reading]:
    return [
        Reading(time=start + timedelta(minutes=15 * i), value=v)
        for i, v in enumerate(values)
    ]


def test_rate_of_change_over_an_hour() -> None:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    readings = _readings(start, [1.0, 1.1, 1.2, 1.3, 1.5])

    assert rate_of_change(readings) == pytest.approx(0.5)


def test_rate_of_change_falling() -> None:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    readings = _readings(start, [2.0, 1.9, 1.8, 1.7, 1.6])

    assert rate_of_change(readings) == pytest.approx(-0.4)


def test_rate_of_change_needs_an_hour_of_data() -> None:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    assert rate_of_change(_readings(start, [1.0, 1.1, 1.2])) is None
    assert rate_of_change([]) is None


def test_parse_flood_areas() -> None:
    warning_areas = parse_flood_areas(
        load_fixture("flood_areas_warning.json"), kind="warning"
    )
    alert_areas = parse_flood_areas(
        load_fixture("flood_areas_alert.json"), kind="alert"
    )

    assert [a.code for a in alert_areas] == ["103WAFwyemon"]
    assert alert_areas[0].name == "Rivers Wye and Monnow in Monmouthshire"
    assert alert_areas[0].kind == "alert"
    assert {a.code for a in warning_areas} == {
        "103FWF011",
        "103FWF011a",
        "103FWF010b",
        "103FWF010a",
    }


def test_parse_forecast() -> None:
    forecast = parse_forecast(load_fixture("forecast_summary.json"))

    assert forecast.issued == datetime(2026, 10, 22, 8, 30, tzinfo=UTC)
    assert forecast.summary.startswith("Local inland flooding is possible")
    assert forecast.days == [
        "Thursday 22 October 2026",
        "Friday 23 October 2026",
        "Saturday 24 October 2026",
        "Sunday 25 October 2026",
        "Monday 26 October 2026",
    ]


def test_parse_areas_at_risk() -> None:
    assert parse_areas_at_risk(load_fixture("areas_at_risk_empty.json")) == []
    assert parse_areas_at_risk([{"a": 1}]) == [{"a": 1}]
    assert parse_areas_at_risk({"unexpected": True}) == []
