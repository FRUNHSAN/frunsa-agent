"""Integration tests: LLMPlanningEngine + SQLiteTraceSink (Phase 17).

Verify LLMPlanningEngine trace data survives the full sink write → query cycle.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from core.contracts.streaming_protocol import PaceConfig
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext
from engines.planning.llm import (
    LLMPlanningEngine,
    MockLLMBackend,
    DEFAULT_DECOMPOSE_RESPONSE,
    DEFAULT_SYNTHESIZE_RESPONSE,
)

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
        goal="Integration test: build a search system",
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


class TestLLMPlanningSinkIntegration:
    """LLMPlanningEngine → SQLiteTraceSink integration."""

    def test_llm_trace_written_to_sink(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        records = _stream_to_records("run-llm-1", items)

        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count > 0

                rows = sink.query_by_run("run-llm-1")
                assert len(rows) > 0
                assert any(r["engine"] == "planning" for r in rows)
            finally:
                sink.close()

    def test_agent_identity_present_in_all_records(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        records = _stream_to_records("run-llm-2", items)

        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("run-llm-2")
                for row in rows:
                    ctx_json = row.get("trace_context_json")
                    assert ctx_json is not None, (
                        f"No trace_context_json for item {row['item_index']}"
                    )
                    import json
                    ctx = json.loads(ctx_json)
                    assert "agent.identity" in ctx, (
                        f"Missing agent.identity in item {row['item_index']}"
                    )
            finally:
                sink.close()

    def test_terminal_item_present(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(), deadline=30.0, pace_config=PaceConfig(),
            )
        )
        records = _stream_to_records("run-llm-3", items)

        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                sink.write_streaming(records)
                rows = sink.query_by_run("run-llm-3")
                terminal_rows = [r for r in rows if r["is_terminal"]]
                assert len(terminal_rows) == 1
            finally:
                sink.close()

    def test_key_count_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink_path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(sink_path)
            try:
                all_keys = sink.query_keys()
                from core.contracts.trace_keys import COMPONENT_TRACE_KEYS
                expected = len(TRACE_KEY_REGISTRY) + len(COMPONENT_TRACE_KEYS)
                assert len(all_keys) == expected
            finally:
                sink.close()
