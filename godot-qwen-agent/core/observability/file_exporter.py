"""FileTraceExporter: writes trace_context from TraceLog as JSON Lines.

Implements TraceWriter protocol. Pure stdlib. Append-only.

Each output line is a self-contained JSON object representing one
DependencyCallTrace record. trace_context from the LAST StreamItem
in each dependency call is included. Per-item streaming trace is
deferred to Phase 12+.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from core.pipeline.tracing import TraceLog, TraceWriter


def _get_registry_keys() -> frozenset:
    """Lazy-load TRACE_KEY_REGISTRY keys (shared with guardrail)."""
    try:
        from core.observability.trace_registry import TRACE_KEY_REGISTRY
        return frozenset(TRACE_KEY_REGISTRY.keys())
    except ImportError:
        return frozenset()


class FileTraceExporter:
    """Writes trace_context from TraceLog as JSON Lines.

    Implements TraceWriter protocol. Pure stdlib. Append-only.

    Each output line corresponds to one DependencyCallTrace record.
    trace_context from the LAST StreamItem in each dependency call is
    included. Per-item streaming trace is deferred to Phase 12+.

    Usage:
        exporter = FileTraceExporter("traces.jsonl")
        runner = PipelineRunner(..., trace_writer=exporter)
        runner.run(...)  # trace_context automatically captured
    """

    def __init__(self, path: str, *, sample_rate: float = 1.0) -> None:
        if not 0.0 < sample_rate <= 1.0:
            raise ValueError(f"sample_rate must be in (0, 1], got {sample_rate}")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._sample_rate = sample_rate
        self._lines_buffer: List[str] = []

    @property
    def sample_rate(self) -> float:
        return self._sample_rate

    def write(self, traces: List[TraceLog]) -> None:
        """Extract DependencyCallTrace records and write as JSON Lines.

        Batches all records into a single string, then writes in one
        syscall. Prevents line interleaving if multiple writers share
        the same file path.
        """
        lines: List[str] = []
        registry_keys = _get_registry_keys()

        for trace_log in traces:
            for step in trace_log.steps:
                for dep_call in step.dependency_calls:
                    if dep_call.trace_context is None:
                        continue
                    if self._sample_rate < 1.0 and random.random() > self._sample_rate:
                        continue

                    ctx = dep_call.trace_context
                    record: Dict[str, Any] = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "run_id": trace_log.pipeline_run_id,
                        "step": step.step_name,
                        "dependency": dep_call.dependency_name,
                        "status": dep_call.status,
                        "duration_ms": dep_call.duration_ms,
                        "engine": self._infer_engine(ctx),
                        "trace_context": ctx,
                        "_registered_keys": [k for k in ctx if k in registry_keys],
                        "_unregistered_keys": [k for k in ctx if k not in registry_keys],
                    }
                    lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))

        if lines:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    # ── Engine prefix inference (O(1) lookup via registry-derived cache) ──

    @staticmethod
    @lru_cache(maxsize=1)  # registry is read-only, cache forever
    def _get_engine_prefix_map() -> Dict[str, str]:
        """Build reverse lookup: key_prefix → engine name from registry."""
        from core.observability.trace_registry import TRACE_KEY_REGISTRY
        return {
            key.split(".")[0]: defn.engine
            for key, defn in TRACE_KEY_REGISTRY.items()
        }

    @staticmethod
    def _infer_engine(ctx: Dict[str, Any]) -> str:
        prefix_map = FileTraceExporter._get_engine_prefix_map()
        for key in ctx:
            prefix = key.split(".", 1)[0]
            if prefix in prefix_map:
                return prefix_map[prefix]
        # Fallback only for truly unregistered keys during bootstrap
        return next((k.split(".", 1)[0] for k in ctx if "." in k), "unknown")
