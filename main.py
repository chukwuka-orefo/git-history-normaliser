#!/usr/bin/env python3
"""git-history-synth CLI.

Currently supports dry run only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from synth.config import ConfigError, load_config
from synth.dryrun import build_entries, render_dryrun_report
from synth.engine import EngineError, compute_timestamps
from synth.repo import GitRepositoryError, load_commit_history
from synth.scope import ScopeError, apply_scope
from synth.validation import ValidationError, validate_config


def _default_schema_path() -> str:
    """
    Resolve schema.json relative to this script so the CLI works from any CWD.
    """
    return str((Path(__file__).resolve().parent / "schema.json"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-history-synth",
        description="Rewrite only Git timestamps under a YAML policy",
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="Path to the target git repository",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to rewrite policy YAML",
    )
    parser.add_argument(
        "--schema",
        default=_default_schema_path(),
        help="Path to schema.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print a report without touching the repo",
    )
    parser.add_argument(
        "--hash-len",
        type=int,
        default=12,
        help="Number of characters to show for commit hash",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if int(args.hash_len) <= 0:
        print("error: --hash-len must be a positive integer", file=sys.stderr)
        return 2

    repo_path = Path(args.repo).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    schema_path = Path(args.schema).expanduser().resolve()

    try:
        cfg = load_config(config_path, schema_path)
        validated = validate_config(cfg)

        commits = load_commit_history(repo_path)
        selected_commits, _untouched = apply_scope(commits, cfg.scope.fraction)

        if not args.dry_run:
            print(
                "error: rewrite mode is not implemented yet. Use --dry-run.",
                file=sys.stderr,
            )
            return 2

        final = compute_timestamps(selected_commits, validated) if selected_commits else {}
        entries = build_entries(selected_commits, final, hash_len=int(args.hash_len))

        report = render_dryrun_report(
            total_commits=len(commits),
            scope_fraction=cfg.scope.fraction,
            mode=cfg.timestamp.mode,
            selected_commits=selected_commits,
            entries=entries,
            hash_len=int(args.hash_len),
        )

        print(report)
        return 0

    except (ConfigError, ValidationError, GitRepositoryError, ScopeError, EngineError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
