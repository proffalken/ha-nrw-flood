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
    trend_from_rate,
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
    readings = _readings(start, [1.0, 1.1, 1.2, 1.3, 1.4])

    assert rate_of_change(readings) == pytest.approx(0.4)


def test_rate_of_change_falling() -> None:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    readings = _readings(start, [2.0, 1.9, 1.8, 1.7, 1.6])

    assert rate_of_change(readings) == pytest.approx(-0.4)


def test_rate_of_change_uses_only_the_last_hour() -> None:
    start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    # Fast rise two hours ago, flat for the last hour.
    readings = _readings(start, [1.0, 1.5, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])

    assert rate_of_change(readings) == pytest.approx(0.0)


def test_one_wild_reading_does_not_move_the_rate() -> None:
    """Monnow Gate, 26 Oct 2026: one 2.748 m reading among ~2.01 m ones."""
    start = datetime(2026, 10, 26, 0, 2, tzinfo=UTC)
    readings = _readings(start, [2.014, 2.013, 2.748, 2.013, 2.020])

    assert abs(rate_of_change(readings)) < 0.02


def test_reading_jitter_does_not_flip_the_rate() -> None:
    """Monnow Gate, 26 Oct 2026, 06:02-07:02: levelling off, last reading 3 mm lower."""
    start = datetime(2026, 10, 26, 6, 2, tzinfo=UTC)
    readings = _readings(start, [2.210, 2.215, 2.216, 2.219, 2.216])

    rate = rate_of_change(readings)
    assert 0 < rate < 0.02


@pytest.mark.parametrize(
    ("rate", "trend"),
    [
        (0.05, "rising"),
        (0.021, "rising"),
        (0.02, "steady"),
        (0.0, "steady"),
        (-0.02, "steady"),
        (-0.021, "falling"),
        (-0.3, "falling"),
        (None, None),
    ],
)
def test_trend_from_rate(rate, trend) -> None:
    assert trend_from_rate(rate) == trend


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


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_parse_forecast_keeps_one_map_per_day() -> None:
    forecast = parse_forecast(load_fixture("forecast_summary.json"))

    assert len(forecast.maps) == len(forecast.days) == 5
    assert all(m.startswith(PNG_SIGNATURE) for m in forecast.maps)
    # Day three's map differs in the fixture.
    assert forecast.maps[2] != forecast.maps[0]
    assert forecast.maps[1] == forecast.maps[0]


def test_parse_forecast_map_edge_cases() -> None:
    payload = load_fixture("forecast_summary.json")
    good = payload["DayOneImage"]
    payload["DayOneImage"] = f"data:image/png;base64,{good}"
    payload["DayTwoImage"] = ""
    payload["DayThreeImage"] = "not base64 at all!"
    payload["DayFourImage"] = "aGVsbG8="  # valid base64, but not a PNG

    maps = parse_forecast(payload).maps

    assert maps[0].startswith(PNG_SIGNATURE)
    assert maps[1] is None
    assert maps[2] is None
    assert maps[3] is None
    assert maps[4].startswith(PNG_SIGNATURE)


def test_forecast_maps_stay_out_of_its_repr() -> None:
    forecast = parse_forecast(load_fixture("forecast_summary.json"))
    assert "PNG" not in repr(forecast)


def test_parse_areas_at_risk() -> None:
    assert parse_areas_at_risk(load_fixture("areas_at_risk_empty.json")) == []
    assert parse_areas_at_risk([{"a": 1}]) == [{"a": 1}]
    assert parse_areas_at_risk({"unexpected": True}) == []
