"""E2E tests: planning engine → StreamingTraceRecord → SQLiteTraceSink (Phase 15).

Full-chain verification: enhanced planning stub with parallel branches,
written to SQLiteTraceSink, queried back with correct keys and agent identity.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from core.contracts.trace_keys import COMPONENT_TRACE_KEYS
from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY
from core.pipeline.tracing import StreamingTraceRecord
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext
from engines.planning.stub import StubPlanningEngine


async def _collect_streaming_records(run_id: str = "planning-e2e-1") -> list[StreamingTraceRecord]:
    """Collect StreamItems from the enhanced planning stub as StreamingTraceRecords."""
    engine = StubPlanningEngine()
    ctx = PlanningContext(
        goal="E2E test goal",
        agent_identity=AgentIdentity(
            id="planner-v1",
            role="planning",
            version="1.0.0",
            capabilities=("task_decomposition",),
        ),
    )
    records: list[StreamingTraceRecord] = []
    async for item in engine.plan(ctx, deadline=999.0, pace_config=None):
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="planning",
            dependency_name="stub",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="planning",
        ))
    return records


class TestPlanningE2E:
    """Full chain: planning stub → StreamingTraceRecord → SQLiteTraceSink → query."""

    def test_full_chain_planning_to_sink(self):
        """Planning engine output written to sink and queried back."""
        records = asyncio.run(_collect_streaming_records())
        assert len(records) == 8

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == 8
                assert result.sentinel_written is False

                rows = sink.query_by_engine("planning")
                assert len(rows) == 8
                for row in rows:
                    assert row["engine"] == "planning"
                    ctx = json.loads(row["trace_context_json"])
                    assert "planning.step_index" in ctx
                    assert "agent.identity" in ctx
                    identity = ctx["agent.identity"]
                    assert identity["id"] == "planner-v1"
                    assert identity["role"] == "planning"
            finally:
                sink.close()

    def test_orchestration_keys_in_passthrough_items(self):
        """Items 2-6 in sink carry orchestration keys (passthrough)."""
        records = asyncio.run(_collect_streaming_records())

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("planning-e2e-1")
                orch_items = [r for r in rows if r["item_index"] in (2, 3, 4, 5, 6)]
                assert len(orch_items) == 5
                for row in orch_items:
                    ctx = json.loads(row["trace_context_json"])
                    assert "orchestration.dag_node_id" in ctx
                    assert "orchestration.merge_ordinal" in ctx
                    assert "orchestration.branch_taken" in ctx
                    assert "retrieval.chunk_id" in ctx
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
                rows = sink.query_by_run("planning-e2e-1")
                orch_items = [r for r in rows if r["item_index"] in (2, 3, 4, 5, 6)]
                ordinals = [
                    json.loads(r["trace_context_json"])["orchestration.merge_ordinal"]
                    for r in orch_items
                ]
                assert ordinals == [0, 1, 2, 3, 4]
            finally:
                sink.close()

    def test_query_by_engine_planning(self):
        """query_by_engine('planning') returns only planning engine items."""
        records = asyncio.run(_collect_streaming_records("planning-e2e-engine"))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_engine("planning")
                assert len(rows) == 8
                for row in rows:
                    assert row["engine"] == "planning"
            finally:
                sink.close()


class TestPlanningSchemaNoMigration:
    """CURRENT_SCHEMA_VERSION stays at 2 — no DDL change for agent namespace."""

    def test_schema_version_stays_at_2(self):
        assert CURRENT_SCHEMA_VERSION == 2

    def test_agent_keys_no_ddl_change(self):
        """Fresh sink with agent key still creates schema_version=2."""
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


class TestPlanningSeedCount:
    """Seed count is dynamic — all keys from TRACE_KEY_REGISTRY."""

    def test_total_seed_count_is_16(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                all_keys = sink.query_keys()
                assert len(all_keys) == len(TRACE_KEY_REGISTRY) + len(COMPONENT_TRACE_KEYS)
            finally:
                sink.close()

    def test_agent_identity_not_in_component_candidate(self):
        """query_keys(component_candidate_only=True) excludes agent.identity."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                candidates = sink.query_keys(component_candidate_only=True)
                # 3 engine component_candidate + 3 component = 6 (no change from Phase 14)
                assert len(candidates) == 6
                for c in candidates:
                    assert not c["key_name"].startswith("agent.")
            finally:
                sink.close()
