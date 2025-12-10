# synth/config.py
"""
Configuration loading and validation.

Responsibilities:
- Load YAML configuration
- Validate against JSON Schema
- Expose a normalised config object

This module does NOT:
- interact with git
- compute timestamps
- perform rewrites
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import math

import json
import yaml
from jsonschema import Draft202012Validator


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimestampConfig:
    mode: str  # author | commit | synthetic


@dataclass(frozen=True)
class ScopeConfig:
    fraction: float


@dataclass(frozen=True)
class Config:
    timestamp: TimestampConfig
    scope: ScopeConfig
    calendar: Dict[str, Any] | None
    work_patterns: Dict[str, Any] | None
    randomness: Dict[str, Any] | None


def _load_schema(schema_path: Path) -> Dict[str, Any]:
    """
    Load JSON Schema from a schema.json file.
    """
    try:
        raw = schema_path.read_text(encoding="utf-8")
    except Exception as e:
        raise ConfigError(f"Failed to read schema file: {schema_path}") from e

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Schema is not valid JSON: {schema_path}") from e

    if not isinstance(parsed, dict):
        raise ConfigError(f"Schema must be a JSON object: {schema_path}")

    return parsed


def _load_yaml(config_path: Path) -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ConfigError(f"Failed to load config: {config_path}") from e

    if raw is None:
        raise ConfigError(f"Config is empty: {config_path}")

    if not isinstance(raw, dict):
        raise ConfigError(f"Config must be a mapping at top level: {config_path}")

    return raw


def load_config(config_path: Path, schema_path: Path) -> Config:
    """
    Load and validate configuration.

    Raises ConfigError on validation failure.
    """
    raw_config = _load_yaml(config_path)
    schema = _load_schema(schema_path)

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw_config), key=lambda e: list(e.path))

    if errors:
        messages = []
        for err in errors:
            path = ".".join(str(p) for p in err.path)
            prefix = path if path else "<root>"
            messages.append(f"{prefix}: {err.message}")
        raise ConfigError("Invalid configuration:\n" + "\n".join(messages))

    timestamp_cfg = TimestampConfig(
        mode=str(raw_config["timestamp"]["mode"])
    )

    fraction = float(raw_config["scope"]["fraction"])
    if not math.isfinite(fraction):
        raise ConfigError("scope.fraction must be a finite number")

    scope_cfg = ScopeConfig(
        fraction=fraction
    )

    return Config(
        timestamp=timestamp_cfg,
        scope=scope_cfg,
        calendar=raw_config.get("calendar"),
        work_patterns=raw_config.get("work_patterns"),
        randomness=raw_config.get("randomness"),
    )
