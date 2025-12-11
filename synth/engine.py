# synth/engine.py
"""
Timestamp computation engine.

Responsibilities:
- Compute final timestamps for selected commits
- Support author, commit, and synthetic modes
- Enforce unified author/committer timestamps

This module does NOT:
- call git
- rewrite history
- load configuration files
"""

from __future__ import annotations

from datetime import datetime, timedelta, time, date, tzinfo
from typing import Dict, List, Tuple
import random

from synth.repo import Commit
from synth.validation import ValidatedConfig, ParsedWorkPatterns, ParsedWorkBlock, ParsedWorkHours


class EngineError(RuntimeError):
    pass


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def compute_timestamps(
    commits: List[Commit],
    config: ValidatedConfig,
) -> Dict[str, datetime]:
    """
    Compute final timestamps for commits.

    Args:
        commits: selected commits (oldest -> newest)
        config: validated and parsed configuration

    Returns:
        dict: commit_hash -> datetime
    """
    mode = config.timestamp.mode

    if mode == "author":
        return _author_mode(commits)

    if mode == "commit":
        return _commit_mode(commits)

    if mode == "synthetic":
        return _synthetic_mode(commits, config)

    raise EngineError(f"Unsupported timestamp mode: {mode}")


# ---------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------

def _author_mode(commits: List[Commit]) -> Dict[str, datetime]:
    """
    Restore committer dates from author dates.
    """
    return {c.hash: c.author_date for c in commits}


def _commit_mode(commits: List[Commit]) -> Dict[str, datetime]:
    """
    Restore author dates from committer dates.
    """
    return {c.hash: c.committer_date for c in commits}


def _synthetic_mode(
    commits: List[Commit],
    config: ValidatedConfig,
) -> Dict[str, datetime]:
    """
    Generate a synthetic timeline.

    Validation guarantees:
    - calendar exists and start <= end
    - work_patterns exist and at least one day group is enabled
    - randomness ranges are sane
    """
    if not commits:
        return {}

    if config.calendar is None or config.work_patterns is None or config.randomness is None:
        raise EngineError("Synthetic mode requires validated calendar, work_patterns, and randomness")

    calendar = config.calendar
    work = config.work_patterns
    randomness = config.randomness

    start_day = calendar.start
    end_day = calendar.end
    tz = calendar.tz

    rng = random.Random(randomness.seed)

    gap_min = int(randomness.gap_minutes_min)
    gap_max = int(randomness.gap_minutes_max)

    sec_min = int(randomness.seconds_min)
    sec_max = int(randomness.seconds_max)

    day0 = _next_enabled_day(start_day, end_day, work)
    current = _random_datetime_for_day(day0, work, rng, sec_min, sec_max, tz)

    results: Dict[str, datetime] = {commits[0].hash: current}

    for commit in commits[1:]:
        candidate = current + _random_gap(rng, gap_min, gap_max, sec_min, sec_max)
        current = _next_valid_datetime(candidate, end_day, work, rng, sec_min, sec_max, tz)
        results[commit.hash] = current

    return results


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _random_gap(
    rng: random.Random,
    gap_min: int,
    gap_max: int,
    sec_min: int,
    sec_max: int,
) -> timedelta:
    return timedelta(
        minutes=rng.randint(gap_min, gap_max),
        seconds=rng.randint(sec_min, sec_max),
    )


def _next_enabled_day(
    start_day: date,
    end_day: date,
    work: ParsedWorkPatterns,
) -> date:
    day = start_day
    while day <= end_day:
        block = _work_block_for_day(day, work)
        if block.enabled:
            return day
        day = day + timedelta(days=1)

    raise EngineError("Synthetic calendar window exhausted")


def _next_valid_datetime(
    candidate: datetime,
    end_day: date,
    work: ParsedWorkPatterns,
    rng: random.Random,
    sec_min: int,
    sec_max: int,
    tz: tzinfo,
) -> datetime:
    """
    Move candidate forward until it lands inside an enabled day and inside that day's work window.

    This function never returns a datetime earlier than candidate.
    """
    day = candidate.date()

    while day <= end_day:
        block = _work_block_for_day(day, work)

        if not block.enabled or block.hours is None:
            day = day + timedelta(days=1)
            candidate = datetime.combine(day, time(0, 0), tzinfo=tz)
            continue

        window_start, window_end = _window_bounds(day, block.hours, tz)

        if candidate < window_start:
            return _random_datetime_for_day(day, work, rng, sec_min, sec_max, tz)

        if window_start <= candidate <= window_end:
            return candidate

        day = day + timedelta(days=1)
        candidate = datetime.combine(day, time(0, 0), tzinfo=tz)

    raise EngineError("Synthetic calendar window exhausted")


def _random_datetime_for_day(
    day: date,
    work: ParsedWorkPatterns,
    rng: random.Random,
    sec_min: int,
    sec_max: int,
    tz: tzinfo,
) -> datetime:
    block = _work_block_for_day(day, work)
    if not block.enabled or block.hours is None:
        raise EngineError("Internal error: requested random time for a disabled day")

    t = _pick_time_in_window(rng, (block.hours.start, block.hours.end), sec_min, sec_max)
    return datetime.combine(day, t, tzinfo=tz)


def _work_block_for_day(day: date, work: ParsedWorkPatterns) -> ParsedWorkBlock:
    weekday = day.weekday()  # Mon=0 ... Sun=6

    if weekday <= 4:
        return work.weekdays

    if weekday == 5:
        return work.saturday

    return work.sunday


def _window_bounds(day: date, hours: ParsedWorkHours, tz: tzinfo) -> Tuple[datetime, datetime]:
    """
    Work hours are minute based (HH:MM). Treat end as inclusive through the full minute.
    """
    start_dt = datetime.combine(day, time(hours.start.hour, hours.start.minute, 0), tzinfo=tz)
    end_dt = datetime.combine(day, time(hours.end.hour, hours.end.minute, 59), tzinfo=tz)
    return start_dt, end_dt


def _pick_time_in_window(
    rng: random.Random,
    window: Tuple[time, time],
    sec_min: int,
    sec_max: int,
) -> time:
    start, end = window

    # Minute based window, end is inclusive through the full minute.
    start_s = start.hour * 3600 + start.minute * 60
    end_s = end.hour * 3600 + end.minute * 60 + 59

    if end_s < start_s:
        raise EngineError("Invalid work window: end before start")

    chosen_s = rng.randint(start_s, end_s)
    chosen_s = chosen_s - (chosen_s % 60)  # align to minute boundary
    chosen_s = max(start_s, min(chosen_s, end_s))

    chosen_minute = (chosen_s % 3600) // 60
    chosen_hour = chosen_s // 3600

    chosen_second = rng.randint(sec_min, sec_max)
    return time(int(chosen_hour), int(chosen_minute), int(chosen_second))
