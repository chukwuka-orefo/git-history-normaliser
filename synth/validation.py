# synth/validation.py
"""
Semantic validation and parsing for configuration.

Responsibilities:
- Validate cross-field constraints the JSON Schema cannot express
- Parse config strings into typed values
- Produce actionable errors with field path context

This module does NOT:
- load YAML files
- load JSON Schema files
- interact with git
- compute timestamps
- rewrite history
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone, tzinfo
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from synth.config import Config, ScopeConfig, TimestampConfig


class ValidationError(RuntimeError):
    """
    Raised when configuration is structurally valid but semantically invalid.

    Attributes:
        path: dotted path of the failing field, for example calendar.start
    """

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


@dataclass(frozen=True)
class ParsedCalendar:
    start: date
    end: date
    timezone_name: str
    tz: tzinfo


@dataclass(frozen=True)
class ParsedWorkHours:
    start: time
    end: time


@dataclass(frozen=True)
class ParsedWorkBlock:
    enabled: bool
    hours: Optional[ParsedWorkHours]


@dataclass(frozen=True)
class ParsedWorkPatterns:
    weekdays: ParsedWorkBlock
    saturday: ParsedWorkBlock
    sunday: ParsedWorkBlock


@dataclass(frozen=True)
class ParsedRandomness:
    seed: Optional[int]
    gap_minutes_min: int
    gap_minutes_max: int
    seconds_min: int
    seconds_max: int


@dataclass(frozen=True)
class ValidatedConfig:
    timestamp: TimestampConfig
    scope: ScopeConfig
    calendar: Optional[ParsedCalendar]
    work_patterns: Optional[ParsedWorkPatterns]
    randomness: Optional[ParsedRandomness]


def validate_config(cfg: Config) -> ValidatedConfig:
    """
    Validate and parse configuration into a form the engine can trust.

    For author and commit modes:
    - Enforce absence of synthetic-only sections

    For synthetic mode:
    - Validate calendar ordering
    - Validate randomness ranges
    - Validate work pattern viability
    - Parse dates and times
    """
    mode = cfg.timestamp.mode

    if mode in ("author", "commit"):
        _forbid_synthetic_sections(cfg, mode)
        return ValidatedConfig(
            timestamp=cfg.timestamp,
            scope=cfg.scope,
            calendar=None,
            work_patterns=None,
            randomness=None,
        )

    if mode != "synthetic":
        raise ValidationError("timestamp.mode", f"unsupported mode: {mode}")

    if cfg.calendar is None:
        raise ValidationError("calendar", "missing calendar for synthetic mode")

    if cfg.work_patterns is None:
        raise ValidationError("work_patterns", "missing work_patterns for synthetic mode")

    if cfg.randomness is None:
        raise ValidationError("randomness", "missing randomness for synthetic mode")

    parsed_calendar = validate_calendar(cfg.calendar)
    parsed_work = validate_work_patterns(cfg.work_patterns)
    parsed_rand = validate_randomness(cfg.randomness)

    return ValidatedConfig(
        timestamp=cfg.timestamp,
        scope=cfg.scope,
        calendar=parsed_calendar,
        work_patterns=parsed_work,
        randomness=parsed_rand,
    )


def validate_calendar(calendar: Mapping[str, Any]) -> ParsedCalendar:
    """
    Validate and parse the calendar section.

    Enforces:
    - start and end parse as real dates
    - start is on or before end
    - timezone resolves, or defaults to UTC when omitted
    """
    start_raw = calendar.get("start")
    end_raw = calendar.get("end")

    if not isinstance(start_raw, str):
        raise ValidationError("calendar.start", "start must be a string")

    if not isinstance(end_raw, str):
        raise ValidationError("calendar.end", "end must be a string")

    start = _parse_date("calendar.start", start_raw)
    end = _parse_date("calendar.end", end_raw)

    if start > end:
        raise ValidationError("calendar", "start must be on or before end")

    tz_name_raw = calendar.get("timezone")
    if tz_name_raw is None:
        tz_name = "UTC"
    else:
        if not isinstance(tz_name_raw, str):
            raise ValidationError("calendar.timezone", "timezone must be a string")
        tz_name = tz_name_raw.strip()
        if not tz_name:
            raise ValidationError("calendar.timezone", "timezone must not be empty")

    tz = _resolve_timezone("calendar.timezone", tz_name)

    return ParsedCalendar(
        start=start,
        end=end,
        timezone_name=tz_name,
        tz=tz,
    )


def validate_work_patterns(work_patterns: Mapping[str, Any]) -> ParsedWorkPatterns:
    """
    Validate and parse work_patterns.

    Enforces:
    - weekdays, saturday, sunday exist
    - at least one of them is enabled
    - for enabled blocks, end is after start
    - for disabled blocks, hours must be absent
    """
    weekdays_raw = work_patterns.get("weekdays")
    saturday_raw = work_patterns.get("saturday")
    sunday_raw = work_patterns.get("sunday")

    if not isinstance(weekdays_raw, Mapping):
        raise ValidationError("work_patterns.weekdays", "weekdays must be an object")

    if not isinstance(saturday_raw, Mapping):
        raise ValidationError("work_patterns.saturday", "saturday must be an object")

    if not isinstance(sunday_raw, Mapping):
        raise ValidationError("work_patterns.sunday", "sunday must be an object")

    weekdays = _validate_work_block("work_patterns.weekdays", weekdays_raw)
    saturday = _validate_work_block("work_patterns.saturday", saturday_raw)
    sunday = _validate_work_block("work_patterns.sunday", sunday_raw)

    if not (weekdays.enabled or saturday.enabled or sunday.enabled):
        raise ValidationError("work_patterns", "enable at least one of weekdays, saturday, or sunday")

    return ParsedWorkPatterns(
        weekdays=weekdays,
        saturday=saturday,
        sunday=sunday,
    )


def validate_randomness(randomness: Mapping[str, Any]) -> ParsedRandomness:
    """
    Validate and parse randomness.

    Enforces:
    - min is not greater than max for both ranges
    - seconds ranges remain within 0 to 59
    - seed is int or null
    """
    seed_raw = randomness.get("seed")
    seed: Optional[int] = None
    if seed_raw is not None:
        if not _is_int(seed_raw):
            raise ValidationError("randomness.seed", "seed must be an integer or null")
        seed = int(seed_raw)

    gap_raw = randomness.get("gap_minutes")
    if not isinstance(gap_raw, Mapping):
        raise ValidationError("randomness.gap_minutes", "gap_minutes must be an object")

    sec_raw = randomness.get("seconds")
    if not isinstance(sec_raw, Mapping):
        raise ValidationError("randomness.seconds", "seconds must be an object")

    gap_min = _require_int(gap_raw, "min", "randomness.gap_minutes.min")
    gap_max = _require_int(gap_raw, "max", "randomness.gap_minutes.max")

    if gap_min < 0 or gap_max < 0:
        raise ValidationError("randomness.gap_minutes", "min and max must be non negative")

    if gap_min > gap_max:
        raise ValidationError("randomness.gap_minutes", "min must be less than or equal to max")

    sec_min = _require_int(sec_raw, "min", "randomness.seconds.min")
    sec_max = _require_int(sec_raw, "max", "randomness.seconds.max")

    if not (0 <= sec_min <= 59):
        raise ValidationError("randomness.seconds.min", "min must be between 0 and 59")

    if not (0 <= sec_max <= 59):
        raise ValidationError("randomness.seconds.max", "max must be between 0 and 59")

    if sec_min > sec_max:
        raise ValidationError("randomness.seconds", "min must be less than or equal to max")

    return ParsedRandomness(
        seed=seed,
        gap_minutes_min=gap_min,
        gap_minutes_max=gap_max,
        seconds_min=sec_min,
        seconds_max=sec_max,
    )


def _forbid_synthetic_sections(cfg: Config, mode: str) -> None:
    if cfg.calendar is not None:
        raise ValidationError("calendar", f"calendar is not allowed in {mode} mode")

    if cfg.work_patterns is not None:
        raise ValidationError("work_patterns", f"work_patterns is not allowed in {mode} mode")

    if cfg.randomness is not None:
        raise ValidationError("randomness", f"randomness is not allowed in {mode} mode")


def _validate_work_block(path: str, block: Mapping[str, Any]) -> ParsedWorkBlock:
    enabled_raw = block.get("enabled")

    if not isinstance(enabled_raw, bool):
        raise ValidationError(f"{path}.enabled", "enabled must be a boolean")

    enabled = bool(enabled_raw)

    hours_raw = block.get("hours")

    if not enabled:
        if hours_raw is not None:
            raise ValidationError(f"{path}.hours", "hours must be omitted when enabled is false")
        return ParsedWorkBlock(enabled=False, hours=None)

    if not isinstance(hours_raw, Mapping):
        raise ValidationError(f"{path}.hours", "hours must be an object when enabled is true")

    start_raw = hours_raw.get("start")
    end_raw = hours_raw.get("end")

    if not isinstance(start_raw, str):
        raise ValidationError(f"{path}.hours.start", "start must be a string")

    if not isinstance(end_raw, str):
        raise ValidationError(f"{path}.hours.end", "end must be a string")

    start_t = _parse_time(f"{path}.hours.start", start_raw)
    end_t = _parse_time(f"{path}.hours.end", end_raw)

    if end_t <= start_t:
        raise ValidationError(f"{path}.hours.end", "end must be after hours.start")

    return ParsedWorkBlock(
        enabled=True,
        hours=ParsedWorkHours(start=start_t, end=end_t),
    )


def _parse_date(path: str, value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise ValidationError(path, f"invalid date: {value}") from e


def _parse_time(path: str, value: str) -> time:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValidationError(path, "time must use HH:MM format")

    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError as e:
        raise ValidationError(path, f"invalid time: {value}") from e

    if not (0 <= h <= 23):
        raise ValidationError(path, f"hour out of range: {h}")

    if not (0 <= m <= 59):
        raise ValidationError(path, f"minute out of range: {m}")

    return time(hour=h, minute=m)


def _resolve_timezone(path: str, name: str) -> tzinfo:
    upper = name.upper()
    if upper in {"UTC", "Z", "ETC/UTC"}:
        return timezone.utc

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as e:
        raise ValidationError(
            path,
            f"invalid timezone: {name}. install tzdata or set timezone to UTC",
        ) from e
    except Exception as e:
        raise ValidationError(path, f"invalid timezone: {name}") from e


def _require_int(obj: Mapping[str, Any], key: str, path: str) -> int:
    raw = obj.get(key)
    if not _is_int(raw):
        raise ValidationError(path, "value must be an integer")
    return int(raw)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
