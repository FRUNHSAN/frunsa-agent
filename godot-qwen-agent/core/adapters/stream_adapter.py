"""Cloud-native streaming adapter: serialization, pace shaping, transport bridge.

Three classes:
  JsonRpc20Serializer — StreamItem ↔ JSON-RPC 2.0 bytes (4-state validation)
  PaceShapingWrapper — throughput-controlled async iterator wrapper
  AsyncDataStreamAdapter — bridges engine streams to cloud transport backends

All transport-specific logic confined to this layer. Engine core stays pure.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import (
    PaceConfig,
    SerializationFormat,
    TransportBackend,
)
from core.pipeline.tracing import DependencyCallTrace, SpanType


# ── JsonRpc20Serializer ──────────────────────────────────────────────


class JsonRpc20Serializer:
    """JSON-RPC 2.0 serializer: StreamItem ↔ bytes.

    Covers ALL 4 StreamItem state combinations:

      is_terminal=False, error=None  → method="stream.item"
      is_terminal=True,  error=None  → method="stream.finish"
      is_terminal=True,  error="..." → method="stream.error"
      is_terminal=False, error="..." → ValueError (illegal state)

    JSON-RPC 2.0 is chosen because its request/notification semantics
    map naturally to Agent tool-call patterns. The transport is gRPC/Redis
    (not stdio), giving cloud-native service discovery and load balancing.
    """

    JSONRPC_VERSION = "2.0"

    def serialize(self, item: StreamItem) -> bytes:
        """Convert StreamItem to JSON-RPC 2.0 bytes.

        Raises ValueError for illegal state (non-terminal with error).
        """
        if not item.is_terminal and item.error is not None:
            raise ValueError(
                f"Non-terminal item cannot carry error: "
                f"is_terminal={item.is_terminal}, error={item.error!r}"
            )

        if item.error is not None:
            method = "stream.error"
        elif item.is_terminal:
            method = "stream.finish"
        else:
            method = "stream.item"

        msg: Dict[str, Any] = {
            "jsonrpc": self.JSONRPC_VERSION,
            "method": method,
            "params": {
                "delta": item.delta,
                "index": item.index,
                "finish_reason": item.finish_reason,
                "model": item.model,
                "is_terminal": item.is_terminal,
            },
        }

        if item.error is not None:
            msg["params"]["error"] = item.error

        if item.finish_reason is not None:
            msg["params"]["finish_reason"] = item.finish_reason

        if item.trace_context is not None:
            msg["params"]["trace_context"] = item.trace_context

        msg["id"] = "terminal" if item.is_terminal else str(item.index)

        return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def deserialize(self, data: bytes) -> StreamItem:
        """Convert JSON-RPC 2.0 bytes back to StreamItem."""
        msg = json.loads(data.decode("utf-8"))
        params = msg.get("params", {})

        return StreamItem(
            delta=params.get("delta", ""),
            index=params.get("index", 0),
            finish_reason=params.get("finish_reason"),
            model=params.get("model", ""),
            is_terminal=params.get("is_terminal", False),
            error=params.get("error"),
            trace_context=params.get("trace_context"),
        )


# ── PaceShapingWrapper ────────────────────────────────────────────────


class PaceShapingWrapper:
    """Wrap an AsyncIterator[StreamItem] with throughput control.

    Does NOT modify StreamItem data — only alters timing between yields.
    This preserves the frozen dataclass invariant.

    InternalStream only — do NOT use for UserFacing streams.

    Parameters:
        source: The upstream async iterator to throttle.
        config: PaceConfig with item_throughput (items/sec), burst_size, adaptive.
        backpressure_signal: Optional callable returning 0.0-1.0
            (0=no pressure, 1=full backpressure). Used in adaptive mode
            to scale throughput dynamically. Sampled every burst_size items.
    """

    def __init__(
        self,
        source: AsyncIterator[StreamItem],
        config: PaceConfig,
        backpressure_signal: Optional[Callable[[], Awaitable[float]]] = None,
    ) -> None:
        self._source = source
        self._config = config
        self._backpressure_signal = backpressure_signal

    def __aiter__(self) -> AsyncIterator[StreamItem]:
        return self._throttled_iter()

    async def _throttled_iter(self) -> AsyncIterator[StreamItem]:
        """Yield items from source with throughput-controlled timing."""
        if self._config.item_throughput is None:
            async for item in self._source:
                yield item
            return

        rate = self._config.item_throughput
        burst = max(self._config.burst_size, 1)  # burst_size=0 → 逐 item
        items_since_sample = 0
        current_rate = rate

        async for item in self._source:
            yield item
            items_since_sample += 1

            if items_since_sample >= burst:
                if self._config.adaptive:
                    # Phase 10: route to engine-specific pacing strategy
                    if self._config.adaptive_strategy == "jitter":
                        raise NotImplementedError(
                            f"adaptive_strategy='jitter' recognized but not implemented; "
                            f"pace_config={self._config}"
                        )

                    if self._backpressure_signal is not None:
                        try:
                            pressure = await self._backpressure_signal()
                            pressure = max(0.0, min(1.0, pressure))
                            current_rate = rate * (1.0 - pressure)
                        except Exception:
                            current_rate = rate

                if current_rate > 0:
                    delay = burst / current_rate
                    await asyncio.sleep(delay)

                items_since_sample = 0


# ── AsyncDataStreamAdapter ────────────────────────────────────────────


class AsyncDataStreamAdapter:
    """Bridges engine streams to cloud-native transport backends.

    Serialization format (JSON-RPC, msgpack) and transport backend
    (gRPC, Redis Streams) are independently pluggable via constructor
    injection. The adapter handles the full lifecycle: connect, send,
    receive, close.

    Follows VectorStoreAdapter pattern: async wrapper with auto-tracing,
    health_probe(), and last_trace property.
    """

    def __init__(
        self,
        serializer: SerializationFormat,
        transport: TransportBackend,
        dependency_name: str = "cloud_transport",
        default_timeout: float = 120.0,
        pace_config: Optional[PaceConfig] = None,
    ) -> None:
        self._serializer = serializer
        self._transport = transport
        self._dependency_name = dependency_name
        self._default_timeout = default_timeout
        self._pace_config = pace_config
        self._last_trace: Optional[DependencyCallTrace] = None

    @property
    def last_trace(self) -> Optional[DependencyCallTrace]:
        return self._last_trace

    async def send_stream(
        self,
        stream: AsyncIterator[StreamItem],
        timeout: Optional[float] = None,
    ) -> None:
        """Serialize and send an entire stream through the transport.

        timeout: transport-level cap on the full send operation.
            Defaults to self._default_timeout. Use asyncio.wait_for
            internally so TimeoutError surfaces to the caller.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        t0 = time.perf_counter()

        async def _send_all():
            await self._transport.connect()

            if self._pace_config is not None:
                nonlocal stream
                stream = PaceShapingWrapper(stream, self._pace_config)

            last_ctx = None
            async for item in stream:
                last_ctx = item.trace_context
                data = self._serializer.serialize(item)
                await self._transport.send(data)

            return last_ctx

        try:
            last_ctx = await asyncio.wait_for(_send_all(), timeout=effective_timeout)

            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="success",
                trace_context=last_ctx,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="timeout",
                metadata={"timeout_s": effective_timeout},
                trace_context=None,
            )
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="error",
                metadata={"error": str(exc)},
                trace_context=None,
            )
            raise
        finally:
            await self._transport.close()

    async def receive_stream(
        self,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[StreamItem]:
        """Receive and deserialize a stream from the transport.

        timeout: max seconds to wait for the full receive stream.
            Defaults to self._default_timeout. Each individual receive
            call is capped by the remaining time budget.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        t0 = time.perf_counter()
        deadline = t0 + effective_timeout

        try:
            await self._transport.connect()

            last_ctx = None
            async with asyncio.timeout_at(deadline):
                async for data in self._transport.receive():
                    item = self._serializer.deserialize(data)
                    last_ctx = item.trace_context
                    yield item

            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="success",
                trace_context=last_ctx,
            )
        except asyncio.TimeoutError:
            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="timeout",
                metadata={"timeout_s": effective_timeout},
                trace_context=None,
            )
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            self._last_trace = DependencyCallTrace(
                dependency_name=self._dependency_name,
                span_type=SpanType.DEPENDENCY_CALL,
                duration_ms=elapsed * 1000,
                status="error",
                metadata={"error": str(exc)},
                trace_context=None,
            )
            raise
        finally:
            await self._transport.close()

    async def health_probe(self) -> Dict[str, Any]:
        """Health probe following VectorStoreAdapter pattern."""
        t0 = time.perf_counter()
        try:
            healthy = self._transport.health_check()
            elapsed = time.perf_counter() - t0
            return {
                "status": "healthy" if healthy else "degraded",
                "latency_ms": round(elapsed * 1000, 2),
                "message": "transport reachable" if healthy else "transport unreachable",
            }
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return {
                "status": "unavailable",
                "latency_ms": round(elapsed * 1000, 2),
                "message": str(exc),
            }
