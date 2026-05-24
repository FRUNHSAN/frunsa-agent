"""E2E tests: PaceShapingWrapper — throughput control with virtual clock.

Uses monkeypatch on asyncio.sleep to eliminate physical delay while
verifying timing logic correctness. Tests from milliseconds, not seconds.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, List

import pytest

from core.adapters.stream_adapter import PaceShapingWrapper
from core.contracts import PaceConfig, StreamItem


# ── Helpers ──────────────────────────────────────────────────────────

def _make_producer(items: List[str]) -> AsyncIterator[StreamItem]:
    """Create an async iterator that yields StreamItems instantly."""

    async def _gen() -> AsyncIterator[StreamItem]:
        for i, delta in enumerate(items):
            yield StreamItem(delta=delta, index=i, model="test/model")

    return _gen()


async def _collect(stream: AsyncIterator[StreamItem]) -> List[StreamItem]:
    return [item async for item in stream]


# ── Virtual clock fixture ────────────────────────────────────────────


@pytest.fixture
def mock_sleep(monkeypatch):
    """Replace asyncio.sleep with immediate return, recording call args.

    Eliminates physical delay — test time is hundreds of milliseconds,
    not seconds. Use sleep_calls for timing assertions.
    """
    sleep_calls: List[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return sleep_calls


# ── TestPaceShaping ──────────────────────────────────────────────────


class TestPaceShaping:
    """Throughput control correctness."""

    def test_unlimited_throughput_is_passthrough(self):
        """item_throughput=None means no throttling — all items pass through."""
        source = _make_producer(["a", "b", "c", "d", "e"])

        async def _test():
            config = PaceConfig(item_throughput=None)
            wrapper = PaceShapingWrapper(source, config)
            items = await _collect(wrapper)
            assert len(items) == 5
            assert [i.delta for i in items] == ["a", "b", "c", "d", "e"]

        asyncio.run(_test())

    def test_burst_batch_sleep(self, mock_sleep):
        """burst_size=5 with 10 items → exactly 2 sleep calls (batch, not per-item)."""
        source = _make_producer(["x"] * 10)

        async def _test():
            config = PaceConfig(item_throughput=10.0, burst_size=5)
            wrapper = PaceShapingWrapper(source, config)
            items = await _collect(wrapper)

            assert len(items) == 10
            # 10 items / burst_size 5 = 2 sleep calls
            assert len(mock_sleep) == 2
            # Each sleep should be ~ burst_size / item_throughput = 5/10 = 0.5s
            for d in mock_sleep:
                assert d >= 0.4  # allow small floating point tolerance

        asyncio.run(_test())

    def test_burst_zero_is_per_item(self, mock_sleep):
        """burst_size=0 → every item triggers one sleep."""
        source = _make_producer(["a", "b", "c"])

        async def _test():
            config = PaceConfig(item_throughput=5.0, burst_size=0)
            wrapper = PaceShapingWrapper(source, config)
            items = await _collect(wrapper)

            assert len(items) == 3
            # burst_size=0 → burst defaults to 1 → 3 calls
            assert len(mock_sleep) == 3

        asyncio.run(_test())

    def test_fixed_rate_enforces_minimum_duration(self, mock_sleep):
        """item_throughput=2.0 → 8 items with burst=4 → 2 batches, 2s each."""
        source = _make_producer(["x"] * 8)

        async def _test():
            config = PaceConfig(item_throughput=2.0, burst_size=4)
            wrapper = PaceShapingWrapper(source, config)
            items = await _collect(wrapper)

            assert len(items) == 8
            assert len(mock_sleep) == 2
            # 4 items / 2 per sec = 2.0s per batch
            assert all(d >= 1.9 for d in mock_sleep)

        asyncio.run(_test())

    def test_streamitem_integrity_after_throttling(self):
        """Pace shaping never modifies StreamItem data — only timing."""
        source = _make_producer(["alpha", "beta", "gamma"])

        async def _test():
            config = PaceConfig(item_throughput=100.0, burst_size=1)
            wrapper = PaceShapingWrapper(source, config)
            items = await _collect(wrapper)

            assert len(items) == 3
            assert items[0].delta == "alpha"
            assert items[0].index == 0
            assert items[1].delta == "beta"
            assert items[1].index == 1
            assert items[2].delta == "gamma"
            assert items[2].index == 2

        asyncio.run(_test())

    def test_terminal_item_still_passed_through(self):
        """Terminal items are not filtered by pace shaping."""

        async def _source():
            yield StreamItem(delta="data", index=0, model="test")
            yield StreamItem(delta="", index=1, is_terminal=True, finish_reason="stop", model="test")

        async def _test():
            config = PaceConfig(item_throughput=10.0, burst_size=1)
            wrapper = PaceShapingWrapper(_source(), config)
            items = await _collect(wrapper)

            assert len(items) == 2
            assert items[1].is_terminal is True

        asyncio.run(_test())


# ── TestAdaptivePace ─────────────────────────────────────────────────


class TestAdaptivePace:
    """Adaptive backpressure scaling."""

    def test_backpressure_signal_halves_throughput(self, mock_sleep):
        """pressure=0.5 → effective rate = 10 * (1-0.5) = 5 items/sec."""
        source = _make_producer(["x"] * 10)

        async def _test():
            async def pressure_signal() -> float:
                return 0.5

            config = PaceConfig(item_throughput=10.0, burst_size=5, adaptive=True)
            wrapper = PaceShapingWrapper(source, config, backpressure_signal=pressure_signal)
            items = await _collect(wrapper)

            assert len(items) == 10
            # With rate halved: 5 items/sec, burst=5 → sleep ~1.0s
            assert len(mock_sleep) == 2
            # At half rate: delay = 5/5 = 1.0s
            assert all(d >= 0.9 for d in mock_sleep)

        asyncio.run(_test())

    def test_full_backpressure_minimizes_throughput(self, mock_sleep):
        """pressure=1.0 → effective rate = 0 → no sleep (rate≈0 means skip)."""
        source = _make_producer(["x"] * 5)

        async def _test():
            async def pressure_signal() -> float:
                return 1.0

            config = PaceConfig(item_throughput=10.0, burst_size=5, adaptive=True)
            wrapper = PaceShapingWrapper(source, config, backpressure_signal=pressure_signal)
            items = await _collect(wrapper)

            assert len(items) == 5
            # rate=0 → should yield all items but skip sleeping
            # (current_rate == 0 → no sleep)

        asyncio.run(_test())

    def test_no_backpressure_full_speed(self, mock_sleep):
        """pressure=0.0 → effective rate = full item_throughput."""
        source = _make_producer(["x"] * 6)

        async def _test():
            async def pressure_signal() -> float:
                return 0.0

            config = PaceConfig(item_throughput=10.0, burst_size=3, adaptive=True)
            wrapper = PaceShapingWrapper(source, config, backpressure_signal=pressure_signal)
            items = await _collect(wrapper)

            assert len(items) == 6
            assert len(mock_sleep) == 2
            # Full rate: delay = 3/10 = 0.3s
            assert all(d >= 0.29 for d in mock_sleep)

        asyncio.run(_test())

    def test_signal_exception_falls_back_to_default_rate(self, mock_sleep):
        """If backpressure_signal raises, use default rate (fallback)."""
        source = _make_producer(["x"] * 6)

        async def _test():
            async def failing_signal() -> float:
                raise RuntimeError("metrics unavailable")

            config = PaceConfig(item_throughput=10.0, burst_size=3, adaptive=True)
            wrapper = PaceShapingWrapper(source, config, backpressure_signal=failing_signal)
            items = await _collect(wrapper)

            assert len(items) == 6
            # Should have slept with full rate (fallback)
            assert len(mock_sleep) == 2

        asyncio.run(_test())

    def test_pressure_clamped_to_range(self, mock_sleep):
        """Pressure values outside [0,1] are clamped."""
        source = _make_producer(["x"] * 5)

        async def _test():
            async def extreme_signal() -> float:
                return 2.5  # > 1.0, should clamp to 1.0

            config = PaceConfig(item_throughput=10.0, burst_size=5, adaptive=True)
            wrapper = PaceShapingWrapper(source, config, backpressure_signal=extreme_signal)
            items = await _collect(wrapper)

            assert len(items) == 5
            # pressure clamped to 1.0 → rate = 0 → no sleep

        asyncio.run(_test())


# ── TestPaceShapingStreamItemIntegrity ───────────────────────────────


class TestPaceShapingStreamItemIntegrity:
    """StreamItem data is NEVER modified by pace shaping — only timing changes."""

    def test_all_fields_preserved(self):
        """Every StreamItem field is identical after pace shaping."""
        original = StreamItem(
            delta="test data",
            index=42,
            finish_reason=None,
            model="gpt-4",
            is_terminal=False,
            error=None,
        )

        async def _source():
            yield original

        async def _test():
            config = PaceConfig(item_throughput=10.0, burst_size=1)
            wrapper = PaceShapingWrapper(_source(), config)
            items = await _collect(wrapper)

            assert len(items) == 1
            result = items[0]
            assert result.delta == original.delta
            assert result.index == original.index
            assert result.finish_reason == original.finish_reason
            assert result.model == original.model
            assert result.is_terminal == original.is_terminal
            assert result.error == original.error

        asyncio.run(_test())

    def test_trace_context_preserved(self):
        """trace_context opaque bag is passed through unmodified (Phase 9.1)."""
        ctx = {"chunk_id": "abc", "retrieval_latency_ms": 42}
        original = StreamItem(
            delta="data", index=0, model="test/rag", trace_context=ctx,
        )

        async def _source():
            yield original

        async def _test():
            config = PaceConfig(item_throughput=100.0, burst_size=1)
            wrapper = PaceShapingWrapper(_source(), config)
            items = await _collect(wrapper)

            assert items[0].trace_context == ctx

        asyncio.run(_test())


# ── TestPaceStreamConvenience ─────────────────────────────────────────


class TestPaceStreamConvenience:
    """pace_stream() pipeline convenience — with backpressure_signal (Phase 9.1)."""

    def test_pace_stream_with_backpressure_signal(self, mock_sleep):
        """pace_stream passes backpressure_signal through to PaceShapingWrapper."""
        from core.pipeline.streaming import pace_stream

        async def pressure_signal() -> float:
            return 0.5

        async def _gen():
            for i in range(10):
                yield StreamItem(delta=f"x{i}", index=i, model="test")

        async def _test():
            wrapper = pace_stream(
                _gen(),
                item_throughput=10.0,
                burst_size=5,
                adaptive=True,
                backpressure_signal=pressure_signal,
            )
            items = await _collect(wrapper)
            assert len(items) == 10
            # With pressure=0.5, effective rate = 5 items/sec, burst=5 → sleep ~1.0s
            assert len(mock_sleep) == 2
            assert all(d >= 0.9 for d in mock_sleep)

        asyncio.run(_test())

    def test_pace_stream_without_signal_still_works(self, mock_sleep):
        """pace_stream without backpressure_signal uses default rate."""
        from core.pipeline.streaming import pace_stream

        async def _gen():
            for i in range(6):
                yield StreamItem(delta=f"x{i}", index=i, model="test")

        async def _test():
            wrapper = pace_stream(_gen(), item_throughput=10.0, burst_size=3)
            items = await _collect(wrapper)
            assert len(items) == 6
            assert len(mock_sleep) == 2

        asyncio.run(_test())
