"""Redis Streams transport.

Production implementation requires:
- redis.asyncio client with connection pool
- Stream key naming convention (e.g., stream:{dependency_name}:{direction})
- Consumer group configuration for load-balanced consumption
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.contracts.streaming_protocol import TransportBackend


class RedisStreamsTransport(TransportBackend, ABC):
    """Redis Streams transport.

    Implements TransportBackend via redis.asyncio for async-native
    streaming over Redis Streams XADD/XREAD commands.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Initialize Redis connection pool and verify stream exists."""
        ...

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """XADD serialized bytes to the stream."""
        ...

    @abstractmethod
    async def send_with_deadline(self, data: bytes, deadline: float) -> None:
        """XADD with deadline (monotonic seconds).

        Redis Streams don't have native deadline semantics, so this
        should be implemented via asyncio.wait_for around XADD.
        """
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[bytes]:
        """XREAD from the stream, yielding deserialized items."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close Redis connection pool gracefully."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """PING Redis to verify connectivity."""
        ...
