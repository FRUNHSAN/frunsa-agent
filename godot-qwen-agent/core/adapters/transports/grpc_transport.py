"""gRPC Bidirectional Streaming transport.

Production implementation requires:
- protobuf schema definition in protos/stream.proto
- grpc.aio.insecure_channel / secure_channel setup
- Metadata-based dependency_name routing
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.contracts.streaming_protocol import TransportBackend


class GrpcBidiTransport(TransportBackend, ABC):
    """gRPC Bidirectional Streaming transport.

    Implements TransportBackend via grpc.aio for async-native streaming.
    JSON-RPC messages are sent as gRPC request/response payloads.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish gRPC channel and bidirectional stream."""
        ...

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """Write serialized bytes to the gRPC stream."""
        ...

    @abstractmethod
    async def send_with_deadline(self, data: bytes, deadline: float) -> None:
        """Write with operation-level deadline (monotonic seconds).

        gRPC natively supports per-RPC deadlines via grpc.aio.metadata
        with timeout. This maps to the underlying gRPC deadline mechanism
        rather than a Python-level asyncio.wait_for.
        """
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[bytes]:
        """Read serialized bytes from the gRPC stream."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the gRPC channel and stream gracefully."""
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """Check gRPC channel connectivity."""
        ...
