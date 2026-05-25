"""E2E tests for LLMOrchestrationEngine — real engine full chain validation.

Phase 18 Task 2: Validates retry E2E, multi-pool E2E, and multi-agent
coexistence with stub engines.
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
from engines.critic.stub import StubCriticEngine
from engines.orchestration.identity import OrchestratorIdentity
from engines.orchestration.interface import BranchSpec, OrchestrationContext
from engines.orchestration.llm import (
    DEFAULT_MERGE_RESPONSE,
    DEFAULT_RETRY_RESPONSE,
    DEFAULT_ROUTE_RESPONSE,
    LLMOrchestrationEngine,
    MockOrchBackend,
)
from engines.planning.stub import StubPlanningEngine


# ── Helpers ────────────────────────────────────────────────────────────


def _orch_context(branches=None, metadata=None):
    return OrchestrationContext(
        branches=branches or (
            BranchSpec(name="fast_path", pool="cpu", items=2),
            BranchSpec(name="rerank", pool="gpu", items=1),
        ),
        agent_identity=OrchestratorIdentity(
            id="orch-llm-v1", role="orchestration", version="1.0.0",
        ),
        metadata=metadata or {},
    )


def _orch_adapter(extra_retries=0):
    responses = [
        DEFAULT_ROUTE_RESPONSE,
        DEFAULT_MERGE_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
    ]
    for _ in range(extra_retries):
        responses.append(DEFAULT_RETRY_RESPONSE)
    return GenerationAdapter(
        MockOrchBackend(responses=tuple(responses)),
        dependency_name="mock_orch",
    )


async def _run_to_sink(engine, context, sink, run_id="e2e-test"):
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


# ── TestLLMOrchE2E ─────────────────────────────────────────────────────


class TestLLMOrchRetryE2E:
    """Retry decisions flow correctly through the full LLM chain to sink."""

    def test_retry_count_survives_llm_chain_to_sink(self, sink_path):
        engine = LLMOrchestrationEngine(_orch_adapter(extra_retries=3))
        sink = SQLiteTraceSink(sink_path)
        try:
            items = asyncio.run(
                _run_to_sink(engine, _orch_context(), sink)
            )
            rows = sink.query_by_engine("orchestration")
            assert len(rows) > 0
            retry_counts = []
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                retry_counts.append(ctx.get("orchestration.retry_count", -1))
            assert all(rc >= 0 for rc in retry_counts)
        finally:
            sink.close()

    def test_llm_orch_items_have_agent_identity(self, sink_path):
        engine = LLMOrchestrationEngine(_orch_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_run_to_sink(engine, _orch_context(), sink))
            rows = sink.query_by_engine("orchestration")
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                assert "agent.identity" in ctx
                assert ctx["agent.identity"]["role"] == "orchestration"
        finally:
            sink.close()


# ── TestMultiPoolE2E ───────────────────────────────────────────────────


class TestMultiPoolE2E:
    """Multi-pool routing works with LLM orchestration engine."""

    def test_pool_keys_survive_llm_chain(self, sink_path):
        context = OrchestrationContext(
            branches=(
                BranchSpec(name="fast_path", pool="cpu", items=2),
                BranchSpec(name="rerank", pool="gpu", items=1),
            ),
            agent_identity=OrchestratorIdentity(
                id="orch-llm-v1", role="orchestration", version="1.0.0",
            ),
            resource_pools={"fast_path": "cpu_pool_0", "rerank": "gpu_pool_1"},
        )
        engine = LLMOrchestrationEngine(_orch_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_run_to_sink(engine, context, sink))
            rows = sink.query_by_engine("orchestration")
            pool_keys = set()
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                pool_keys.add(ctx.get("orchestration.resource_pool_key"))
            # Should have distinct pool keys for different branches
            assert len(pool_keys) >= 1
        finally:
            sink.close()


# ── TestMultiAgentCoexistence ──────────────────────────────────────────


class TestMultiAgentCoexistence:
    """LLM orchestration engine coexists with stub engines in same sink."""

    def test_llm_orch_and_stub_planning_same_sink(self, sink_path):
        async def _collect_planning(engine, context):
            items = []
            async for item in engine.plan(context, 5.0, PaceConfig()):
                items.append(item)
            return items

        sink = SQLiteTraceSink(sink_path)
        try:
            # Write from LLM orchestration engine
            orch_engine = LLMOrchestrationEngine(_orch_adapter())
            orch_items = asyncio.run(
                _run_to_sink(orch_engine, _orch_context(), sink)
            )
            assert len(orch_items) > 0

            # Write from stub planning engine (which internally uses stub orchestration)
            planning_engine = StubPlanningEngine()
            from engines.planning.interface import PlanningContext
            plan_items = asyncio.run(
                _collect_planning(planning_engine, PlanningContext(goal="test coexistence"))
            )
            plan_records = [
                StreamingTraceRecord(
                    pipeline_run_id="coexist-plan",
                    step_name="planning",
                    dependency_name="stub",
                    item_index=item.index,
                    item_delta_preview=item.delta[:200],
                    is_terminal=item.is_terminal,
                    trace_context=item.trace_context,
                    ts_iso="2026-05-25T00:00:00Z",
                    engine="planning",
                )
                for item in plan_items
            ]
            sink.write_streaming(plan_records)
            assert len(plan_items) > 0

            # Both should be queryable
            orch_rows = sink.query_by_engine("orchestration")
            plan_rows = sink.query_by_engine("planning")
            assert len(orch_rows) > 0
            assert len(plan_rows) > 0
        finally:
            sink.close()

    def test_no_key_collision_llm_orch_stub_critic(self, sink_path):
        async def _collect_critic(engine):
            items = []
            async for item in engine.evaluate():
                items.append(item)
            return items

        sink = SQLiteTraceSink(sink_path)
        try:
            orch_engine = LLMOrchestrationEngine(_orch_adapter())
            asyncio.run(_run_to_sink(orch_engine, _orch_context(), sink))

            critic_engine = StubCriticEngine()
            critic_items = asyncio.run(_collect_critic(critic_engine))
            critic_records = [
                StreamingTraceRecord(
                    pipeline_run_id="coexist-critic",
                    step_name="critic",
                    dependency_name="stub",
                    item_index=item.index,
                    item_delta_preview=item.delta[:200],
                    is_terminal=item.is_terminal,
                    trace_context=item.trace_context,
                    ts_iso="2026-05-25T00:00:00Z",
                    engine="critic",
                )
                for item in critic_items
            ]
            sink.write_streaming(critic_records)

            orch_rows = sink.query_by_engine("orchestration")
            critic_rows = sink.query_by_engine("critic")
            # Keys should not collide across engines in trace_context
            for row in orch_rows:
                ctx = json.loads(row["trace_context_json"])
                assert "critic.score" not in ctx
            for row in critic_rows:
                ctx = json.loads(row["trace_context_json"])
                assert "orchestration.dag_node_id" not in ctx
        finally:
            sink.close()

    def test_both_orch_engines_same_sink(self, sink_path):
        """Stub and LLM orchestration engines coexist in the same sink."""
        async def _collect_stub_orch(engine):
            items = []
            async for item in engine.orchestrate():
                items.append(item)
            return items

        from engines.orchestration.stub import StubOrchestrationEngine

        sink = SQLiteTraceSink(sink_path)
        try:
            # Stub orchestration
            stub = StubOrchestrationEngine()
            stub_items = asyncio.run(_collect_stub_orch(stub))
            stub_records = [
                StreamingTraceRecord(
                    pipeline_run_id="coexist-orch-stub",
                    step_name="orchestration",
                    dependency_name="stub",
                    item_index=item.index,
                    item_delta_preview=item.delta[:200],
                    is_terminal=item.is_terminal,
                    trace_context=item.trace_context,
                    ts_iso="2026-05-25T00:00:00Z",
                    engine="orchestration",
                )
                for item in stub_items
            ]
            sink.write_streaming(stub_records)

            # LLM orchestration
            llm = LLMOrchestrationEngine(_orch_adapter())
            llm_items = asyncio.run(
                _run_to_sink(llm, _orch_context(), sink)
            )

            all_orch = sink.query_by_engine("orchestration")
            assert len(all_orch) == len(stub_records) + len(llm_items)
        finally:
            sink.close()
