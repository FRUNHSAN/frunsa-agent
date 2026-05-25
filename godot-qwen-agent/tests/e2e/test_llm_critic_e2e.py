"""E2E tests for LLMCriticEngine — real engine full chain validation.

Phase 18 Task 3: Validates full chain to sink and multi-agent coexistence
with all other engines.
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
from engines.critic.identity import CriticAgent
from engines.critic.interface import CriticContext
from engines.critic.llm import (
    DEFAULT_DECOMPOSITION_RESPONSE,
    DEFAULT_DISPATCH_RESPONSE,
    DEFAULT_SYNTHESIS_RESPONSE,
    LLMCriticEngine,
    MockCriticBackend,
)
from engines.planning.stub import StubPlanningEngine


# ── Helpers ────────────────────────────────────────────────────────────


def _critic_context():
    return CriticContext(
        plan_output="Goal: test full chain. Sub-tasks: [A, B, C]. "
                     "Parallel branches: fast_path (3 items), full_rerank (2 items).",
        agent_identity=CriticAgent(
            id="critic-llm-v1", role="critic", version="1.0.0",
        ),
    )


def _critic_adapter():
    return GenerationAdapter(
        MockCriticBackend(responses=(
            DEFAULT_DECOMPOSITION_RESPONSE,
            DEFAULT_DISPATCH_RESPONSE,
            DEFAULT_SYNTHESIS_RESPONSE,
        )),
        dependency_name="mock_critic",
    )


async def _run_to_sink(engine, context, sink, run_id="e2e-test"):
    records = []
    async for item in engine.evaluate(context, 10.0, PaceConfig()):
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="critic",
            dependency_name="llm",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="critic",
        ))
    sink.write_streaming(records)
    return records


@pytest.fixture
def sink_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test.db")


# ── TestLLMCriticE2E ───────────────────────────────────────────────────


class TestLLMCriticE2E:
    """Full chain: LLM critic -> sink -> query."""

    def test_full_chain_critic_to_sink(self, sink_path):
        engine = LLMCriticEngine(_critic_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            records = asyncio.run(
                _run_to_sink(engine, _critic_context(), sink)
            )
            assert len(records) == 3
            rows = sink.query_by_engine("critic")
            assert len(rows) == 3
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                assert "critic.score" in ctx
                assert isinstance(ctx["critic.score"], float)
        finally:
            sink.close()

    def test_scores_queryable_in_sink(self, sink_path):
        engine = LLMCriticEngine(_critic_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_run_to_sink(engine, _critic_context(), sink))
            rows = sink.query_by_engine("critic")
            scores = [
                json.loads(row["trace_context_json"])["critic.score"]
                for row in rows
            ]
            assert scores == [0.85, 0.72, 0.90]
        finally:
            sink.close()


# ── TestMultiAgentCoexistence ──────────────────────────────────────────


class TestMultiAgentCoexistence:
    """LLM critic coexists with stub engines in same sink."""

    def test_llm_critic_and_stub_planning_same_sink(self, sink_path):
        async def _collect_planning(engine):
            items = []
            from engines.planning.interface import PlanningContext
            async for item in engine.plan(
                PlanningContext(goal="multi-agent test"),
                deadline=5.0,
                pace_config=PaceConfig(),
            ):
                items.append(item)
            return items

        sink = SQLiteTraceSink(sink_path)
        try:
            # LLM critic
            critic_engine = LLMCriticEngine(_critic_adapter())
            critic_records = asyncio.run(
                _run_to_sink(critic_engine, _critic_context(), sink, "e2e-critic")
            )
            assert len(critic_records) == 3

            # Stub planning
            planning_engine = StubPlanningEngine()
            plan_items = asyncio.run(_collect_planning(planning_engine))
            plan_records = [
                StreamingTraceRecord(
                    pipeline_run_id="e2e-plan",
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

            critic_rows = sink.query_by_engine("critic")
            plan_rows = sink.query_by_engine("planning")
            assert len(critic_rows) > 0
            assert len(plan_rows) > 0
        finally:
            sink.close()

    def test_llm_critic_and_llm_orch_same_sink(self, sink_path):
        from engines.orchestration.identity import OrchestratorIdentity
        from engines.orchestration.interface import BranchSpec, OrchestrationContext
        from engines.orchestration.llm import (
            DEFAULT_MERGE_RESPONSE,
            DEFAULT_RETRY_RESPONSE,
            DEFAULT_ROUTE_RESPONSE,
            LLMOrchestrationEngine,
            MockOrchBackend,
        )

        async def _collect_orch():
            records = []
            async for item in orch_engine.orchestrate(
                orch_context, 10.0, PaceConfig(),
            ):
                records.append(StreamingTraceRecord(
                    pipeline_run_id="e2e-orch",
                    step_name="orchestration",
                    dependency_name="llm",
                    item_index=item.index,
                    item_delta_preview=item.delta[:200],
                    is_terminal=item.is_terminal,
                    trace_context=item.trace_context,
                    ts_iso="2026-05-25T00:00:00Z",
                    engine="orchestration",
                ))
            return records

        sink = SQLiteTraceSink(sink_path)
        try:
            # LLM critic
            critic_engine = LLMCriticEngine(_critic_adapter())
            asyncio.run(
                _run_to_sink(critic_engine, _critic_context(), sink, "e2e-critic")
            )

            # LLM orchestration
            orch_adapter = GenerationAdapter(
                MockOrchBackend(responses=(
                    DEFAULT_ROUTE_RESPONSE,
                    DEFAULT_MERGE_RESPONSE,
                    DEFAULT_RETRY_RESPONSE,
                )),
                dependency_name="mock_orch",
            )
            orch_engine = LLMOrchestrationEngine(orch_adapter)
            orch_context = OrchestrationContext(
                branches=(
                    BranchSpec(name="fast", pool="cpu", items=2),
                    BranchSpec(name="rerank", pool="gpu", items=1),
                ),
                agent_identity=OrchestratorIdentity(
                    id="orch-v1", role="orchestration", version="1.0.0",
                ),
            )
            orch_records = asyncio.run(_collect_orch())
            sink.write_streaming(orch_records)

            critic_rows = sink.query_by_engine("critic")
            orch_rows = sink.query_by_engine("orchestration")
            assert len(critic_rows) > 0
            assert len(orch_rows) > 0
        finally:
            sink.close()

    def test_no_key_collision_critic_orch(self, sink_path):
        from engines.orchestration.stub import StubOrchestrationEngine

        async def _collect_orch(engine):
            items = []
            async for item in engine.orchestrate():
                items.append(item)
            return items

        sink = SQLiteTraceSink(sink_path)
        try:
            # LLM critic
            critic_engine = LLMCriticEngine(_critic_adapter())
            asyncio.run(
                _run_to_sink(critic_engine, _critic_context(), sink, "e2e-critic")
            )

            # Stub orchestration
            stub = StubOrchestrationEngine()
            stub_items = asyncio.run(_collect_orch(stub))
            stub_records = [
                StreamingTraceRecord(
                    pipeline_run_id="e2e-orch-stub",
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

            critic_rows = sink.query_by_engine("critic")
            orch_rows = sink.query_by_engine("orchestration")
            for row in critic_rows:
                ctx = json.loads(row["trace_context_json"])
                assert "orchestration.dag_node_id" not in ctx
            for row in orch_rows:
                ctx = json.loads(row["trace_context_json"])
                assert "critic.score" not in ctx
        finally:
            sink.close()
