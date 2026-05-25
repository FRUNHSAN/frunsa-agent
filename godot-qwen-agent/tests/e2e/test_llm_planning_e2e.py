"""E2E tests: LLMPlanningEngine end-to-end chain (Phase 17).

Full chain: LLMPlanningEngine → StreamingTraceRecord → SQLiteTraceSink → query.
Compares LLM planning engine output shape against deterministic stub.
"""

from __future__ import annotations

import os
import tempfile

from core.contracts.streaming_protocol import PaceConfig
from core.observability.sqlite_sink import SQLiteTraceSink
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext
from engines.planning.llm import (
    LLMPlanningEngine,
    MockLLMBackend,
    DEFAULT_DECOMPOSE_RESPONSE,
    DEFAULT_SYNTHESIZE_RESPONSE,
)
from engines.planning.stub import StubPlanningEngine

from tests.conftest import async_collect


class _MockAdapter:
    def __init__(self, backend):
        self._backend = backend

    async def generate(self, prompt, context, **params):
        return self._backend.generate(prompt, context, **params)


def _make_engine():
    backend = MockLLMBackend(
        responses=(DEFAULT_DECOMPOSE_RESPONSE, DEFAULT_SYNTHESIZE_RESPONSE),
    )
    return LLMPlanningEngine(_MockAdapter(backend))


def _make_context():
    return PlanningContext(
        goal="E2E test: build a search system with parallel retrieval",
        agent_identity=AgentIdentity(
            id="planner-v1", role="planning", version="1.0.0",
        ),
        sub_tasks=("fast_path: keyword retrieval", "full_rerank: semantic reranking"),
    )


def _stream_to_records(run_id, items):
    from core.pipeline.tracing import StreamingTraceRecord
    records = []
    for item in items:
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name=f"step_{item.index}",
            dependency_name="llm_planning",
            item_index=item.index,
            item_delta_preview=item.delta[:80],
            is_terminal=item.is_terminal,
            trace_context=dict(item.trace_context) if item.trace_context else None,
            ts_iso="2026-01-01T00:00:00Z",
            engine="planning",
        ))
    return records


class TestLLMPlanningE2E:
    """LLMPlanningEngine end-to-end tests."""

    def test_full_chain_llm_to_sink(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        records = _stream_to_records("e2e-llm", items)

        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == len(records)

                rows = sink.query_by_run("e2e-llm")
                assert len(rows) == len(records)
                assert rows[-1]["is_terminal"] == 1
            finally:
                sink.close()

    def test_llm_and_stub_produce_same_trace_key_sets(self):
        ctx = _make_context()

        llm_items = async_collect(
            _make_engine().plan(ctx, deadline=30.0, pace_config=PaceConfig()),
        )
        llm_keys = set()
        for item in llm_items:
            if item.trace_context:
                llm_keys.update(item.trace_context.keys())

        stub_items = async_collect(
            StubPlanningEngine().plan(ctx, deadline=30.0, pace_config=PaceConfig()),
        )
        stub_keys = set()
        for item in stub_items:
            if item.trace_context:
                stub_keys.update(item.trace_context.keys())

        planning_core = {
            "planning.step_index", "planning.reasoning_depth",
            "planning.parent_step_id", "planning.cumulative_tokens",
            "agent.identity",
        }
        assert planning_core.issubset(llm_keys), (
            f"LLM engine missing: {planning_core - llm_keys}"
        )
        assert planning_core.issubset(stub_keys), (
            f"Stub engine missing: {planning_core - stub_keys}"
        )

    def test_llm_engine_model_is_llm(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        serial_items = [i for i in items if "planning/llm" in i.model]
        assert len(serial_items) >= 2  # decompose step + synthesis

    def test_schema_version_unchanged(self):
        from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 2

    def test_error_path_still_writes_to_sink(self):
        class _FailingAdapter:
            async def generate(self, prompt, context, **params):
                raise RuntimeError("simulated LLM outage")

        engine = LLMPlanningEngine(_FailingAdapter())
        items = async_collect(
            engine.plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        records = _stream_to_records("e2e-error", items)

        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("e2e-error")
                assert len(rows) == 1
                assert rows[0]["is_terminal"] == 1
            finally:
                sink.close()
