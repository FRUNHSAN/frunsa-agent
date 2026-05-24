"""YAML ↔ StepConfig bidirectional converter.

YAML files for persistence and human editing; StepConfig dataclasses for runtime.
The converter is pure data mapping — no business logic.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml

from .engine import PipelineConfig, RetryPolicy, StepConfig


_ENV_PATTERN = re.compile(r"\$\{(\w+)(?:\:-(.+))?\}")


def resolve_env(value: str) -> str:
    """Resolve ${ENV_VAR} and ${ENV_VAR:-default} in a string value."""
    if not isinstance(value, str):
        return value
    match = _ENV_PATTERN.fullmatch(value.strip())
    if not match:
        return value
    var_name, default = match.groups()
    env_val = os.getenv(var_name)
    if env_val is not None:
        return env_val
    if default is not None:
        return default
    raise ConfigurationError(
        f"Environment variable '{var_name}' is not set and no default provided."
    )


def _resolve_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively resolve ${ENV} in param values (strings only)."""
    resolved: Dict[str, Any] = {}
    for k, v in params.items():
        if isinstance(v, str):
            resolved[k] = resolve_env(v)
        elif isinstance(v, dict):
            resolved[k] = _resolve_params(v)
        else:
            resolved[k] = v
    return resolved


def load_pipeline_config(
    source: Union[str, Path, Dict, List],
) -> List[StepConfig]:
    """Load pipeline config from YAML file path, or a raw dict/list."""
    if isinstance(source, list):
        raw = source
    elif isinstance(source, dict):
        raw = source.get("steps", source if isinstance(source, list) else [])
    else:
        with open(source, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict):
            raw = raw.get("steps", raw)

    steps: List[StepConfig] = []
    for step_data in raw:
        step_data = dict(step_data)  # shallow copy
        step_data.setdefault("params", {})
        step_data["params"] = _resolve_params(step_data["params"])

        if "retry_policy" in step_data and step_data["retry_policy"]:
            step_data["retry_policy"] = RetryPolicy(**step_data["retry_policy"])

        if "version" in step_data:
            from core.contracts import SemVer
            step_data["version"] = SemVer.parse(step_data.pop("version"))

        steps.append(StepConfig(**step_data))
    return steps


def dump_pipeline_config(
    steps: List[StepConfig], path: Union[str, Path, None] = None
) -> str:
    """Export StepConfig list to YAML string. Optionally write to file."""
    raw: List[Dict[str, Any]] = []
    for step in steps:
        d = asdict(step)
        if d.get("version"):
            d["version"] = str(d["version"])
        if d.get("retry_policy"):
            d["retry_policy"] = asdict(d["retry_policy"])
        raw.append(d)

    output = yaml.dump(raw, sort_keys=False, indent=2, allow_unicode=True)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
    return output


class ConfigurationError(Exception):
    """Raised when pipeline configuration is invalid (missing ENV var, bad YAML, etc.)."""
