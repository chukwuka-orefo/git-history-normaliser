# user_ui/yaml_emit.py
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, Mapping

import yaml


class QuotedString(str):
    """
    Marker type for forcing quoted YAML scalars.

    This is used to stop PyYAML from later reinterpreting unquoted ISO dates and HH:MM
    values as non-string types on load.
    """


def _quoted_str_representer(dumper: yaml.SafeDumper, data: QuotedString):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


yaml.add_representer(QuotedString, _quoted_str_representer, Dumper=yaml.SafeDumper)


_DEFAULT_GAP_MIN = 25
_DEFAULT_GAP_MAX = 90
_DEFAULT_SEC_MIN = 5
_DEFAULT_SEC_MAX = 55


def build_policy_dict(cleaned_data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Convert validated form.cleaned_data into a policy dict matching schema.json.

    Rules:
    1) author or commit mode emits only timestamp and scope
    2) synthetic mode emits timestamp, scope, calendar, work_patterns, randomness
    3) synthetic randomness always emits defaults unless overridden
    4) date and time strings are emitted as quoted strings to avoid YAML implicit typing
    """
    mode = str(cleaned_data["mode"])
    scope_fraction = float(cleaned_data["scope_fraction"])

    policy: Dict[str, Any] = {
        "timestamp": {"mode": mode},
        "scope": {"fraction": scope_fraction},
    }

    if mode in {"author", "commit"}:
        return policy

    if mode != "synthetic":
        raise ValueError(f"Unsupported mode: {mode}")

    start_date: date = cleaned_data["calendar_start"]
    end_date: date = cleaned_data["calendar_end"]

    policy["calendar"] = {
        "start": QuotedString(start_date.isoformat()),
        "end": QuotedString(end_date.isoformat()),
        "timezone": "UTC",
    }

    policy["work_patterns"] = {
        "weekdays": _build_work_block(cleaned_data, "weekdays"),
        "saturday": _build_work_block(cleaned_data, "saturday"),
        "sunday": _build_work_block(cleaned_data, "sunday"),
    }

    policy["randomness"] = _build_randomness(cleaned_data, start_date)

    return policy


def build_yaml(cleaned_data: Mapping[str, Any]) -> str:
    """
    Build YAML text from validated form.cleaned_data.
    """
    policy = build_policy_dict(cleaned_data)
    return yaml.safe_dump(
        policy,
        sort_keys=False,
        default_flow_style=False,
    )


def _build_work_block(cleaned_data: Mapping[str, Any], prefix: str) -> Dict[str, Any]:
    enabled = bool(cleaned_data.get(f"{prefix}_enabled"))

    if not enabled:
        return {"enabled": False}

    start_t: time = cleaned_data[f"{prefix}_start"]
    end_t: time = cleaned_data[f"{prefix}_end"]

    return {
        "enabled": True,
        "hours": {
            "start": QuotedString(_fmt_time(start_t)),
            "end": QuotedString(_fmt_time(end_t)),
        },
    }


def _build_randomness(cleaned_data: Mapping[str, Any], calendar_start: date) -> Dict[str, Any]:
    seed = cleaned_data.get("randomness_seed")
    if seed is None:
        seed = int(calendar_start.strftime("%Y%m%d"))

    gap_min = cleaned_data.get("gap_minutes_min")
    gap_max = cleaned_data.get("gap_minutes_max")
    gap_min_i, gap_max_i = _normalise_range(
        gap_min,
        gap_max,
        _DEFAULT_GAP_MIN,
        _DEFAULT_GAP_MAX,
        clamp_min=0,
        clamp_max=None,
    )

    sec_min = cleaned_data.get("seconds_min")
    sec_max = cleaned_data.get("seconds_max")
    sec_min_i, sec_max_i = _normalise_range(
        sec_min,
        sec_max,
        _DEFAULT_SEC_MIN,
        _DEFAULT_SEC_MAX,
        clamp_min=0,
        clamp_max=59,
    )

    return {
        "seed": int(seed),
        "gap_minutes": {"min": gap_min_i, "max": gap_max_i},
        "seconds": {"min": sec_min_i, "max": sec_max_i},
    }


def _normalise_range(
    maybe_min: Any,
    maybe_max: Any,
    default_min: int,
    default_max: int,
    *,
    clamp_min: int,
    clamp_max: int | None,
) -> tuple[int, int]:
    """
    Always produce a valid integer range.

    Behaviour:
    1) If both missing, use defaults
    2) If only min provided, set max to max(default_max, min)
    3) If only max provided, set min to min(default_min, max)
    4) Clamp to bounds if requested
    5) Ensure min <= max by collapsing to equality if needed
    """
    if maybe_min is None and maybe_max is None:
        rmin = default_min
        rmax = default_max
    elif maybe_min is None:
        rmax = int(maybe_max)
        rmin = min(default_min, rmax)
    elif maybe_max is None:
        rmin = int(maybe_min)
        rmax = max(default_max, rmin)
    else:
        rmin = int(maybe_min)
        rmax = int(maybe_max)

    if clamp_max is None:
        rmin = max(clamp_min, rmin)
        rmax = max(clamp_min, rmax)
    else:
        rmin = max(clamp_min, min(clamp_max, rmin))
        rmax = max(clamp_min, min(clamp_max, rmax))

    if rmin > rmax:
        rmax = rmin

    return rmin, rmax


def _fmt_time(t: time) -> str:
    return t.strftime("%H:%M")
