# synth/scope.py
"""
Commit scope selection.

Selects a contiguous slice of commits based on a fractional scope.

Responsibilities:
- Interpret scope.fraction
- Select commit subset deterministically

This module does NOT:
- modify commits
- inspect timestamps
- interact with git
"""

from typing import List, Tuple
from math import floor

from synth.repo import Commit


class ScopeError(RuntimeError):
    pass


def apply_scope(
    commits: List[Commit],
    fraction: float,
) -> Tuple[List[Commit], List[Commit]]:
    """
    Apply scope fraction to commit list.

    Args:
        commits: full commit list (oldest -> newest)
        fraction: value in [-1.0, 1.0]

    Returns:
        (selected_commits, untouched_commits)
    """
    if not -1.0 <= fraction <= 1.0:
        raise ScopeError(f"Invalid scope fraction: {fraction}")

    total = len(commits)

    if total == 0 or fraction == 0.0:
        return [], commits[:]

    k = floor(abs(fraction) * total)

    if k == 0:
        return [], commits[:]

    if fraction > 0:
        selected = commits[:k]
        untouched = commits[k:]
    else:
        selected = commits[total - k :]
        untouched = commits[: total - k]

    return selected, untouched
