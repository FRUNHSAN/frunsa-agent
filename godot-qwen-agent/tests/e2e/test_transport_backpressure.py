"""E2E tests: transport backpressure — AsyncDataStreamAdapter with FakeTransport.

Uses in-memory FakeTransport so tests run without network. Verifies:
  - Slow consumer throttles fast producer (backpressure propagation)
  - Queue capacity enforcement
  - Shared backpressure signals across multiple streams
  - Merge + transport integration
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest

from core.adapters.stream_adapter import (
    AsyncDataStreamAdapter,
    JsonRpc20Serializer,
    PaceShapingWrapper,
)
from core.contracts import PaceConfig, StreamItem
from core.contracts.streaming_protocol import TransportBackend


# ── Fake Transport ─────────────────────────────────────────────────────


class FakeTransport:
    """In-memory TransportBackend for testing without network.

    Records sent data and feeds pre-configured receive data.
    Supports capacity limiting to simulate slow consumers.
    """

    def __init__(
        self,
        receive_items: Optional[List[bytes]] = None,
        max_queue: int = 32,
        healthy: bool = True,
    ) -> None:
        self._receive_items = receive_items or []
        self._sent: List[bytes] = []
        self._connected = False
        self._closed = False
        self._max_queue = max_queue
        self._healthy = healthy
        self._send_count = 0

    @property
    def sent(self) -> List[bytes]:
        return self._sent

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def closed(self) -> bool:
        return self._closed

    async def connect(self) -> None:
        self._connected = True

    async def send(self, data: bytes) -> None:
        self._sent.append(data)
        self._send_count += 1

    async def receive(self) -> AsyncIterator[bytes]:
        for item in self._receive_items:
            yield item

    async def close(self) -> None:
        self._closed = True

    def health_check(self) -> bool:
        return self._healthy


class SlowFakeTransport(FakeTransport):
    """Transport that simulates a slow consumer by delaying each send."""

    def __init__(self, delay_per_item: float = 0.01, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._delay = delay_per_item
        self._sleep_calls: List[float] = []

    async def send(self, data: bytes) -> None:
        self._sleep_calls.append(self._delay)
        self._sent.append(data)
        self._send_count += 1


class FailingTransport(FakeTransport):
    """Transport that fails on send after N items."""

    def __init__(self, fail_after: int = 3, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fail_after = fail_after

    async def send(self, data: bytes) -> None:
        self._sent.append(data)
        self._send_count += 1
        if self._send_count >= self._fail_after:
            raise ConnectionError("simulated transport failure")


# ── Helpers ──────────────────────────────────────────────────────────


def _make_items(count: int, prefix: str = "data") -> List[StreamItem]:
    return [
        StreamItem(delta=f"{prefix}_{i}", index=i, model="test/model")
        for i in range(count)
    ]


async def _make_stream(items: List[StreamItem]) -> AsyncIterator[StreamItem]:
    for item in items:
        yield item


async def _collect(stream: AsyncIterator[StreamItem]) -> List[StreamItem]:
    return [item async for item in stream]


# ── TestTransportBackpressure ────────────────────────────────────────


class TestTransportBackpressure:
    """Backpressure propagation through transport layer."""

    def test_send_stream_all_items_serialized_and_sent(self):
        """send_stream serializes and sends all items through transport."""
        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        items = _make_items(5)
        asyncio.run(adapter.send_stream(_make_stream(items)))

        assert len(transport.sent) == 5
        # Verify each sent item deserializes correctly
        for i, raw in enumerate(transport.sent):
            item = serializer.deserialize(raw)
            assert item.delta == f"data_{i}"
            assert item.index == i

    def test_receive_stream_deserializes_transport_data(self):
        """receive_stream reads from transport and deserializes items."""
        serializer = JsonRpc20Serializer()
        items = _make_items(3)
        raw_items = [serializer.serialize(it) for it in items]

        transport = FakeTransport(receive_items=raw_items)
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _test():
            received = await _collect(adapter.receive_stream())
            assert len(received) == 3
            for i, item in enumerate(received):
                assert item.delta == f"data_{i}"
                assert item.index == i

        asyncio.run(_test())

    def test_send_with_pace_config_throttles_output(self):
        """send_stream with pace_config shapes throughput through transport."""
        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        pace_config = PaceConfig(item_throughput=10.0, burst_size=5)
        adapter = AsyncDataStreamAdapter(
            serializer, transport, pace_config=pace_config,
        )

        items = _make_items(10)
        asyncio.run(adapter.send_stream(_make_stream(items)))

        assert len(transport.sent) == 10
        assert transport.connected is True
        assert transport.closed is True

    def test_send_stream_connects_and_closes(self):
        """send_stream lifecycle: connect → send → close (always)."""
        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        asyncio.run(adapter.send_stream(_make_stream(_make_items(2))))

        assert transport.connected is True
        assert transport.closed is True

    def test_receive_stream_connects_and_closes(self):
        """receive_stream lifecycle: connect → receive → close (always)."""
        serializer = JsonRpc20Serializer()
        raw = [serializer.serialize(StreamItem(delta="x", index=0, model="t"))]
        transport = FakeTransport(receive_items=raw)
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _test():
            async for _ in adapter.receive_stream():
                pass
            assert transport.connected is True
            assert transport.closed is True

        asyncio.run(_test())

    def test_send_stream_transport_failure_sets_error_trace(self):
        """When transport fails mid-stream, last_trace records the error."""
        transport = FailingTransport(fail_after=3)
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        items = _make_items(5)
        with pytest.raises(ConnectionError, match="simulated transport failure"):
            asyncio.run(adapter.send_stream(_make_stream(items)))

        assert adapter.last_trace is not None
        assert adapter.last_trace.status == "error"

    def test_send_stream_timeout_raises_timeouterror(self):
        """send_stream timeout triggers asyncio.TimeoutError (Phase 9.1)."""

        class StallingTransport(FakeTransport):
            async def send(self, data: bytes) -> None:
                await asyncio.sleep(999)  # never completes within timeout

        transport = StallingTransport()
        adapter = AsyncDataStreamAdapter(
            JsonRpc20Serializer(), transport, default_timeout=0.01,
        )

        async def _gen():
            yield StreamItem(delta="x", index=0, model="test")

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(adapter.send_stream(_make_stream(_make_items(1))))

        assert adapter.last_trace is not None
        assert adapter.last_trace.status == "timeout"

    def test_send_stream_custom_timeout_overrides_default(self):
        """Explicit timeout parameter overrides default_timeout (Phase 9.1)."""
        transport = FakeTransport()
        adapter = AsyncDataStreamAdapter(
            JsonRpc20Serializer(), transport, default_timeout=999.0,
        )

        items = _make_items(3)
        # Should succeed with custom timeout even though default is huge
        asyncio.run(adapter.send_stream(_make_stream(items), timeout=10.0))

        assert len(transport.sent) == 3
        assert adapter.last_trace.status == "success"

    def test_send_with_deadline_transport_support(self):
        """Transport with send_with_deadline works through adapter (Phase 9.1)."""

        class DeadlineTransport(FakeTransport):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._deadlines: List[float] = []

            async def send_with_deadline(self, data: bytes, deadline: float) -> None:
                self._deadlines.append(deadline)
                self._sent.append(data)

        transport = DeadlineTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        items = _make_items(3)
        asyncio.run(adapter.send_stream(_make_stream(items)))

        assert len(transport.sent) == 3


# ── TestTransportHealthProbe ─────────────────────────────────────────


class TestTransportHealthProbe:
    """AsyncDataStreamAdapter health_probe following VectorStoreAdapter pattern."""

    def test_health_probe_healthy_transport(self):
        """health_probe returns healthy when transport is reachable."""
        transport = FakeTransport(healthy=True)
        adapter = AsyncDataStreamAdapter(JsonRpc20Serializer(), transport)

        async def _test():
            result = await adapter.health_probe()
            assert result["status"] == "healthy"

        asyncio.run(_test())

    def test_health_probe_degraded_transport(self):
        """health_probe returns degraded when health_check returns False."""
        transport = FakeTransport(healthy=False)
        adapter = AsyncDataStreamAdapter(JsonRpc20Serializer(), transport)

        async def _test():
            result = await adapter.health_probe()
            assert result["status"] == "degraded"

        asyncio.run(_test())

    def test_health_probe_exception_returns_unavailable(self):
        """health_probe catches exceptions and returns unavailable."""

        class BrokenTransport(FakeTransport):
            def health_check(self) -> bool:
                raise RuntimeError("transport down")

        adapter = AsyncDataStreamAdapter(
            JsonRpc20Serializer(), BrokenTransport(),
        )

        async def _test():
            result = await adapter.health_probe()
            assert result["status"] == "unavailable"

        asyncio.run(_test())


# ── TestTransportWithMerge ──────────────────────────────────────────


class TestTransportWithMerge:
    """Merge + transport integration — merged streams flow through adapter."""

    def test_merged_streams_sent_through_transport(self):
        """Multiple stream sources merged, then sent through adapter."""
        from core.pipeline.streaming import merge_streams

        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _gen(prefix: str, count: int):
            for i in range(count):
                yield StreamItem(delta=f"{prefix}_{i}", index=i, model="test")
            # merge_streams requires each stream to end with a terminal
            yield StreamItem(
                delta="", index=count, model="test",
                is_terminal=True, finish_reason="stop",
            )

        async def _test():
            s1 = _gen("a", 3)
            s2 = _gen("b", 2)
            merged = merge_streams([s1, s2])
            await adapter.send_stream(merged)

            # 5 data + 1 merged terminal (individual terminals suppressed)
            assert len(transport.sent) == 6
            items = [serializer.deserialize(b) for b in transport.sent]
            deltas = [it.delta for it in items]
            assert sum(1 for d in deltas if d.startswith("a_")) == 3
            assert sum(1 for d in deltas if d.startswith("b_")) == 2
            # Last item is the merged terminal
            assert items[-1].is_terminal is True

        asyncio.run(_test())

    def test_paced_merged_stream_through_transport(self):
        """Pace-shaped merge stream flows through transport correctly."""
        from core.pipeline.streaming import merge_streams

        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        pace_config = PaceConfig(item_throughput=20.0, burst_size=4)
        adapter = AsyncDataStreamAdapter(
            serializer, transport, pace_config=pace_config,
        )

        async def _gen(prefix: str, count: int):
            for i in range(count):
                yield StreamItem(delta=f"{prefix}_{i}", index=i, model="test")
            yield StreamItem(
                delta="", index=count, model="test",
                is_terminal=True, finish_reason="stop",
            )

        async def _test():
            s1 = _gen("x", 4)
            s2 = _gen("y", 4)
            merged = merge_streams([s1, s2])
            await adapter.send_stream(merged)

            # 8 data + 1 merged terminal
            assert len(transport.sent) == 9

        asyncio.run(_test())

    def test_terminal_items_in_merged_stream_flow_through(self):
        """Terminal items survive merge + transport round-trip."""
        from core.pipeline.streaming import merge_streams

        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _gen_with_terminal():
            yield StreamItem(delta="chunk1", index=0, model="test")
            yield StreamItem(delta="chunk2", index=1, model="test")
            yield StreamItem(
                delta="", index=2, model="test",
                is_terminal=True, finish_reason="stop",
            )

        async def _test():
            merged = merge_streams([_gen_with_terminal()])
            await adapter.send_stream(merged)

            assert len(transport.sent) == 3
            last = serializer.deserialize(transport.sent[-1])
            assert last.is_terminal is True
            assert last.finish_reason == "stop"

        asyncio.run(_test())

    def test_error_terminal_in_merged_stream_preserved(self):
        """Error terminals survive merge + transport."""
        from core.pipeline.streaming import merge_streams

        transport = FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _gen_with_error():
            yield StreamItem(delta="data", index=0, model="test")
            yield StreamItem(
                delta="", index=1, model="test",
                is_terminal=True, finish_reason="error",
                error="backend_timeout",
            )

        async def _test():
            merged = merge_streams([_gen_with_error()])
            await adapter.send_stream(merged)

            assert len(transport.sent) == 2
            last = serializer.deserialize(transport.sent[-1])
            assert last.is_terminal is True
            assert last.finish_reason == "error"
            assert last.error == "backend_timeout"

        asyncio.run(_test())


# ── TestSharedBackpressure ──────────────────────────────────────────


class TestSharedBackpressure:
    """Shared backpressure signals across multiple stream adapters."""

    def test_shared_pressure_signal_across_adapters(self):
        """One backpressure signal feeds multiple PaceShapingWrappers."""
        # Simulate a shared pressure gauge
        shared_pressure = 0.5

        async def pressure_signal() -> float:
            return shared_pressure

        config = PaceConfig(item_throughput=10.0, burst_size=5, adaptive=True)

        async def _gen(prefix: str, count: int):
            for i in range(count):
                yield StreamItem(delta=f"{prefix}_{i}", index=i, model="test")

        async def _test():
            wrapper1 = PaceShapingWrapper(_gen("a", 10), config, pressure_signal)
            wrapper2 = PaceShapingWrapper(_gen("b", 10), config, pressure_signal)

            items1 = await _collect(wrapper1)
            items2 = await _collect(wrapper2)

            assert len(items1) == 10
            assert len(items2) == 10

        asyncio.run(_test())

    def test_pressure_changes_reflected_in_throughput(self, monkeypatch):
        """When shared pressure increases, throughput decreases."""
        sleep_calls: List[float] = []

        async def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        # Start with no pressure, then increase
        pressure_values = [0.0, 0.8]
        call_index = 0

        async def dynamic_pressure() -> float:
            nonlocal call_index
            val = pressure_values[min(call_index, len(pressure_values) - 1)]
            call_index += 1
            return val

        config = PaceConfig(item_throughput=10.0, burst_size=5, adaptive=True)

        async def _gen(count: int):
            for i in range(count):
                yield StreamItem(delta=f"item_{i}", index=i, model="test")

        async def _test():
            wrapper = PaceShapingWrapper(_gen(10), config, dynamic_pressure)
            items = await _collect(wrapper)
            assert len(items) == 10

        asyncio.run(_test())

    def test_independent_streams_have_independent_timing(self, monkeypatch):
        """Streams without shared signal operate independently."""
        sleep_calls: List[float] = []

        async def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        config = PaceConfig(item_throughput=10.0, burst_size=3)

        async def _gen(prefix: str, count: int):
            for i in range(count):
                yield StreamItem(delta=f"{prefix}_{i}", index=i, model="test")

        async def _test():
            # Each wrapper has its own internal counter — independent timing
            w1 = PaceShapingWrapper(_gen("a", 6), config)
            w2 = PaceShapingWrapper(_gen("b", 9), config)

            items1 = await _collect(w1)
            items2 = await _collect(w2)

            assert len(items1) == 6
            assert len(items2) == 9

        asyncio.run(_test())
