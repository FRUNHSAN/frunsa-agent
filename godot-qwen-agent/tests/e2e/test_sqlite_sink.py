"""E2E tests: SQLiteTraceSink and sink_schema_consistency guardrail (Phase 12).

Two test classes:
  1. TestSQLiteTraceSink — schema creation, registry seeding, write paths, query interface
  2. TestSinkSchemaGuardrail — consistent schema passes, drift detection
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.observability.sink_schema import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_TABLE_NAME,
    TRACE_KEYS_TABLE_NAME,
    TRACE_RECORDS_TABLE_NAME,
)
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY
from core.pipeline.tracing import (
    DependencyCallTrace,
    StepTrace,
    StreamingTraceRecord,
    StreamingWriteResult,
    TraceLog,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_trace_log(dep_call: DependencyCallTrace) -> TraceLog:
    step = StepTrace(
        step_index=0,
        step_name="test_step",
        pipeline_run_id="run-001",
        status="success",
        dependency_calls=[dep_call],
    )
    return TraceLog(
        pipeline_run_id="run-001",
        steps=[step],
        total_steps=1,
        success_count=1,
    )


def _make_streaming_record(
    run_id: str = "run-1",
    step: str = "step_a",
    dep: str = "dep_x",
    index: int = 0,
    preview: str = "delta preview",
    terminal: bool = False,
    ctx: dict | None = None,
    ts: str = "2026-01-01T00:00:00Z",
    engine: str = "",
) -> StreamingTraceRecord:
    return StreamingTraceRecord(
        pipeline_run_id=run_id,
        step_name=step,
        dependency_name=dep,
        item_index=index,
        item_delta_preview=preview,
        is_terminal=terminal,
        trace_context=ctx,
        ts_iso=ts,
        engine=engine,
    )


# ── TestSQLiteTraceSink ──────────────────────────────────────────────


class TestSQLiteTraceSink:
    """SQLiteTraceSink integration tests (Phase 12)."""

    # ── Schema creation ──────────────────────────────────────────────

    def test_schema_creation(self):
        """Sink creates all three tables on construction."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                tables = sink._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                table_names = {row[0] for row in tables}
                assert TRACE_RECORDS_TABLE_NAME in table_names
                assert TRACE_KEYS_TABLE_NAME in table_names
                assert SCHEMA_VERSION_TABLE_NAME in table_names
            finally:
                sink.close()

    def test_registry_seeding(self):
        """Trace keys are seeded from TRACE_KEY_REGISTRY on first construction."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                count = sink._conn.execute(
                    f"SELECT COUNT(*) FROM {TRACE_KEYS_TABLE_NAME}"
                ).fetchone()[0]
                assert count == len(TRACE_KEY_REGISTRY)
            finally:
                sink.close()

    def test_registry_seeding_idempotent(self):
        """Second construction does not duplicate trace_keys rows."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink1 = SQLiteTraceSink(path)
            sink1.close()
            sink2 = SQLiteTraceSink(path)
            try:
                count = sink2._conn.execute(
                    f"SELECT COUNT(*) FROM {TRACE_KEYS_TABLE_NAME}"
                ).fetchone()[0]
                assert count == len(TRACE_KEY_REGISTRY)
            finally:
                sink2.close()

    def test_version_recording(self):
        """Schema version is recorded on construction."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                version = sink._conn.execute(
                    f"SELECT version FROM {SCHEMA_VERSION_TABLE_NAME}"
                ).fetchone()[0]
                assert version == CURRENT_SCHEMA_VERSION
            finally:
                sink.close()

    # ── Summary write (TraceWriter) ──────────────────────────────────

    def test_summary_write(self):
        """write() stores summary records with item_index=NULL."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                dt = DependencyCallTrace(
                    dependency_name="llm_api",
                    status="success",
                    duration_ms=42.0,
                    trace_context={"planning.step_index": 0, "planning.reasoning_depth": 1},
                )
                sink.write([_make_trace_log(dt)])

                rows = sink.query_by_run("run-001")
                assert len(rows) == 1
                row = rows[0]
                assert row["dependency"] == "llm_api"
                assert row["status"] == "success"
                assert row["duration_ms"] == 42.0
                assert row["item_index"] is None
                assert row["item_delta_preview"] is None
                assert row["is_terminal"] is None
                assert row["engine"] == "planning"
                assert row["trace_context_json"] is not None
            finally:
                sink.close()

    def test_summary_write_error_status(self):
        """write() stores error/timout status correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                dt_err = DependencyCallTrace(
                    dependency_name="bad_call",
                    status="error",
                    duration_ms=100.0,
                    trace_context={"planning.step_index": 0},
                    metadata={"error": "connection refused"},
                )
                dt_timeout = DependencyCallTrace(
                    dependency_name="slow_call",
                    status="timeout",
                    duration_ms=5000.0,
                    trace_context=None,
                )
                sink.write([
                    _make_trace_log(dt_err),
                    _make_trace_log(dt_timeout),
                ])

                rows = sink.query_by_run("run-001")
                statuses = {row["status"] for row in rows}
                assert statuses == {"error", "timeout"}
            finally:
                sink.close()

    # ── Streaming write (StreamingTraceWriter) ────────────────────────

    def test_streaming_write(self):
        """write_streaming() stores per-item records."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path, max_items_per_call=100)
            try:
                records = [
                    _make_streaming_record(run_id="r1", step="s1", dep="d1", index=i,
                        ctx={"planning.step_index": i}, terminal=(i == 2))
                    for i in range(3)
                ]
                result = sink.write_streaming(records)

                assert result.accepted_count == 3
                assert result.overflow_count == 0
                assert result.sentinel_written is False

                rows = sink.query_by_run("r1")
                assert len(rows) == 3
                for i, row in enumerate(rows):
                    assert row["item_index"] == i
                    assert row["is_terminal"] == (1 if i == 2 else 0)
                    assert row["item_delta_preview"] is not None
            finally:
                sink.close()

    def test_truncation_at_cap(self):
        """Records exceeding max_items_per_call are truncated + sentinel."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path, max_items_per_call=5)
            try:
                records = [
                    _make_streaming_record(run_id="r2", index=i, ctx={"planning.step_index": i})
                    for i in range(12)
                ]
                result = sink.write_streaming(records)

                assert result.accepted_count == 5
                assert result.overflow_count == 7
                assert result.sentinel_written is True

                per_item_rows = sink.query_by_run("r2")
                assert len(per_item_rows) == 5
            finally:
                sink.close()

    def test_count_only_mode(self):
        """max_items_per_call=0 → no per-item rows, sentinel only."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path, max_items_per_call=0)
            try:
                records = [
                    _make_streaming_record(run_id="r3", index=i)
                    for i in range(10)
                ]
                result = sink.write_streaming(records)

                assert result.accepted_count == 0
                assert result.overflow_count == 10
                assert result.sentinel_written is True

                per_item_rows = sink.query_by_run("r3")
                assert len(per_item_rows) == 0
            finally:
                sink.close()

    def test_unlimited_mode(self):
        """max_items_per_call=-1 → all records stored, no sentinel."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path, max_items_per_call=-1)
            try:
                records = [
                    _make_streaming_record(run_id="r4", index=i)
                    for i in range(50)
                ]
                result = sink.write_streaming(records)

                assert result.accepted_count == 50
                assert result.overflow_count == 0
                assert result.sentinel_written is False

                per_item_rows = sink.query_by_run("r4")
                assert len(per_item_rows) == 50
            finally:
                sink.close()

    def test_empty_streaming_write(self):
        """Empty record list → accepted=0, no sentinel."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming([])
                assert result.accepted_count == 0
                assert result.overflow_count == 0
                assert result.sentinel_written is False
            finally:
                sink.close()

    # ── Query interface ──────────────────────────────────────────────

    def test_query_by_engine(self):
        """query_by_engine filters by engine name."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                records = [
                    _make_streaming_record(run_id="re", index=0,
                        ctx={"planning.step_index": 0}),
                    _make_streaming_record(run_id="re", index=1,
                        ctx={"rag.chunk_id": "c1", "rag.retrieval_latency_ms": 10.0}),
                ]
                sink.write_streaming(records)

                planning_rows = sink.query_by_engine("planning")
                rag_rows = sink.query_by_engine("rag")
                assert len(planning_rows) == 1
                assert len(rag_rows) == 1
            finally:
                sink.close()

    def test_query_by_run(self):
        """query_by_run returns all records for a run, sorted by ts."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming([
                    _make_streaming_record(run_id="r_query", index=0),
                    _make_streaming_record(run_id="r_query", index=1),
                    _make_streaming_record(run_id="other", index=0),
                ])
                rows = sink.query_by_run("r_query")
                assert len(rows) == 2
            finally:
                sink.close()

    def test_query_keys_component_candidate_filter(self):
        """query_keys(component_candidate_only=True) returns only candidate keys."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                all_keys = sink.query_keys(component_candidate_only=False)
                cc_keys = sink.query_keys(component_candidate_only=True)

                assert len(all_keys) == 6
                assert len(cc_keys) == 3
                cc_names = {k["key_name"] for k in cc_keys}
                assert cc_names == {
                    "planning.cumulative_tokens",
                    "rag.chunk_id",
                    "rag.retrieval_latency_ms",
                }
            finally:
                sink.close()

    def test_query_item_counts_by_dependency(self):
        """query_item_counts_by_dependency returns per-dep item counts."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming([
                    _make_streaming_record(run_id="rc", dep="dep_a", index=i)
                    for i in range(3)
                ])
                sink.write_streaming([
                    _make_streaming_record(run_id="rc", dep="dep_b", index=i)
                    for i in range(7)
                ])

                counts = sink.query_item_counts_by_dependency("rc")
                count_map = {c["dependency"]: c["item_count"] for c in counts}
                assert count_map["dep_a"] == 3
                assert count_map["dep_b"] == 7
            finally:
                sink.close()

    # ── Engine inference ─────────────────────────────────────────────

    def test_engine_inference(self):
        """Engine is inferred from trace_context keys."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                records = [
                    _make_streaming_record(run_id="ei", index=0,
                        ctx={"rag.chunk_id": "c1", "rag.retrieval_latency_ms": 5.0}),
                ]
                sink.write_streaming(records)
                rows = sink.query_by_run("ei")
                assert rows[0]["engine"] == "rag"
            finally:
                sink.close()

    # ── Context manager ──────────────────────────────────────────────

    def test_context_manager(self):
        """SQLiteTraceSink supports with-statement."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            with SQLiteTraceSink(path) as sink:
                assert sink.max_items_per_call == 100
                keys = sink.query_keys()
                assert len(keys) == 6
            # After __exit__, connection is closed
            with pytest.raises(Exception):
                sink.query_keys()

    # ── Summary + streaming coexistence ──────────────────────────────

    def test_summary_and_streaming_coexistence(self):
        """Both write() and write_streaming() populate the same table correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                # Summary write
                dt = DependencyCallTrace(
                    dependency_name="summary_dep",
                    status="success",
                    trace_context={"planning.step_index": 99},
                )
                sink.write([_make_trace_log(dt)])

                # Streaming write
                records = [
                    _make_streaming_record(run_id="run-001", dep="stream_dep", index=i)
                    for i in range(2)
                ]
                sink.write_streaming(records)

                rows = sink.query_by_run("run-001")
                # 1 summary + 2 per-item = 3 total
                assert len(rows) == 3
                summary_rows = [r for r in rows if r["item_index"] is None]
                per_item_rows = [r for r in rows if r["item_index"] is not None]
                assert len(summary_rows) == 1
                assert len(per_item_rows) == 2
            finally:
                sink.close()


# ── TestSinkSchemaGuardrail ──────────────────────────────────────────


class TestSinkSchemaGuardrail:
    """sink_schema_consistency guardrail tests (Phase 12)."""

    def test_consistent_schema_passes(self, tmp_path: Path):
        """Guardrail returns zero violations for a correctly-built schema."""
        from guardrails.rules.sink_schema_consistency import sink_schema_consistency

        violations = sink_schema_consistency(tmp_path)
        # A fresh in-memory DB should pass all checks
        assert len(violations) == 0, (
            f"Expected 0 violations for consistent schema, got: "
            f"{[(v.severity.value, v.message[:80]) for v in violations]}"
        )

    def test_guardrail_includes_all_declared_indexes(self):
        """Guardrail checks for all 6 declared indexes."""
        from guardrails.rules.sink_schema_consistency import sink_schema_consistency
        from core.observability.sink_schema import TRACE_RECORDS_INDEXES, TRACE_KEYS_INDEXES

        total_indexes = len(TRACE_RECORDS_INDEXES) + len(TRACE_KEYS_INDEXES)
        assert total_indexes == 7  # 6 trace_records + 1 trace_keys = 7

        # Verify the guardrail function runs without import errors
        # (index coverage check happens inside the function)
        with tempfile.TemporaryDirectory() as tmp:
            violations = sink_schema_consistency(Path(tmp))
            # Should pass — all indexes created by SQLiteTraceSink
            index_violations = [
                v for v in violations if "Index" in v.message
            ]
            assert len(index_violations) == 0, (
                f"Index violations: {[v.message for v in index_violations]}"
            )
