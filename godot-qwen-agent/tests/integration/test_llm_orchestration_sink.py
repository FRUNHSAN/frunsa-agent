"""Integration tests for LLMOrchestrationEngine with SQLiteTraceSink.

Phase 18 Task 2: Validates key seeding, write/query, and metadata
pass-through from LLMOrchestrationEngine to SQLite sink.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts.streaming_protocol import PaceConfig
from core.observability.sqlite_sink import SQLiteTraceSink
from core.pipeline.tracing import StreamingTraceRecord
from engines.orchestration.identity import OrchestratorIdentity
from engines.orchestration.interface import BranchSpec, OrchestrationContext
from engines.orchestration.llm import (
    DEFAULT_MERGE_RESPONSE,
    DEFAULT_RETRY_RESPONSE,
    DEFAULT_ROUTE_RESPONSE,
    LLMOrchestrationEngine,
    MockOrchBackend,
)


def _default_context():
    return OrchestrationContext(
        branches=(
            BranchSpec(name="fast_path", pool="cpu", items=2),
            BranchSpec(name="rerank", pool="gpu", items=1),
        ),
        agent_identity=OrchestratorIdentity(
            id="orch-v1", role="orchestration", version="1.0.0",
        ),
    )


def _default_adapter():
    return GenerationAdapter(
        MockOrchBackend(responses=(
            DEFAULT_ROUTE_RESPONSE,
            DEFAULT_MERGE_RESPONSE,
            DEFAULT_RETRY_RESPONSE,
        )),
        dependency_name="mock_orch",
    )


async def _collect_and_sink(engine, context, sink, run_id="int-test"):
    """Collect all items from engine, convert to records, and write to sink."""
    records = []
    async for item in engine.orchestrate(context, 10.0, PaceConfig()):
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="orchestration",
            dependency_name="llm",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="orchestration",
        ))
    sink.write_streaming(records)
    return records


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def sink_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test.db")


# ── TestSinkKeySeeding ─────────────────────────────────────────────────


class TestSinkKeySeeding:
    """LLM orchestration keys are properly seeded in the sink."""

    def test_orchestration_keys_seeded(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            rows = sink._conn.execute(
                "SELECT key_name FROM trace_keys WHERE engine = ?", ("orchestration",)
            ).fetchall()
            keys = {r[0] for r in rows}
            assert "orchestration.dag_node_id" in keys
            assert "orchestration.parallel_depth" in keys
            assert "orchestration.merge_ordinal" in keys
            assert "orchestration.branch_taken" in keys
            assert "orchestration.retry_count" in keys
            assert "orchestration.resource_pool_key" in keys
        finally:
            sink.close()

    def test_agent_identity_seeded_for_orchestration(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            rows = sink._conn.execute(
                "SELECT key_name FROM trace_keys WHERE key_name = ?",
                ("agent.identity",),
            ).fetchall()
            assert len(rows) == 1
        finally:
            sink.close()


# ── TestSinkWriteQuery ─────────────────────────────────────────────────


class TestSinkWriteQuery:
    """LLM orchestration items can be written to and queried from sink."""

    def test_write_and_query_by_engine(self, sink_path):
        engine = LLMOrchestrationEngine(_default_adapter())
        context = _default_context()
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_collect_and_sink(engine, context, sink))
            rows = sink.query_by_engine("orchestration")
            assert len(rows) > 0
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                assert "orchestration.dag_node_id" in ctx
        finally:
            sink.close()

    def test_all_six_keys_in_sink_trace_context(self, sink_path):
        engine = LLMOrchestrationEngine(_default_adapter())
        context = _default_context()
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_collect_and_sink(engine, context, sink))
            rows = sink.query_by_engine("orchestration")
            required = {f"orchestration.{k}" for k in (
                "dag_node_id", "parallel_depth", "merge_ordinal",
                "branch_taken", "retry_count", "resource_pool_key",
            )}
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                missing = required - set(ctx.keys())
                assert not missing, f"Missing in sink: {missing}"
        finally:
            sink.close()


# ── TestMetadataPassthrough ────────────────────────────────────────────


class TestMetadataPassthrough:
    """metadata slot passes through to sink without guardrail interference."""

    def test_metadata_in_context_accepted(self, sink_path):
        context = OrchestrationContext(
            branches=(BranchSpec(name="test", pool="cpu", items=1),),
            agent_identity=OrchestratorIdentity(
                id="orch-v1", role="orchestration", version="1.0.0",
            ),
            metadata={"routing_algorithm": "round_robin_v2", "latency_ms": 42},
        )
        backend = MockOrchBackend(responses=(
            '{"branches": [{"name": "test", "pool": "cpu", "items": 1}], "parallel_depth": 1}',
            '{"strategy": "sequential"}',
        ))
        adapter = GenerationAdapter(backend, dependency_name="mock_orch")
        engine = LLMOrchestrationEngine(adapter)
        sink = SQLiteTraceSink(sink_path)
        try:
            items = asyncio.run(_collect_and_sink(engine, context, sink))
            assert len(items) > 0
        finally:
            sink.close()

    def test_sink_survives_metadata_in_context(self, sink_path):
        context = OrchestrationContext(
            branches=(BranchSpec(name="s", pool="cpu", items=1),),
            agent_identity=OrchestratorIdentity(
                id="o", role="orchestration", version="1.0.0",
            ),
            metadata={"new_field": True},
        )
        backend = MockOrchBackend(responses=(
            '{"branches": [{"name": "s", "pool": "cpu", "items": 1}], "parallel_depth": 1}',
            '{"strategy": "sequential"}',
        ))
        adapter = GenerationAdapter(backend, dependency_name="mock_orch")
        engine = LLMOrchestrationEngine(adapter)
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_collect_and_sink(engine, context, sink))
            rows = sink.query_by_engine("orchestration")
            assert len(rows) >= 1
        finally:
            sink.close()
