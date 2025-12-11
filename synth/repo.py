# synth/repo.py
"""
Repository introspection utilities.

Reads commit history from a target Git repository.
Handles Git Bash ↔ Windows path normalisation.

UI support:
- Exposes commit subject and author/committer identity fields
- Exposes ref decorations (branches/tags) as context
"""

from dataclasses import dataclass
from datetime import datetime
from subprocess import run, PIPE, CalledProcessError
from typing import List
from pathlib import Path
import os


# Single source of truth for git field separation
_FIELD_SEP = "\x00"


@dataclass(frozen=True)
class Commit:
    hash: str
    author_date: datetime
    committer_date: datetime
    index: int

    # UI fields
    subject: str = ""
    author_name: str = ""
    author_email: str = ""
    committer_name: str = ""
    committer_email: str = ""
    refs: str = ""


class GitRepositoryError(RuntimeError):
    pass


def _normalise_repo_path(repo_path: Path) -> Path:
    """
    Convert Git Bash paths (/c/Users/...) to native Windows paths (C:\\Users\\...).
    No-op on non-Windows systems.
    """
    if os.name != "nt":
        return repo_path

    p = str(repo_path)

    if p.startswith("/") and len(p) >= 3 and p[2] == "/":
        drive = p[1]
        if drive.isalpha():
            return Path(f"{drive.upper()}:/{p[3:]}")

    return Path(p)


def _run_git_command(repo_path: Path, args: List[str]) -> str:
    repo_path = _normalise_repo_path(repo_path)

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
        # Do not strip spaces — only remove trailing newlines
        return result.stdout.rstrip("\n")
    except CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise GitRepositoryError(stderr if stderr else "git command failed") from e


def ensure_git_repository(repo_path: Path) -> None:
    try:
        _run_git_command(repo_path, ["rev-parse", "--is-inside-work-tree"])
    except GitRepositoryError as e:
        raise GitRepositoryError(f"Not a git repository: {repo_path}") from e


def load_commit_history(repo_path: Path) -> List[Commit]:
    """
    Load commits in deterministic oldest → newest order.

    Fields per commit:
    - hash
    - author_date, committer_date
    - author/committer name + email
    - subject (first line of message)
    - refs (decorations from %D)
    """
    ensure_git_repository(repo_path)

    log_format = (
    "%H%x00"
    "%ad%x00"
    "%cd%x00"
    "%an%x00"
    "%ae%x00"
    "%cn%x00"
    "%ce%x00"
    "%s%x00"
    "%D"
    )

    raw_log = _run_git_command(
        repo_path,
        [
            "log",
            "--reverse",
            "--date=iso-strict",
            f"--pretty=format:{log_format}",
        ],
    )

    commits: List[Commit] = []

    if not raw_log:
        return commits

    for idx, line in enumerate(raw_log.splitlines()):
        parts = line.split(_FIELD_SEP)

        if len(parts) != 9:
            raise GitRepositoryError(f"Malformed git log line: {line!r}")

        (
            commit_hash,
            author_str,
            committer_str,
            author_name,
            author_email,
            committer_name,
            committer_email,
            subject,
            refs,
        ) = parts

        try:
            author_date = datetime.fromisoformat(author_str)
            committer_date = datetime.fromisoformat(committer_str)
        except ValueError as e:
            raise GitRepositoryError(
                f"Invalid timestamp format in git log: {line!r}"
            ) from e

        commits.append(
            Commit(
                hash=commit_hash,
                author_date=author_date,
                committer_date=committer_date,
                index=idx,
                subject=subject,
                author_name=author_name,
                author_email=author_email,
                committer_name=committer_name,
                committer_email=committer_email,
                refs=refs.strip(),
            )
        )

    return commits
