# synth/dryrun.py
"""
Dry run reporting.

Responsibilities:
- Build a report for a planned rewrite
- Render a deterministic, human readable output

This module does NOT:
- call git
- compute timestamps
- rewrite history
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Sequence

from synth.repo import Commit


@dataclass(frozen=True)
class DryRunEntry:
    index: int
    hash_prefix: str
    author_date: datetime
    committer_date: datetime
    final_timestamp: datetime
    changed: bool


def build_entries(
    commits: Sequence[Commit],
    final_timestamps: Mapping[str, datetime],
    *,
    hash_len: int = 12,
) -> List[DryRunEntry]:
    """
    Build per commit dry run entries.

    Raises:
        KeyError: if a commit hash is missing from final_timestamps, this indicates an upstream bug.
        ValueError: if hash_len is invalid.
    """
    if hash_len <= 0:
        raise ValueError("hash_len must be a positive integer")

    entries: List[DryRunEntry] = []

    for c in commits:
        final = final_timestamps[c.hash]
        changed = (c.author_date != final) or (c.committer_date != final)

        entries.append(
            DryRunEntry(
                index=c.index,
                hash_prefix=c.hash[:hash_len],
                author_date=c.author_date,
                committer_date=c.committer_date,
                final_timestamp=final,
                changed=changed,
            )
        )

    entries.sort(key=lambda e: e.index)
    return entries


def render_dryrun_report(
    *,
    total_commits: int,
    scope_fraction: float,
    mode: str,
    selected_commits: Sequence[Commit],
    entries: Sequence[DryRunEntry],
    hash_len: int,
) -> str:
    """
    Render a dry run report as plain text.
    """
    lines: List[str] = []

    lines.append(f"Total commits: {total_commits}")
    lines.append(f"Scope fraction: {scope_fraction}")
    lines.append(f"Selected commits: {len(selected_commits)}")

    if selected_commits:
        start = selected_commits[0].index
        end = selected_commits[-1].index
        lines.append(f"Index range: [{start} .. {end}]")
    else:
        lines.append("Index range: <none>")

    lines.append(f"Mode: {mode}")

    if not entries:
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Hash shown as {hash_len} character prefix")
    lines.append("")

    headers = [
        "idx",
        "hash",
        "author_date",
        "committer_date",
        "final_timestamp",
        "changed",
    ]

    rows: List[List[str]] = []
    for e in sorted(entries, key=lambda x: x.index):
        rows.append(
            [
                str(e.index),
                e.hash_prefix,
                _fmt_dt(e.author_date),
                _fmt_dt(e.committer_date),
                _fmt_dt(e.final_timestamp),
                "yes" if e.changed else "no",
            ]
        )

    lines.extend(_format_table(headers, rows))
    return "\n".join(lines)


def _fmt_dt(dt: datetime) -> str:
    return dt.isoformat()


def _format_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    widths = [len(h) for h in headers]

    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(items: List[str]) -> str:
        return "  ".join(items[i].ljust(widths[i]) for i in range(len(items)))

    lines: List[str] = []
    lines.append(fmt_row(headers))
    lines.append(fmt_row(["-" * w for w in widths]))

    for row in rows:
        lines.append(fmt_row(row))

    return lines
