from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import os
import re
import sys
import tempfile
import subprocess

from user_ui.yaml_emit import build_yaml


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    returncode: int
    cmd: Sequence[str]
    stdout: str
    stderr: str


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


_GIT_BASH_PATH_RE = re.compile(r"^/([a-zA-Z])/(.+)$")


_DEFAULT_DRY_RUN_TIMEOUT_SECONDS = 60
_DEFAULT_REWRITE_TIMEOUT_SECONDS = 600


def preview_yaml(cleaned_data: Mapping[str, Any]) -> str:
    """
    Render the exact YAML that will be executed, without writing any files.
    """
    return build_yaml(cleaned_data)


def browse_repo_directory(initial_dir: str | None = None) -> str | None:
    """
    Open a native folder picker and return the selected directory path.

    This works only when the Django server is running locally on the user's machine.
    Browsers cannot provide a real local filesystem path for security reasons.

    Returns None if the user cancels.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        raise ServiceError("Folder picker is unavailable on this environment") from e

    initial = None
    if initial_dir:
        initial = _normalise_repo_path(str(initial_dir))

    root = tk.Tk()
    root.withdraw()

    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.askdirectory(
        initialdir=initial or os.getcwd(),
        mustexist=True,
        title="Select a Git repository folder",
    )

    try:
        root.destroy()
    except Exception:
        pass

    if not selected:
        return None

    p = str(Path(selected).expanduser().resolve())
    if os.name == "nt":
        p = p.replace("\\", "/")

    return p


def run_dry_run(
    cleaned_data: Mapping[str, Any],
    *,
    hash_len: int | None = None,
    timeout_seconds: int | None = _DEFAULT_DRY_RUN_TIMEOUT_SECONDS,
) -> CommandResult:
    """
    Execute a dry run and return captured stdout and stderr.

    Writes policy YAML to a temp file and removes it immediately after the process ends.
    """
    repo_path = _normalise_repo_path(str(cleaned_data["repo_path"]))
    yaml_text = build_yaml(cleaned_data)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        policy_path = td_path / "rewrite.yaml"
        policy_path.write_text(yaml_text, encoding="utf-8", newline="\n")

        cmd = [
            sys.executable,
            str(_PROJECT_ROOT / "main.py"),
            "--repo",
            repo_path,
            "--config",
            str(policy_path),
            "--dry-run",
        ]

        if hash_len is not None:
            if int(hash_len) <= 0:
                raise ServiceError("hash_len must be a positive integer")
            cmd.extend(["--hash-len", str(int(hash_len))])

        return _run(cmd, cwd=_PROJECT_ROOT, timeout_seconds=timeout_seconds)


def run_rewrite(
    cleaned_data: Mapping[str, Any],
    *,
    timeout_seconds: int | None = _DEFAULT_REWRITE_TIMEOUT_SECONDS,
) -> CommandResult:
    """
    Execute a destructive rewrite and return captured stdout and stderr.

    Safety:
    The caller must provide confirm_rewrite in cleaned_data.
    """
    if not bool(cleaned_data.get("confirm_rewrite")):
        raise ServiceError("Rewrite requires confirm_rewrite to be checked")

    repo_path = _normalise_repo_path(str(cleaned_data["repo_path"]))
    allow_dirty = bool(cleaned_data.get("allow_dirty"))
    yaml_text = build_yaml(cleaned_data)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        policy_path = td_path / "rewrite.yaml"
        policy_path.write_text(yaml_text, encoding="utf-8", newline="\n")

        cmd = [
            sys.executable,
            "-m",
            "synth.rewrite",
            "--repo",
            repo_path,
            "--config",
            str(policy_path),
            "--force",
        ]

        if allow_dirty:
            cmd.append("--allow-dirty")

        return _run(cmd, cwd=_PROJECT_ROOT, timeout_seconds=timeout_seconds)


def _run(cmd: Sequence[str], *, cwd: Path, timeout_seconds: int | None) -> CommandResult:
    """
    Run a subprocess and capture stdout and stderr.
    """
    try:
        completed = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        stdout = ""
        stderr = ""
        if getattr(e, "stdout", None):
            stdout = e.stdout if isinstance(e.stdout, str) else ""
        if getattr(e, "stderr", None):
            stderr = e.stderr if isinstance(e.stderr, str) else ""

        return CommandResult(
            ok=False,
            returncode=124,
            cmd=list(cmd),
            stdout=stdout,
            stderr=(stderr or "") + "\nprocess timed out",
        )
    except FileNotFoundError as e:
        raise ServiceError(f"Command not found: {cmd[0]}") from e
    except Exception as e:
        raise ServiceError(f"Failed to run command: {cmd[0]}") from e

    return CommandResult(
        ok=completed.returncode == 0,
        returncode=int(completed.returncode),
        cmd=list(cmd),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _normalise_repo_path(path_str: str) -> str:
    """
    Normalise Git Bash style paths to Windows drive paths when running on Windows.

    Example:
      /c/Users/name/repo -> C:/Users/name/repo
    """
    p = path_str.strip()

    if os.name != "nt":
        return p

    m = _GIT_BASH_PATH_RE.match(p)
    if not m:
        return p

    drive = m.group(1).upper()
    rest = m.group(2)
    return f"{drive}:/{rest}"
