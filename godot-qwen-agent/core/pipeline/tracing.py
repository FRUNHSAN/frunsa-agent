"""Observability primitives: traces, snapshots, and pluggable trace writers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Literal, Optional, Protocol


class SnapshotPolicy(Enum):
    FULL = "full"
    SUMMARY = "summary"
    NONE = "none"


# ── Snapshot helpers ────────────────────────────────────────────


def snapshot(value: Any, policy: SnapshotPolicy) -> Any:
    if policy == SnapshotPolicy.NONE:
        return None
    if policy == SnapshotPolicy.FULL:
        return _deep_serializable(value)
    if policy == SnapshotPolicy.SUMMARY:
        return _summarize(value)
    return None


def _deep_serializable(value: Any) -> Any:
    """Convert value to a JSON-safe representation recursively."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_deep_serializable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _deep_serializable(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict
        # asdict() preserves enums — re-process every value
        raw = asdict(value)
        return _deep_serializable(raw)
    return str(value)[:1000]


def _summarize(value: Any, preview_chars: int = 200) -> dict:
    """Lightweight summary: type, count, blake2b fingerprint, preview.

    Hash is for change detection only — no cryptographic guarantees.
    Uses blake2b (3-5x faster than sha256).
    """
    if value is None:
        return {"type": "NoneType", "count": 0}
    if isinstance(value, list):
        if len(value) == 0:
            fp = b"empty_list"
        else:
            first_type = type(value[0]).__name__.encode()
            last_type = type(value[-1]).__name__.encode()
            fp = f"{len(value)}:{first_type}:{last_type}".encode()
        return {
            "type": "list",
            "count": len(value),
            "hash": hashlib.blake2b(fp, digest_size=8).hexdigest(),
            "preview": repr(value[:3])[:preview_chars],
        }
    if isinstance(value, str):
        limited = value[:10000].encode()
        return {
            "type": "str",
            "length": len(value),
            "hash": hashlib.blake2b(limited, digest_size=8).hexdigest(),
            "preview": value[:preview_chars],
        }
    if isinstance(value, dict):
        return {"type": "dict", "keys": list(value.keys())[:20], "count": len(value)}
    return {"type": type(value).__name__, "repr": repr(value)[:preview_chars]}


# ── Trace data classes ──────────────────────────────────────────


@dataclass
class StepTrace:
    step_index: int
    step_name: str
    pipeline_run_id: str
    parent_run_id: Optional[str] = None
    snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY
    component_type: str = ""
    strategy: str = ""
    status: Literal["pending", "running", "success", "failed", "skipped", "cancelled"] = "pending"
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    input_keys: List[str] = field(default_factory=list)
    input_snapshot: Optional[Dict[str, Any]] = None
    output_key: str = ""
    output_snapshot: Optional[Any] = None
    params: Dict[str, Any] = field(default_factory=dict)
    contract_validation: Optional[Any] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None


@dataclass
class TraceLog:
    pipeline_run_id: str
    parent_run_id: Optional[str] = None
    pipeline_version: int = 1
    started_at_iso: str = ""
    finished_at_iso: str = ""
    total_duration_seconds: float = 0.0
    snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY
    steps: List[StepTrace] = field(default_factory=list)
    total_steps: int = 0
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0
    cancelled_count: int = 0

    def to_dict(self) -> dict:
        return _deep_serializable(self)


# ── Pluggable trace writers ─────────────────────────────────────


class TraceWriter(Protocol):
    """Pluggable trace writer. Default: LocalJSONWriter. Extend: Kafka, S3, DB."""

    def write(self, traces: List[TraceLog]) -> None: ...


class LocalJSONWriter:
    def __init__(self, path: str) -> None:
        from pathlib import Path
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, traces: List[TraceLog]) -> None:
        import json
        data = [t.to_dict() for t in traces]
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, separators=(",", ":")) + "\n")


def serialize_tracelog(trace_log: TraceLog, fmt: str = "json") -> str | bytes:
    """Serialize a single TraceLog. 'json' for human-readable, 'msgpack' for production."""
    data = trace_log.to_dict()

    if fmt == "json":
        import json
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    if fmt == "msgpack":
        import msgpack
        from datetime import datetime
        from uuid import UUID

        def _default(obj: Any) -> str:
            if isinstance(obj, (datetime, UUID)):
                return str(obj)
            raise TypeError(f"Unsupported type: {type(obj)}")

        return msgpack.dumps(data, default=_default, use_bin_type=True)

    raise ValueError(f"Unknown format: '{fmt}'. Use 'json' or 'msgpack'.")
