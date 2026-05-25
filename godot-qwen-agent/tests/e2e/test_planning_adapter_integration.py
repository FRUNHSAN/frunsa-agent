"""TDD tests: Planning engine adapter integration (Phase 10).

Three test classes validating that Phase 9/9.1 adapter extension points
work correctly with a second engine type (Planning). These tests are
written BEFORE the Planning stub — they should FAIL until Step 3.

Tests validate channel behavior (trace_context passthrough, strategy
routing, deadline timeout), NOT engine semantics (reasoning quality).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Dict, List, Optional

import pytest

from core.adapters.stream_adapter import (
    AsyncDataStreamAdapter,
    JsonRpc20Serializer,
    PaceShapingWrapper,
)
from core.contracts import PaceConfig, StreamItem


# ── Helpers ──────────────────────────────────────────────────────────


def _planning_item(
    delta: str,
    index: int,
    step_index: int = 0,
    reasoning_depth: int = 0,
    parent_step_id: Optional[str] = None,
    is_terminal: bool = False,
) -> StreamItem:
    """Create a StreamItem with Planning trace_context keys."""
    return StreamItem(
        delta=delta,
        index=index,
        model="planning/stub",
        is_terminal=is_terminal,
        finish_reason="stop" if is_terminal else None,
        trace_context={
            "planning.step_index": step_index,
            "planning.reasoning_depth": reasoning_depth,
            "planning.parent_step_id": parent_step_id,
            "planning.cumulative_tokens": len(delta),
        },
    )


def _rag_item(
    delta: str,
    index: int,
    chunk_id: str = "chunk_001",
    retrieval_latency_ms: int = 42,
) -> StreamItem:
    """Create a StreamItem with RAG trace_context keys."""
    return StreamItem(
        delta=delta,
        index=index,
        model="rag/generator",
        trace_context={
            "rag.chunk_id": chunk_id,
            "rag.retrieval_latency_ms": retrieval_latency_ms,
        },
    )


def _mixed_item() -> StreamItem:
    """Create a StreamItem with both Planning and RAG trace_context keys."""
    return StreamItem(
        delta="mixed content",
        index=0,
        model="test/merged",
        trace_context={
            "planning.step_index": 1,
            "planning.reasoning_depth": 2,
            "rag.chunk_id": "chunk_042",
            "rag.retrieval_latency_ms": 15,
        },
    )


async def _collect(stream: AsyncIterator[StreamItem]) -> List[StreamItem]:
    return [item async for item in stream]


# ── TestTraceContextNamespaceIsolation ───────────────────────────────


class TestTraceContextNamespaceIsolation:
    """trace_context opaque Dict preserves per-engine key namespaces.

    Phase 9.1 added trace_context as an Optional[Dict[str, Any]].
    Each engine uses a dot-separated prefix (planning.*, rag.*).
    The adapter must pass all keys through without inspection or collision.
    """

    def test_planning_keys_survive_round_trip(self):
        """Planning trace_context keys survive serialize → deserialize intact."""
        serializer = JsonRpc20Serializer()
        original = _planning_item("decompose goal", index=0, step_index=0, reasoning_depth=0)
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.trace_context is not None
        assert deserialized.trace_context["planning.step_index"] == 0
        assert deserialized.trace_context["planning.reasoning_depth"] == 0
        assert deserialized.trace_context["planning.parent_step_id"] is None
        assert deserialized.trace_context["planning.cumulative_tokens"] == len("decompose goal")

    def test_planning_keys_with_parent_step_survive_round_trip(self):
        """Non-None parent_step_id also round-trips correctly."""
        serializer = JsonRpc20Serializer()
        original = _planning_item(
            "sub-conclusion", index=2, step_index=2,
            reasoning_depth=1, parent_step_id="step-1",
        )
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.trace_context is not None
        assert deserialized.trace_context["planning.parent_step_id"] == "step-1"
        assert deserialized.trace_context["planning.reasoning_depth"] == 1

    def test_planning_keys_dont_conflict_with_rag_keys(self):
        """Planning.* and rag.* keys coexist without overwrite in one StreamItem."""
        serializer = JsonRpc20Serializer()
        original = _mixed_item()
        deserialized = serializer.deserialize(serializer.serialize(original))

        ctx = deserialized.trace_context
        assert ctx is not None
        # Planning keys preserved
        assert ctx["planning.step_index"] == 1
        assert ctx["planning.reasoning_depth"] == 2
        # RAG keys preserved (no conflict)
        assert ctx["rag.chunk_id"] == "chunk_042"
        assert ctx["rag.retrieval_latency_ms"] == 15
        # Both namespaces present
        planning_keys = {k for k in ctx if k.startswith("planning.")}
        rag_keys = {k for k in ctx if k.startswith("rag.")}
        assert len(planning_keys) == 2
        assert len(rag_keys) == 2

    def test_no_cross_engine_key_leakage(self):
        """Serializing a Planning item doesn't inject rag.* keys and vice versa."""
        serializer = JsonRpc20Serializer()

        planning_item = _planning_item("think", 0)
        planning_serialized = serializer.deserialize(serializer.serialize(planning_item))
        planning_keys = list(planning_serialized.trace_context.keys()) if planning_serialized.trace_context else []
        assert not any(k.startswith("rag.") for k in planning_keys)

        rag_item = _rag_item("retrieved text", 0)
        rag_serialized = serializer.deserialize(serializer.serialize(rag_item))
        rag_keys = list(rag_serialized.trace_context.keys()) if rag_serialized.trace_context else []
        assert not any(k.startswith("planning.") for k in rag_keys)

    def test_bare_key_awareness(self):
        """Meta-test: verify guardrail trace_context_namespace detects bare keys.

        This is NOT a runtime test — it documents the expectation that
        trace_context keys without '.' separator will be flagged by the
        trace_context_namespace guardrail (WARNING level).

        The guardrail will be verified separately via `python -m guardrails check`.
        This test exists to ensure the guardrail test suite covers bare key detection.
        """
        # A bare key without engine prefix — this SHOULD be flagged by guardrail
        item_with_bare_key = StreamItem(
            delta="test", index=0, model="test",
            trace_context={"step": 1},  # bare key, no '.' separator
        )
        serializer = JsonRpc20Serializer()
        deserialized = serializer.deserialize(serializer.serialize(item_with_bare_key))

        # Runtime: the key survives round-trip (adapter is blind to semantics)
        assert deserialized.trace_context == {"step": 1}
        # Guardrail: trace_context_namespace should flag this at WARNING level
        # Verified by: `python -m guardrails check --all`


# ── TestAdaptiveStrategyJitterRouting ────────────────────────────────


class TestAdaptiveStrategyJitterRouting:
    """PaceConfig.adaptive_strategy="jitter" is recognized and routed.

    Phase 9.1 added adaptive_strategy as an extension point. Phase 10
    verifies that the PaceShapingWrapper routes "jitter" to the correct
    strategy branch. The branch raises NotImplementedError — proving
    routing works without implementing jitter semantics prematurely.
    """

    def test_jitter_strategy_recognized(self):
        """adaptive_strategy='jitter' → NotImplementedError (routing confirmed)."""
        config = PaceConfig(
            item_throughput=10.0,
            burst_size=5,
            adaptive=True,
            adaptive_strategy="jitter",
        )

        async def _gen():
            for i in range(10):
                yield StreamItem(delta=f"step_{i}", index=i, model="planning/stub")

        async def _test():
            wrapper = PaceShapingWrapper(_gen(), config)
            with pytest.raises(NotImplementedError, match="jitter"):
                await _collect(wrapper)

        asyncio.run(_test())

    def test_jitter_strategy_error_context(self):
        """NotImplementedError carries engine context for debugging (Phase 10 review feedback)."""
        config = PaceConfig(
            item_throughput=10.0,
            burst_size=3,
            adaptive=True,
            adaptive_strategy="jitter",
        )

        async def _gen():
            for i in range(6):
                yield StreamItem(delta=f"step_{i}", index=i, model="planning/stub")

        async def _test():
            wrapper = PaceShapingWrapper(_gen(), config)
            with pytest.raises(NotImplementedError) as exc_info:
                await _collect(wrapper)
            # Error message should contain the strategy name for grep-ability
            assert "jitter" in str(exc_info.value)

        asyncio.run(_test())

    def test_null_strategy_uses_default_linear(self, monkeypatch):
        """adaptive_strategy=None (default) → standard linear scaling (no error)."""
        sleep_calls: List[float] = []

        async def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        config = PaceConfig(
            item_throughput=10.0,
            burst_size=5,
            adaptive=True,
            adaptive_strategy=None,  # default
        )

        async def _gen():
            for i in range(10):
                yield StreamItem(delta=f"step_{i}", index=i, model="planning/stub")

        async def _test():
            wrapper = PaceShapingWrapper(_gen(), config)
            items = await _collect(wrapper)
            assert len(items) == 10
            assert len(sleep_calls) == 2  # normal burst behavior

        asyncio.run(_test())


# ── TestDeadlineTimeout ──────────────────────────────────────────────


class TestDeadlineTimeout:
    """Planning engine respects operation-level deadline.

    Phase 9.1 added send_with_deadline to TransportBackend. Phase 10
    verifies that a Planning engine stub checks its deadline parameter
    and raises asyncio.TimeoutError when exceeded, with the adapter
    recording status="timeout" in last_trace.
    """

    def test_planning_deadline_triggers_timeout(self):
        """Stub with expired deadline raises TimeoutError through adapter."""
        from engines.planning.stub import StubPlanningEngine

        transport = _FakeDeadlineTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport, default_timeout=10.0)

        engine = StubPlanningEngine()
        pace_config = PaceConfig(adaptive_strategy="jitter")

        async def _test():
            from engines.planning.identity import AgentIdentity
            from engines.planning.interface import PlanningContext
            ctx = PlanningContext(
                goal="test goal",
                agent_identity=AgentIdentity(id="test", role="test", version="1.0.0"),
            )
            stream = engine.plan(
                context=ctx,
                deadline=0.0,  # expired immediately — stub uses perf_counter (μs resolution)
                pace_config=pace_config,
            )
            with pytest.raises(asyncio.TimeoutError):
                await adapter.send_stream(stream)

            assert adapter.last_trace is not None
            assert adapter.last_trace.status == "timeout"

        asyncio.run(_test())

    def test_planning_with_sufficient_deadline_completes(self):
        """Stub with generous deadline completes all steps successfully."""
        from engines.planning.stub import StubPlanningEngine

        transport = _FakeDeadlineTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        engine = StubPlanningEngine()
        pace_config = PaceConfig(adaptive_strategy="jitter")

        async def _test():
            from engines.planning.identity import AgentIdentity
            from engines.planning.interface import PlanningContext
            ctx = PlanningContext(
                goal="test goal",
                agent_identity=AgentIdentity(id="test", role="test", version="1.0.0"),
            )
            stream = engine.plan(
                context=ctx,
                deadline=60.0,  # generous
                pace_config=pace_config,
            )
            await adapter.send_stream(stream)

            assert len(transport.sent) == 8  # 8 items (2 serial + 5 orchestration + 1 terminal)
            assert adapter.last_trace is not None
            assert adapter.last_trace.status == "success"

            # Verify trace_context on the last item
            last = serializer.deserialize(transport.sent[-1])
            assert last.trace_context is not None
            assert last.is_terminal is True

        asyncio.run(_test())


# ── Fake Transport for deadline tests ────────────────────────────────


class _FakeDeadlineTransport:
    """In-memory transport that records sent data for deadline test assertions."""

    def __init__(self) -> None:
        self._sent: List[bytes] = []
        self._connected = False
        self._closed = False

    @property
    def sent(self) -> List[bytes]:
        return self._sent

    async def connect(self) -> None:
        self._connected = True

    async def send(self, data: bytes) -> None:
        self._sent.append(data)

    async def receive(self) -> AsyncIterator[bytes]:
        for item in self._sent:
            yield item

    async def close(self) -> None:
        self._closed = True

    def health_check(self) -> bool:
        return True
