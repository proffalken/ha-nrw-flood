"""Models for NRW API payloads, and the pure functions that parse them."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import LEVEL_NONE, LEVELS, SEVERITY_TO_LEVEL, STATION_URL

_UK = ZoneInfo("Europe/London")
_RIVER_LEVEL = "River Level"
_RATE_WINDOW = timedelta(hours=1)


def parse_nrw_time(value: Any) -> datetime | None:
    """Parse an NRW timestamp into an aware UTC datetime.

    The warnings feed gives naive UK local times, the river data gives UTC
    with a "Z", and the forecast uses US-style "10/22/2026 09:30:00 AM".
    """
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UK)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


@dataclass(frozen=True, slots=True)
class FloodWarning:
    """One entry from the live flood warnings and alerts feed."""

    code: str
    description: str | None
    area: str | None
    severity_value: int | None
    message: str | None
    raised: datetime | None
    severity_changed: datetime | None
    message_changed: datetime | None
    tidal: bool | None

    @property
    def level(self) -> str | None:
        """alert / warning / severe, or None once no longer in force."""
        return SEVERITY_TO_LEVEL.get(self.severity_value)

    @property
    def in_force(self) -> bool:
        return self.level is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "area": self.area,
            "level": self.level,
            "message": self.message,
            "raised": _iso(self.raised),
            "severity_changed": _iso(self.severity_changed),
            "message_changed": _iso(self.message_changed),
            "tidal": self.tidal,
        }


def parse_warnings(payload: Any) -> list[FloodWarning]:
    """Parse the warnings GeoJSON FeatureCollection."""
    features = payload.get("features") if isinstance(payload, dict) else None
    warnings: list[FloodWarning] = []
    for feature in features or []:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict) or not _text(props.get("FWACODE")):
            continue
        try:
            severity = int(props.get("SEVERITYVALUE"))
        except TypeError, ValueError:
            severity = None
        warnings.append(
            FloodWarning(
                code=props["FWACODE"].strip(),
                description=_text(props.get("DESCRIPTION")),
                area=_text(props.get("AREA")),
                severity_value=severity,
                message=_text(props.get("RIM_ENGLISH")),
                raised=parse_nrw_time(props.get("TIMERAISED")),
                severity_changed=parse_nrw_time(props.get("SEVERITY_CHANGED")),
                message_changed=parse_nrw_time(props.get("RIM_CHANGED")),
                tidal=_bool(props.get("TIDAL")),
            )
        )
    return warnings


def highest_level(warnings: list[FloodWarning]) -> str:
    """The most severe level among warnings in force, or "none"."""
    levels = [w.level for w in warnings if w.level]
    if not levels:
        return LEVEL_NONE
    return max(levels, key=LEVELS.index)


@dataclass(frozen=True, slots=True)
class Station:
    """The latest river level reading at one monitoring station."""

    station_id: int
    title: str
    name: str | None
    status: str | None
    parameter: int
    units: str | None
    latest_value: float | None
    latest_time: datetime | None
    trend_raw: str | None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def url(self) -> str:
        return STATION_URL.format(self.station_id)

    @property
    def trend(self) -> str | None:
        return trend_from_status(self.trend_raw)


def parse_stations(payload: Any) -> list[Station]:
    """Parse the latest station data, keeping river level parameters only."""
    stations: list[Station] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or item.get("location") is None:
            continue
        for param in item.get("parameters") or []:
            if param.get("paramNameEN") != _RIVER_LEVEL:
                continue
            value = param.get("latestValue")
            stations.append(
                Station(
                    station_id=int(item["location"]),
                    title=_text(item.get("titleEn"))
                    or _text(item.get("nameEN"))
                    or str(item["location"]),
                    name=_text(item.get("nameEN")),
                    status=_text(item.get("statusEN")),
                    parameter=int(param["parameter"]),
                    units=_text(param.get("units")),
                    latest_value=float(value) if value is not None else None,
                    latest_time=parse_nrw_time(param.get("latestTime")),
                    trend_raw=_text(param.get("parameterStatusEN")),
                    latitude=item.get("latitude"),
                    longitude=item.get("longitude"),
                )
            )
    return stations


def trend_from_status(status: str | None) -> str | None:
    """Map NRW's "Level Rising" style status to rising / falling / steady."""
    if not status:
        return None
    lowered = status.lower()
    for trend in ("rising", "falling", "steady"):
        if trend in lowered:
            return trend
    return None


@dataclass(frozen=True, slots=True)
class Reading:
    """One timestamped river level reading."""

    time: datetime
    value: float


def parse_history(payload: Any) -> list[Reading]:
    """Parse a station's historical readings, oldest first."""
    raw = payload.get("parameterReadings") if isinstance(payload, dict) else None
    readings = []
    for item in raw or []:
        time = parse_nrw_time(item.get("time"))
        value = item.get("value")
        if time is not None and value is not None:
            readings.append(Reading(time=time, value=float(value)))
    return sorted(readings, key=lambda r: r.time)


def rate_of_change(readings: list[Reading]) -> float | None:
    """Metres per hour over roughly the last hour of readings.

    Compares the latest reading with the newest one at least an hour older.
    Returns None until there's an hour of data.
    """
    if not readings:
        return None
    latest = readings[-1]
    target = latest.time - _RATE_WINDOW
    earlier = [r for r in readings if r.time <= target]
    if not earlier:
        return None
    base = earlier[-1]
    hours = (latest.time - base.time).total_seconds() / 3600
    return round((latest.value - base.value) / hours, 3)


@dataclass(frozen=True, slots=True)
class FloodArea:
    """An NRW flood warning area or flood alert area."""

    code: str
    name: str
    kind: str  # "warning" or "alert"
    river: str | None


def parse_flood_areas(payload: Any, kind: str) -> list[FloodArea]:
    """Parse a DataMapWales WFS response for one flood area layer."""
    features = payload.get("features") if isinstance(payload, dict) else None
    areas = []
    for feature in features or []:
        props = feature.get("properties") or {}
        code = _text(props.get("fwd_tacode"))
        if not code:
            continue
        areas.append(
            FloodArea(
                code=code,
                name=_text(props.get("fwa_name"))
                or _text(props.get("descrip"))
                or code,
                kind=kind,
                river=_text(props.get("river_sea")),
            )
        )
    return areas


@dataclass(frozen=True, slots=True)
class Forecast:
    """The Wales-wide 5-day flood risk forecast summary."""

    issued: datetime | None
    summary: str | None
    days: list[str]
    # One PNG map per entry in days (None where NRW sent no usable image).
    # Each is a few hundred kilobytes, so they're kept out of the repr.
    maps: list[bytes | None] = field(default_factory=list, repr=False)


_DAY_KEYS = ("One", "Two", "Three", "Four", "Five")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _decode_png(value: Any) -> bytes | None:
    """Decode a base64 PNG, with or without a data: URI prefix."""
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith("data:"):
        value = value.partition(",")[2]
    try:
        image = base64.b64decode(value, validate=True)
    except binascii.Error, ValueError:
        return None
    return image if image.startswith(_PNG_SIGNATURE) else None


def parse_forecast(payload: Any) -> Forecast:
    """Parse the forecast summary and its daily risk maps."""
    data = payload if isinstance(payload, dict) else {}
    days: list[str] = []
    maps: list[bytes | None] = []
    for n in _DAY_KEYS:
        day = _text(data.get(f"Day{n}String_en"))
        if day:
            days.append(day)
            maps.append(_decode_png(data.get(f"Day{n}Image")))
    return Forecast(
        issued=parse_nrw_time(data.get("IssueDate")),
        summary=_text(data.get("Summary_en")),
        days=days,
        maps=maps,
    )


def parse_areas_at_risk(payload: Any) -> list[Any]:
    """Return the areas-at-risk list as given.

    Its item format isn't documented and it was empty when this was written,
    so it's passed through untouched rather than guessed at.
    """
    return payload if isinstance(payload, list) else []
