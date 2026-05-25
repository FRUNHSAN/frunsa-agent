"""E2E tests: orchestration stub → StreamingTraceRecord → SQLiteTraceSink (Phase 14).

Full-chain verification: stub output captured as StreamingTraceRecords,
written to SQLiteTraceSink, then queried back with correct engine and keys.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY
from core.pipeline.tracing import StreamingTraceRecord
from engines.orchestration.stub import StubOrchestrationEngine


async def _collect_streaming_records(run_id: str = "orch-e2e-1") -> list[StreamingTraceRecord]:
    """Collect StreamItems from the stub and convert to StreamingTraceRecords."""
    engine = StubOrchestrationEngine()
    records: list[StreamingTraceRecord] = []
    async for item in engine.orchestrate():
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="orchestration",
            dependency_name="stub",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="orchestration",
        ))
    return records


class TestOrchestrationE2E:
    """Full chain: stub → StreamingTraceRecord → SQLiteTraceSink → query."""

    def test_full_chain_write_and_query(self):
        """Stub output written to sink, then queried back by engine."""
        records = asyncio.run(_collect_streaming_records())
        assert len(records) == 5  # 3 fast_path + 2 full_rerank

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == 5
                assert result.overflow_count == 0
                assert result.sentinel_written is False

                rows = sink.query_by_engine("orchestration")
                assert len(rows) == 5
                for row in rows:
                    assert row["engine"] == "orchestration"
                    ctx = json.loads(row["trace_context_json"])
                    assert "orchestration.dag_node_id" in ctx
                    assert "orchestration.parallel_depth" in ctx
                    assert "orchestration.merge_ordinal" in ctx
                    assert "orchestration.branch_taken" in ctx
                    assert "orchestration.retry_count" in ctx
                    assert "orchestration.resource_pool_key" in ctx
                    assert "retrieval.chunk_id" in ctx
                    assert "retrieval.latency_ms" in ctx
            finally:
                sink.close()

    def test_all_six_orchestration_keys_in_trace_context(self):
        """Every stored record carries all 6 orchestration keys."""
        records = asyncio.run(_collect_streaming_records())

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("orch-e2e-1")

                required = {
                    "orchestration.dag_node_id",
                    "orchestration.parallel_depth",
                    "orchestration.merge_ordinal",
                    "orchestration.branch_taken",
                    "orchestration.retry_count",
                    "orchestration.resource_pool_key",
                }
                for i, row in enumerate(rows):
                    ctx = json.loads(row["trace_context_json"])
                    missing = required - set(ctx.keys())
                    assert not missing, f"Row {i}: missing keys: {missing}"
            finally:
                sink.close()

    def test_merge_ordinal_sequential_in_sink(self):
        """merge_ordinal values in sink are sequential 0..4."""
        records = asyncio.run(_collect_streaming_records())

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("orch-e2e-1")
                ordinals = [json.loads(row["trace_context_json"])["orchestration.merge_ordinal"] for row in rows]
                assert ordinals == list(range(5))
            finally:
                sink.close()

    def test_query_by_run_returns_all_items(self):
        """query_by_run returns all 5 items for the run."""
        records = asyncio.run(_collect_streaming_records("orch-e2e-run"))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("orch-e2e-run")
                assert len(rows) == 5
                for row in rows:
                    assert row["item_index"] is not None
                    assert row["is_terminal"] in (0, 1)
            finally:
                sink.close()


class TestOrchestrationSchemaNoMigration:
    """CURRENT_SCHEMA_VERSION stays at 2 — no DDL change for orchestration."""

    def test_schema_version_stays_at_2(self):
        assert CURRENT_SCHEMA_VERSION == 2

    def test_orchestration_keys_no_ddl_change(self):
        """Fresh sink with orchestration still creates schema_version=2."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                version = sink._conn.execute(
                    "SELECT version FROM schema_version"
                ).fetchone()[0]
                assert version == 2
            finally:
                sink.close()


class TestOrchestrationSeedCount:
    """Seed count: 15 total (6 engine + 3 component + 6 orchestration)."""

    def test_total_seed_count_is_15(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                all_keys = sink.query_keys()
                assert len(all_keys) == 16  # Phase 15: +agent.identity
            finally:
                sink.close()

    def test_orchestration_keys_not_in_component_keys(self):
        """query_component_keys() does not include orchestration keys."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                comp_keys = sink.query_component_keys()
                comp_names = {k["key_name"] for k in comp_keys}
                for name in comp_names:
                    assert not name.startswith("orchestration."), (
                        f"{name} should not be in component keys"
                    )
            finally:
                sink.close()

    def test_orchestration_not_in_component_candidate(self):
        """query_keys(component_candidate_only=True) excludes orchestration."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                candidates = sink.query_keys(component_candidate_only=True)
                # 3 engine candidate + 3 component = 6
                assert len(candidates) == 6
                for c in candidates:
                    assert not c["key_name"].startswith("orchestration.")
            finally:
                sink.close()
