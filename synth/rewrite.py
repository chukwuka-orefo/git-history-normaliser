# synth/rewrite.py
"""
History rewrite implementation.

Responsibilities:
- Load config and schema
- Run semantic validation
- Read commits and apply scope
- Compute final timestamps
- Rewrite only author and committer dates using git-filter-repo

This module does NOT:
- change commit messages
- change file contents
- change commit ordering or topology
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subprocess import CalledProcessError, run, PIPE
from typing import Dict, List, Mapping, Optional

from synth.config import ConfigError, load_config
from synth.engine import EngineError, compute_timestamps
from synth.repo import GitRepositoryError, load_commit_history
from synth.scope import ScopeError, apply_scope
from synth.validation import ValidationError, validate_config
from synth.dryrun import build_entries, render_dryrun_report


class RewriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class RewritePlan:
    repo_path: Path
    selected_count: int
    total_commits: int
    mode: str
    scope_fraction: float
    date_map: Mapping[str, str]  # original commit hash (lower) -> "unix_seconds +/-HHMM"


def _default_schema_path() -> str:
    """
    Resolve schema.json relative to the project root.
    This file lives in synth/, so parent of parent is the root.
    """
    return str((Path(__file__).resolve().parents[1] / "schema.json"))


def _run_git(repo_path: Path, args: List[str]) -> str:
    try:
        result = run(
            ["git", "-C", str(repo_path)] + args,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return result.stdout
    except CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise RewriteError(stderr if stderr else "git command failed") from e


def _ensure_clean_worktree(repo_path: Path) -> None:
    out = _run_git(repo_path, ["status", "--porcelain"])
    if out.strip():
        raise RewriteError("Working tree is not clean. Commit or stash changes, or pass --allow-dirty to override.")


def _ensure_filter_repo_available(repo_path: Path) -> None:
    try:
        run(
            [sys.executable, "-m", "git_filter_repo", "--help"],
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise RewriteError(
            "git-filter-repo is not available. Install it in the active environment, then try again."
        ) from e


def _format_git_date(dt: datetime) -> str:
    """
    Convert a timezone-aware datetime to git-filter-repo's expected date bytes format:
    "<unix_seconds> <+HHMM or -HHMM>"

    Validation and engine should provide timezone-aware datetimes. If tzinfo is missing,
    treat the value as UTC to avoid undefined behaviour.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    offset = dt.utcoffset()
    if offset is None:
        offset = timedelta(0)

    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)

    hh = total_minutes // 60
    mm = total_minutes % 60

    ts = int(dt.timestamp())
    return f"{ts} {sign}{hh:02d}{mm:02d}"


def _build_rewrite_plan(
    repo_path: Path,
    config_path: Path,
    schema_path: Path,
) -> RewritePlan:
    cfg = load_config(config_path, schema_path)
    validated = validate_config(cfg)

    commits = load_commit_history(repo_path)
    selected, _untouched = apply_scope(commits, cfg.scope.fraction)

    final = compute_timestamps(selected, validated) if selected else {}

    date_map: Dict[str, str] = {}
    for c in selected:
        if c.hash not in final:
            raise RewriteError(f"Missing computed timestamp for commit: {c.hash}")
        date_map[c.hash.lower()] = _format_git_date(final[c.hash])

    return RewritePlan(
        repo_path=repo_path,
        selected_count=len(selected),
        total_commits=len(commits),
        mode=cfg.timestamp.mode,
        scope_fraction=cfg.scope.fraction,
        date_map=date_map,
    )


def _commit_callback_body(mapping_path: Path) -> str:
    """
    Build a git-filter-repo commit-callback body.

    Note: git-filter-repo uses bytestrings for commit fields.
    - commit.original_id is a bytestring of the original hash
    - commit.author_date and commit.committer_date are bytestrings like b"unix +0000"
    """
    map_path = mapping_path.as_posix()

    return f"""
if 'DATE_MAP' not in globals():
    import json
    with open({map_path!r}, 'r', encoding='utf-8') as _f:
        DATE_MAP = json.load(_f)

_oid = commit.original_id
if isinstance(_oid, bytes):
    _oid = _oid.decode('ascii', 'ignore')
_oid = _oid.lower()

_new = DATE_MAP.get(_oid)
if _new is not None:
    _b = _new.encode('ascii')
    commit.author_date = _b
    commit.committer_date = _b
""".strip()


def rewrite_history(
    *,
    repo_path: Path,
    config_path: Path,
    schema_path: Path,
    force: bool,
    allow_dirty: bool,
) -> None:
    """
    Perform the history rewrite in-place on the target repository.

    This operation is destructive. Use --force only when you accept the consequences.
    """
    repo_path = repo_path.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    schema_path = schema_path.expanduser().resolve()

    plan = _build_rewrite_plan(repo_path, config_path, schema_path)

    if plan.selected_count == 0:
        print("No commits selected by scope. Nothing to rewrite.")
        return

    if not allow_dirty:
        _ensure_clean_worktree(repo_path)

    _ensure_filter_repo_available(repo_path)

    if not force:
        raise RewriteError("Refusing to rewrite without --force.")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        mapping_path = td_path / "timestamp_map.json"
        mapping_path.write_text(json.dumps(plan.date_map, indent=2), encoding="utf-8")

        callback_body = _commit_callback_body(mapping_path)

        cmd = [
            sys.executable,
            "-m",
            "git_filter_repo",
            "--force",
            "--preserve-commit-hashes",
            "--preserve-commit-encoding",
            "--commit-callback",
            callback_body,
        ]

        try:
            run(
                cmd,
                cwd=str(repo_path),
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except CalledProcessError as e:
            raise RewriteError(f"git-filter-repo failed with exit code {e.returncode}") from e

    print(f"Rewrite complete. Rewrote {plan.selected_count} commits out of {plan.total_commits}.")

    # Print the final state table, using the same renderer as dry-run.
    # This is an audit-friendly confirmation of what the repository now looks like.
    try:
        cfg = load_config(config_path, schema_path)
        validated = validate_config(cfg)

        new_commits = load_commit_history(repo_path)
        selected_new, _untouched_new = apply_scope(new_commits, cfg.scope.fraction)

        final_new = compute_timestamps(selected_new, validated) if selected_new else {}
        entries = build_entries(selected_new, final_new, hash_len=12)

        report = render_dryrun_report(
            total_commits=len(new_commits),
            scope_fraction=cfg.scope.fraction,
            mode=cfg.timestamp.mode,
            selected_commits=selected_new,
            entries=entries,
            hash_len=12,
        )

        print()
        print("Final rewritten state")
        print()
        print(report)
    except Exception as e:
        print(f"warning: failed to render final report: {e}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-history-synth-rewrite",
        description="Rewrite only Git timestamps under a YAML policy (destructive)",
    )

    parser.add_argument("--repo", required=True, help="Path to the target git repository")
    parser.add_argument("--config", required=True, help="Path to rewrite policy YAML")
    parser.add_argument("--schema", default=_default_schema_path(), help="Path to schema.json")

    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed with rewriting even if the repository is not a fresh clone",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Proceed even if the working tree has uncommitted changes",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        rewrite_history(
            repo_path=Path(args.repo),
            config_path=Path(args.config),
            schema_path=Path(args.schema),
            force=bool(args.force),
            allow_dirty=bool(args.allow_dirty),
        )
        return 0

    except (ConfigError, ValidationError, GitRepositoryError, ScopeError, EngineError, RewriteError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
