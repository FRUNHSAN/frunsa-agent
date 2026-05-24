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


# ── Span types for distinguishing internal vs external work ─────


class SpanType(str, Enum):
    STEP_EXECUTION = "step"
    DEPENDENCY_CALL = "dep_call"
    RESOURCE_ACQUIRE = "resource"


# ── Trace data classes ──────────────────────────────────────────


@dataclass
class DependencyCallTrace:
    """Trace for a single external dependency call (vector store query, LLM API, etc.)."""
    dependency_name: str
    span_type: SpanType = SpanType.DEPENDENCY_CALL
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0
    status: Literal["success", "timeout", "error"] = "success"
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_context: Optional[Dict[str, Any]] = None
    # Captures trace_context from the LAST StreamItem in this dependency call.
    # For engines emitting per-step context (e.g., Planning), only the terminal
    # step's context is retained here. Per-item streaming trace → Phase 12+.


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
    dependency_calls: List[DependencyCallTrace] = field(default_factory=list)
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


# ── Per-item streaming trace (Phase 12) ──────────────────────────────


@dataclass(frozen=True)
class StreamingTraceRecord:
    """Per-StreamItem trace record for per-item observability.

    Unlike DependencyCallTrace (which captures only the LAST item's
    trace_context), StreamingTraceRecord captures context from EVERY
    StreamItem in a dependency call. This enables per-item latency
    analysis, streaming completeness verification, and component-level
    trace key empirical analysis.

    Cost boundary: the StreamingTraceWriter protocol enforces
    max_items_per_call to prevent unbounded storage inflation.
    A RAG call with 50 chunks would otherwise produce 50 records
    vs Planning's 3 — 16x asymmetry.
    """

    pipeline_run_id: str
    step_name: str
    dependency_name: str
    item_index: int
    item_delta_preview: str     # first 200 chars of StreamItem.delta
    is_terminal: bool
    trace_context: Optional[Dict[str, Any]]
    ts_iso: str                 # ISO 8601 timestamp captured at item yield time
    engine: str = ""            # inferred from trace_context keys (lazy, filled by sink)


@dataclass(frozen=True)
class StreamingWriteResult:
    """Feedback from sink about what was actually stored.

    Adapters collect ALL StreamingTraceRecords blindly — no truncation logic.
    The sink enforces max_items_per_call and reports back what happened.
    This removes duplicate truncation/counting logic from every adapter
    implementation and makes cost boundary enforcement type-enforced
    rather than convention-based.
    """

    accepted_count: int        # actually written per-item records
    overflow_count: int        # truncated count (0 = no truncation)
    sentinel_written: bool     # whether an overflow sentinel was appended


class StreamingTraceWriter(Protocol):
    """Pluggable per-item trace writer with cost boundary enforcement.

    DISTINCT from TraceWriter (which writes summary TraceLog records).
    StreamingTraceWriter writes individual StreamItem trace records
    for granular per-item observability.

    Cost boundary enforcement lives in the SINK, not the adapter. Adapters
    blindly collect ALL StreamingTraceRecords and pass them to
    write_streaming(). The sink truncates to max_items_per_call, appends
    overflow sentinel, and returns StreamingWriteResult. Single
    responsibility — no duplicate truncation logic across N adapter
    implementations.

    The max_items_per_call property is NOT an optimization — it is a
    structural requirement. Without it, a dependency call producing 50
    items vs one producing 3 would create 16x storage inflation with
    no upper bound. Every implementation MUST declare this cap.
    """

    @property
    def max_items_per_call(self) -> int:
        """Hard cap on per-item records stored per dependency call.

        Semantics:
          -1 = unlimited (opt-in to unbounded storage risk)
           0 = count-only (no per-item records; sentinel records total count)
          >0 = store at most N per-item records; overflow counted in sentinel
        """
        ...

    def write_streaming(
        self, records: List[StreamingTraceRecord]
    ) -> StreamingWriteResult:
        """Write per-item streaming trace records.

        The implementation MUST enforce max_items_per_call:
          - If max_items_per_call == 0: no per-item records, sentinel only.
          - If max_items_per_call > 0 and len(records) > cap: truncate + sentinel.
          - If max_items_per_call == -1: unlimited, no truncation.

        Returns StreamingWriteResult with accepted/overflow/sentinel counts.
        """
        ...
