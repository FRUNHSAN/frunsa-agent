"""Integration tests for LLMCriticEngine with SQLiteTraceSink.

Phase 18 Task 3: Validates key seeding, write/query, and metadata
pass-through from LLMCriticEngine to SQLite sink.
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


def _default_context():
    return CriticContext(
        plan_output="Goal: test. Steps: analyze, execute, verify.",
        agent_identity=CriticAgent(
            id="critic-v1", role="critic", version="1.0.0",
        ),
    )


def _default_adapter():
    return GenerationAdapter(
        MockCriticBackend(responses=(
            DEFAULT_DECOMPOSITION_RESPONSE,
            DEFAULT_DISPATCH_RESPONSE,
            DEFAULT_SYNTHESIS_RESPONSE,
        )),
        dependency_name="mock_critic",
    )


async def _collect_and_sink(engine, context, sink, run_id="int-test"):
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


# ── TestSinkKeySeeding ─────────────────────────────────────────────────


class TestSinkKeySeeding:
    """Critic keys are properly seeded in the sink."""

    def test_critic_keys_seeded(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            rows = sink._conn.execute(
                "SELECT key_name FROM trace_keys WHERE engine = ?", ("critic",)
            ).fetchall()
            keys = {r[0] for r in rows}
            assert "critic.score" in keys
            assert "critic.verdict" in keys
        finally:
            sink.close()

    def test_agent_identity_seeded_for_critic(self, sink_path):
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
    """LLM critic items can be written to and queried from sink."""

    def test_write_and_query_by_engine(self, sink_path):
        engine = LLMCriticEngine(_default_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_collect_and_sink(engine, _default_context(), sink))
            rows = sink.query_by_engine("critic")
            assert len(rows) == 3
        finally:
            sink.close()

    def test_critic_keys_in_sink_trace_context(self, sink_path):
        engine = LLMCriticEngine(_default_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            asyncio.run(_collect_and_sink(engine, _default_context(), sink))
            rows = sink.query_by_engine("critic")
            for row in rows:
                ctx = json.loads(row["trace_context_json"])
                assert "critic.score" in ctx
                assert "critic.verdict" in ctx
                assert "agent.identity" in ctx
        finally:
            sink.close()


# ── TestMetadataPassthrough ────────────────────────────────────────────


class TestMetadataPassthrough:
    """metadata slot survives sink write/query cycle."""

    def test_metadata_accepted(self, sink_path):
        ctx = CriticContext(
            plan_output="test",
            agent_identity=CriticAgent(
                id="c", role="critic", version="1.0.0",
            ),
            metadata={"evaluation_mode": "strict"},
        )
        engine = LLMCriticEngine(_default_adapter())
        sink = SQLiteTraceSink(sink_path)
        try:
            records = asyncio.run(_collect_and_sink(engine, ctx, sink))
            assert len(records) == 3
        finally:
            sink.close()
