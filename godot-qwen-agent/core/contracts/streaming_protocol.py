"""Transport-agnostic cloud-native streaming protocol.

SerializationFormat converts StreamItem ↔ bytes.
TransportBackend handles network I/O (gRPC, Redis Streams, etc.).
PaceConfig controls throughput QoS (item_throughput, not token_rate).

All types are transport-agnostic — no gRPC/Redis/kafka imports here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Protocol


class SerializationFormat(Protocol):
    """Pluggable wire format — converts StreamItem ↔ bytes.

    JSON-RPC 2.0 is the default implementation. msgpack and protobuf
    are alternative backends for binary-efficient transport.
    """

    def serialize(self, item: "StreamItem") -> bytes:
        """Convert a StreamItem to wire-format bytes."""
        ...

    def deserialize(self, data: bytes) -> "StreamItem":
        """Convert wire-format bytes back to a StreamItem."""
        ...


class TransportBackend(Protocol):
    """Pluggable cloud-native transport backend.

    gRPC bidirectional streaming, Redis Streams, NATS, and Kafka
    are all valid implementations. The backend handles connection
    lifecycle, service discovery, and load balancing.
    """

    async def connect(self) -> None:
        """Establish connection to the transport."""
        ...

    async def send(self, data: bytes) -> None:
        """Send serialized bytes through the transport."""
        ...

    async def send_with_deadline(self, data: bytes, deadline: float) -> None:
        """Send with operation-level deadline (monotonic seconds).

        Phase 9.1: distinct from transport-level timeout. Planning engines
        use this for per-step deadlines (e.g. "single reasoning step ≤ 30s").
        Default implementation delegates to send() for backends that don't
        support native deadlines.
        """
        ...

    async def receive(self) -> AsyncIterator[bytes]:
        """Receive serialized bytes from the transport as an async iterator."""
        ...

    async def close(self) -> None:
        """Close the transport connection gracefully."""
        ...

    def health_check(self) -> bool:
        """Synchronous health probe. Returns True if transport is reachable."""
        ...


@dataclass(frozen=True)
class PaceConfig:
    """Streaming quality-of-service parameters.

    adaptive=True 时，backpressure_signal 返回值语义：
      0.0 = 下游完全空闲，可全速发送
      1.0 = 下游完全饱和，应暂停发送
      中间值 = 线性插值缩放 item_throughput

    信号采样频率由 PaceShapingWrapper 内部控制(建议每 burst_size
    个 item 采样一次)，避免高频 await 成为性能瓶颈。

    adaptive_strategy 为 Phase 9.1 扩展点——不同引擎注入不同 pacing
    语义，PaceShapingWrapper 根据策略名选择采样/调速行为。None 时
    使用默认线性缩放。具体策略语义由各引擎定义，不在此处硬编码。
    """

    item_throughput: Optional[float] = None
    burst_size: int = 0
    adaptive: bool = False
    # Phase 9.1: extension point for engine-specific pacing strategies.
    # None → default (backpressure_signal scales item_throughput linearly).
    # RAG: "backpressure" — downstream queue depth via backpressure_signal.
    # Planning: "jitter" — max acceptable inter-item timing variance.
    # The PaceShapingWrapper reads this to select its sampling/pacing behaviour;
    # actual strategy semantics are defined by each engine, not here.
    adaptive_strategy: Optional[str] = None

    def __post_init__(self) -> None:
        if self.item_throughput is not None and self.item_throughput < 0:
            raise ValueError(
                f"item_throughput must be >= 0, got {self.item_throughput}"
            )
        if self.burst_size < 0:
            raise ValueError(
                f"burst_size must be >= 0, got {self.burst_size}"
            )
