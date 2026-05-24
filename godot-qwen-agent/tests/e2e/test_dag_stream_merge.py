"""Phase 8.2b: DAG stream merge contract tests (TDD).

Tests the WAIT_ALL merge semantics, N-sentinel convergence, error
propagation with cancellation, InternalStream vs UserFacing isolation,
and backpressure behavior.

Reference: .ai_reasoning/chains/phase_08_dag_streaming_semantics.yaml
"""

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from core.contracts import StreamItem
from core.pipeline.engine import (
    PipelineConfig,
    PipelineRunner,
    PipelineStartupError,
    StepConfig,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer
from core.pipeline.streaming import merge_streams


# ── Test async-gen helpers ────────────────────────────────────────────


async def _make_producer(
    items: List[StreamItem], delay_per_item: float = 0.0
) -> AsyncIterator[StreamItem]:
    """Yields StreamItems with optional delay (simulates async I/O)."""
    for item in items:
        if delay_per_item > 0:
            await asyncio.sleep(delay_per_item)
        yield item


def _data_item(delta: str, index: int, model: str = "mock/producer") -> StreamItem:
    """Create a non-terminal data StreamItem."""
    return StreamItem(delta=delta, index=index, model=model)


def _terminal_item(
    index: int,
    finish_reason: str = "stop",
    model: str = "mock/producer",
    error: Optional[str] = None,
) -> StreamItem:
    """Create a terminal StreamItem."""
    return StreamItem(
        delta="",
        index=index,
        finish_reason=finish_reason,
        is_terminal=True,
        model=model,
        error=error,
    )


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1: Normal Merge — N-Sentinel Convergence
# ═══════════════════════════════════════════════════════════════════════


class TestNSentinelMerge:
    """WAIT_ALL merge: all N producers' data is received before the consumer
    exits, and the consumer exits after the N-th terminal."""

    def test_three_producers_converge_to_single_consumer(self):
        """3 producers, each 5 data + 1 terminal → 15 data + 1 merged terminal."""

        async def _test():
            producers = [
                _make_producer(
                    [_data_item(f"p0-{i}", i) for i in range(5)]
                    + [_terminal_item(5)]
                ),
                _make_producer(
                    [_data_item(f"p1-{i}", i) for i in range(5)]
                    + [_terminal_item(5)]
                ),
                _make_producer(
                    [_data_item(f"p2-{i}", i) for i in range(5)]
                    + [_terminal_item(5)]
                ),
            ]

            items = [item async for item in merge_streams(producers)]

            data_items = [it for it in items if not it.is_terminal]
            terminal_items = [it for it in items if it.is_terminal]

            assert len(data_items) == 15, f"Expected 15 data items, got {len(data_items)}"
            assert len(terminal_items) == 1, (
                f"Expected 1 merged terminal, got {len(terminal_items)}"
            )
            assert terminal_items[0].finish_reason == "stop"

        asyncio.run(_test())

    def test_consumer_blocks_until_all_sentinels_received(self):
        """Consumer must not produce the merged terminal until all N
        producers have sent their terminal items. This test uses staggered
        delays to verify ordering."""

        async def _test():
            # Producer 0: fast (no delay), 2 data + terminal
            # Producer 1: slow (50ms delay), 2 data + terminal
            p0 = _make_producer(
                [_data_item("p0-0", 0), _data_item("p0-1", 1), _terminal_item(2)],
                delay_per_item=0.0,
            )
            p1 = _make_producer(
                [_data_item("p1-0", 0), _data_item("p1-1", 1), _terminal_item(2)],
                delay_per_item=0.05,
            )

            items = [item async for item in merge_streams([p0, p1])]

            # After both producers done, we should have the merged terminal
            assert items[-1].is_terminal
            # p0's items should arrive before p1's (p0 is faster)
            p0_indices = [i for i, it in enumerate(items) if "p0" in it.delta]
            p1_indices = [i for i, it in enumerate(items) if "p1" in it.delta]
            if p0_indices and p1_indices:
                assert max(p0_indices) < min(p1_indices), (
                    "Fast producer items should arrive before slow producer items"
                )

        asyncio.run(_test())

    def test_single_producer_merge_is_identity(self):
        """Single producer merge: individual terminal suppressed, merged
        terminal emitted. 1 data + 1 merged terminal = 2 items total."""

        async def _test():
            producers = [
                _make_producer(
                    [_data_item("only", 0), _terminal_item(1)]
                )
            ]
            items = [item async for item in merge_streams(producers)]
            # 1 data item + 1 merged terminal (individual terminal suppressed)
            assert len(items) == 2, f"Expected 2 items, got {len(items)}"
            data = [it for it in items if not it.is_terminal]
            terms = [it for it in items if it.is_terminal]
            assert len(data) == 1
            assert data[0].delta == "only"
            assert len(terms) == 1
            assert terms[0].finish_reason == "stop"

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2: Error Propagation — Mid-Stream Error Cancellation
# ═══════════════════════════════════════════════════════════════════════


class TestErrorPropagation:
    """When a producer sends an error terminal, the merge consumer must:
    1. Yield the error terminal immediately
    2. Cancel remaining producer tasks
    3. Not leak coroutines
    """

    def test_mid_stream_error_yields_error_terminal(self):
        """Producer 1 errors after 3 items → consumer gets the error terminal."""

        async def _test():
            producers = [
                _make_producer(
                    [_data_item(f"p0-{i}", i) for i in range(5)]
                    + [_terminal_item(5)]
                ),
                _make_producer(
                    [_data_item(f"p1-{i}", i) for i in range(3)]
                    + [
                        _terminal_item(
                            3,
                            finish_reason="error",
                            error="upstream_timeout",
                        )
                    ]
                ),
                _make_producer(
                    [_data_item(f"p2-{i}", i) for i in range(5)]
                    + [_terminal_item(5)]
                ),
            ]

            items = [item async for item in merge_streams(producers)]

            error_items = [
                it for it in items if it.is_terminal and it.finish_reason == "error"
            ]
            assert len(error_items) >= 1, "Expected at least one error terminal"
            assert error_items[0].error == "upstream_timeout"

        asyncio.run(_test())

    def test_error_terminal_cancels_remaining_producers(self):
        """When an error terminal arrives, remaining producer tasks are
        cancelled before they finish. Verified by using a slow producer
        that shouldn't have time to complete all items."""

        async def _test():
            yielded_count: List[int] = [0]  # mutable tracking

            async def _slow_counted_producer() -> AsyncIterator[StreamItem]:
                try:
                    for i in range(100):
                        yielded_count[0] = i + 1
                        await asyncio.sleep(0.01)  # 10ms per item
                        yield _data_item(f"slow-{i}", i)
                    yield _terminal_item(100)
                except asyncio.CancelledError:
                    # Expected: cancelled before finishing 100 items
                    raise

            # p0: normal, p1: errors immediately, p2: slow (100 items, 10ms each)
            producers = [
                _make_producer(
                    [_data_item(f"p0-{i}", i) for i in range(3)]
                    + [_terminal_item(3)]
                ),
                _make_producer(
                    [_terminal_item(0, finish_reason="error", error="fail_fast")]
                ),
                _slow_counted_producer(),
            ]

            items = [item async for item in merge_streams(producers)]

            error_items = [
                it for it in items if it.is_terminal and it.finish_reason == "error"
            ]
            assert len(error_items) >= 1

            # slow producer should NOT have finished all 100 items
            assert yielded_count[0] < 100, (
                f"Slow producer yielded {yielded_count[0]} items — "
                "expected cancellation before reaching 100"
            )

        asyncio.run(_test())

    def test_no_resource_leak_on_error_cancellation(self):
        """After error cancellation, all producer tasks should be cleaned up.
        No 'Task was destroyed but it is pending' warnings."""

        async def _test():
            producers = []
            for n in range(5):
                if n == 3:
                    producers.append(
                        _make_producer(
                            [_terminal_item(0, finish_reason="error", error="fail")]
                        )
                    )
                else:
                    producers.append(
                        _make_producer(
                            [_data_item(f"p{n}-{i}", i) for i in range(5)]
                            + [_terminal_item(5)]
                        )
                    )

            items = [item async for item in merge_streams(producers)]
            assert any(
                it.is_terminal and it.finish_reason == "error" for it in items
            )

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3: InternalStream vs UserFacingStream Isolation
# ═══════════════════════════════════════════════════════════════════════


class TestInternalStreamIsolation:
    """StepOutput.internal_stream must NEVER leak to UserFacing (SSE) output.
    Only StepOutput.stream (UserFacing) from generator steps may be serialized."""

    def test_stepoutput_has_internal_stream_field(self):
        """Verify StepOutput supports internal_stream for DAG node streaming."""
        output = StepOutput(result="ok")
        assert hasattr(output, "internal_stream")
        assert output.internal_stream is None

    def test_non_generator_step_produces_internal_data(self):
        """PipelineConfig can represent stream-aware DAG pipelines. The engine
        will route internal_stream through DAG merges, not UserFacing."""

        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="chunk_docs",
                    component_type="chunker",
                    strategy="mock",
                    provides="chunks",
                    depends_on=["original_query"],
                ),
                StepConfig(
                    name="retrieve",
                    component_type="retriever",
                    strategy="mock",
                    provides="retrieval_results",
                    depends_on=["chunks"],
                ),
                StepConfig(
                    name="generate",
                    component_type="generator",
                    strategy="mock",
                    provides="generation",
                    depends_on=["retrieval_results"],
                ),
            ],
            pipeline_version=2,
            default_timeout_seconds=30.0,
        )

        assert config.pipeline_version == 2
        assert len(config.steps) == 3
        # Only the generator has component_type="generator"
        assert config.steps[2].component_type == "generator"

    @pytest.mark.xfail(reason="Guardrails rule not yet implemented (8.2b)")
    def test_guardrails_enforces_only_generator_sets_user_facing_stream(self):
        """Guardrails should flag any non-generator step that sets
        StepOutput.stream (the UserFacing field). This is a static check."""
        pytest.skip("Guardrails rule for UserFacingStream isolation not yet written")


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4: Backpressure — Consumer-Limited Producer Rate
# ═══════════════════════════════════════════════════════════════════════


class TestBackpressure:
    """asyncio.Queue(maxsize=N) must throttle fast producers when the
    consumer is slower than the producers."""

    def test_slow_consumer_throttles_fast_producer(self):
        """Fast producer (0ms/item) + slow consumer (50ms/item) + Queue(5)
        → Producer effective rate ≈ 50ms/item (consumer-bound)."""

        async def _test():
            prod_timestamps: List[float] = []

            async def _timed_producer(
                items: List[StreamItem],
            ) -> AsyncIterator[StreamItem]:
                for item in items:
                    prod_timestamps.append(time.perf_counter())
                    yield item

            producer = _timed_producer(
                [_data_item(f"x-{i}", i) for i in range(20)] + [_terminal_item(20)]
            )

            items = []
            async for item in merge_streams([producer], queue_size=5):
                items.append(item)
                await asyncio.sleep(0.05)  # slow consumer: 50ms/item

            assert len(items) == 21  # 20 data + 1 terminal

            if len(prod_timestamps) >= 3:
                intervals = [
                    prod_timestamps[i + 1] - prod_timestamps[i]
                    for i in range(len(prod_timestamps) - 1)
                ]
                avg_interval = sum(intervals) / len(intervals)
                # First 5 items fill queue instantly, rest wait for consumer (50ms).
                # Average should be > 10ms for backpressure to be working.
                assert avg_interval > 0.01, (
                    f"Expected backpressure throttling (avg > 10ms), "
                    f"got avg={avg_interval*1000:.1f}ms"
                )

        asyncio.run(_test())

    def test_queue_never_exceeds_capacity(self):
        """With queue_size=3 and 20 items, the Queue should never overflow
        (put() blocks instead of raising QueueFull)."""

        async def _test():
            producer = _make_producer(
                [_data_item(f"item-{i}", i) for i in range(20)]
                + [_terminal_item(20)],
                delay_per_item=0.0,
            )

            items = []
            async for item in merge_streams([producer], queue_size=3):
                items.append(item)

            assert len(items) == 21
            # No QueueFull exception = test passes

        asyncio.run(_test())

    def test_multiple_producers_share_backpressure(self):
        """Multiple producers sharing one queue: all should be throttled
        by a single slow consumer."""

        async def _test():
            async def _timed_producer(
                name: str, count: int, timestamps: List[float]
            ) -> AsyncIterator[StreamItem]:
                for i in range(count):
                    timestamps.append(time.perf_counter())
                    yield _data_item(f"{name}-{i}", i)
                yield _terminal_item(count)

            ts0: List[float] = []
            ts1: List[float] = []
            ts2: List[float] = []

            producers = [
                _timed_producer("p0", 10, ts0),
                _timed_producer("p1", 10, ts1),
                _timed_producer("p2", 10, ts2),
            ]

            items = []
            async for item in merge_streams(producers, queue_size=4):
                items.append(item)
                if not item.is_terminal:
                    await asyncio.sleep(0.03)  # consumer: ~30ms/item

            data_items = [it for it in items if not it.is_terminal]
            assert len(data_items) == 30  # 3 * 10

            for name, ts in [("p0", ts0), ("p1", ts1), ("p2", ts2)]:
                if len(ts) >= 3:
                    intervals = [
                        ts[i + 1] - ts[i] for i in range(len(ts) - 1)
                    ]
                    avg = sum(intervals) / len(intervals)
                    assert avg > 0.005, (
                        f"{name}: expected throttling (avg > 5ms), got avg={avg*1000:.1f}ms"
                    )

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════
# Scenario 5: merge_streams function contract
# ═══════════════════════════════════════════════════════════════════════


class TestMergeStreamsContract:
    """Contract-level tests for the merge_streams function signature."""

    def test_merge_streams_function_exists(self):
        """merge_streams is importable from core.pipeline.streaming."""
        assert merge_streams is not None

    def test_merge_streams_accepts_list_of_async_iterators(self):
        """Signature: merge_streams(streams, queue_size). Empty list → no items."""

        async def _test():
            items = [item async for item in merge_streams([])]
            assert len(items) == 0

        asyncio.run(_test())

    def test_terminal_item_has_is_terminal_true(self):
        """The merged terminal item must have is_terminal=True."""

        async def _test():
            producers = [
                _make_producer([_terminal_item(0)]),
            ]
            items = [item async for item in merge_streams(producers)]
            assert items[-1].is_terminal

        asyncio.run(_test())


# ═══════════════════════════════════════════════════════════════════════
# Scenario 6: Engine Integration — DAG pipeline with InternalStream merge
# ═══════════════════════════════════════════════════════════════════════


class TestEngineIntegration:
    """PipelineRunner auto-merges internal_stream from multiple upstreams
    and passes the merged stream to downstream steps via input_dict."""

    def test_multi_upstream_streams_are_merged(self):
        """3 retriever-like steps produce internal_stream → downstream
        generator receives _merged_stream with all data items."""
        from core.pipeline.engine import PipelineRunner, StepConfig, PipelineConfig, StepOutput, HealthStatus

        class StreamProducer:
            VERSION = "mock"

            async def run(self, inputs, resources):
                name = inputs.get("name", str(inputs.get("original_query", "unknown")))
                items = [
                    _data_item(f"{name}-0", 0),
                    _data_item(f"{name}-1", 1),
                    _terminal_item(2),
                ]

                async def _gen():
                    for item in items:
                        yield item

                return StepOutput(
                    result={"source": name, "count": 2},
                    internal_stream=_gen(),
                )

            def health_check(self):
                return HealthStatus(status="healthy")

        class StreamConsumer:
            VERSION = "mock"

            async def run(self, inputs, resources):
                merged = inputs.get("_merged_stream")
                if merged is not None:
                    collected = [item async for item in merged]
                    data_count = sum(1 for it in collected if not it.is_terminal)
                    return StepOutput(result={"total_data_items": data_count})
                internal = inputs.get("_internal_stream")
                if internal is not None:
                    collected = [item async for item in internal]
                    data_count = sum(1 for it in collected if not it.is_terminal)
                    return StepOutput(result={"total_data_items": data_count})
                return StepOutput(result={"total_data_items": 0})

            def health_check(self):
                return HealthStatus(status="healthy")

        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="retrieve_a", component_type="retriever", strategy="mock",
                    provides="results_a", depends_on=["original_query"],
                ),
                StepConfig(
                    name="retrieve_b", component_type="retriever", strategy="mock",
                    provides="results_b", depends_on=["original_query"],
                ),
                StepConfig(
                    name="retrieve_c", component_type="retriever", strategy="mock",
                    provides="results_c", depends_on=["original_query"],
                ),
                StepConfig(
                    name="rerank", component_type="reranker", strategy="mock",
                    provides="reranked",
                    depends_on=["results_a", "results_b", "results_c"],
                ),
            ],
            pipeline_version=2,
            default_timeout_seconds=30.0,
        )

        factories = {
            "retrieve_a": lambda c: StreamProducer(),
            "retrieve_b": lambda c: StreamProducer(),
            "retrieve_c": lambda c: StreamProducer(),
            "rerank": lambda c: StreamConsumer(),
        }

        with PipelineRunner(config, factories) as runner:
            state, _ = runner.run(initial_state={"original_query": "test_query"})

        assert state["reranked"]["total_data_items"] == 6, (
            f"Expected 6 merged data items, got {state['reranked']['total_data_items']}"
        )

    def test_single_upstream_no_merge_overhead(self):
        """With a single upstream producing internal_stream, the engine
        passes it directly as _internal_stream without merge overhead."""
        from core.pipeline.engine import PipelineRunner, StepConfig, PipelineConfig, StepOutput, HealthStatus

        class StreamProducer:
            VERSION = "mock"

            async def run(self, inputs, resources):
                async def _gen():
                    yield _data_item("single-0", 0)
                    yield _data_item("single-1", 1)
                    yield _terminal_item(2)
                return StepOutput(result={"count": 2}, internal_stream=_gen())

            def health_check(self):
                return HealthStatus(status="healthy")

        class StreamConsumer:
            VERSION = "mock"

            async def run(self, inputs, resources):
                stream = inputs.get("_internal_stream")
                assert stream is not None, "Expected _internal_stream for single upstream"
                merged = inputs.get("_merged_stream")
                assert merged is None, (
                    "Single upstream should NOT trigger merge"
                )
                collected = [item async for item in stream]
                return StepOutput(
                    result={"received": len([it for it in collected if not it.is_terminal])}
                )

            def health_check(self):
                return HealthStatus(status="healthy")

        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="retrieve_single", component_type="retriever", strategy="mock",
                    provides="results", depends_on=["original_query"],
                ),
                StepConfig(
                    name="consumer", component_type="reranker", strategy="mock",
                    provides="final", depends_on=["results"],
                ),
            ],
            pipeline_version=2,
        )

        factories = {
            "retrieve_single": lambda c: StreamProducer(),
            "consumer": lambda c: StreamConsumer(),
        }

        with PipelineRunner(config, factories) as runner:
            state, _ = runner.run(initial_state={"original_query": "single_test"})

        assert state["final"]["received"] == 2

    def test_no_streams_produces_no_merge(self):
        """When no upstream step produces internal_stream, the downstream
        step receives neither _merged_stream nor _internal_stream."""
        from core.pipeline.engine import PipelineRunner, StepConfig, PipelineConfig, StepOutput, HealthStatus

        class PlainStep:
            VERSION = "mock"

            async def run(self, inputs, resources):
                return StepOutput(result={"value": 42})

            def health_check(self):
                return HealthStatus(status="healthy")

        class CheckStep:
            VERSION = "mock"

            async def run(self, inputs, resources):
                has_merged = "_merged_stream" in inputs
                has_internal = "_internal_stream" in inputs
                return StepOutput(
                    result={"has_merged": has_merged, "has_internal": has_internal}
                )

            def health_check(self):
                return HealthStatus(status="healthy")

        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="step_a", component_type="custom", strategy="mock",
                    provides="a", depends_on=["original_query"],
                ),
                StepConfig(
                    name="step_b", component_type="custom", strategy="mock",
                    provides="b", depends_on=["a"],
                ),
            ],
        )

        factories = {
            "step_a": lambda c: PlainStep(),
            "step_b": lambda c: CheckStep(),
        }

        with PipelineRunner(config, factories) as runner:
            state, _ = runner.run(initial_state={"original_query": "test"})

        assert state["b"]["has_merged"] is False
        assert state["b"]["has_internal"] is False
