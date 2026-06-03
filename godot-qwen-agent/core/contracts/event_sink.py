"""EventSink Protocol — Phase 25 anti-corruption layer.

Defines the contract for event emission and query.
Business code depends ONLY on this Protocol, never on
ContractAwareEventSink (the concrete in-memory implementation).

Swap to Redis Streams, Kafka, or a cloud event bus by writing
a new class that satisfies this Protocol. Zero changes to
health_evaluator, repair_engine, or hitl_gateway.

Design:
  - __call__ is the write path — business logic "emits" events
  - Query methods are read path — consumers inspect history
  - No subscribe/observer — YAGNI for MVP
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventSink(Protocol):
    """Contract for event emission and query.

    Implementations: ContractAwareEventSink (in-memory, current),
    RedisEventSink (future), KafkaEventSink (future).
    """

    # ── Write ──────────────────────────────────────────────────

    def __call__(self, event: Any) -> None:
        """Emit a CompositionEvent into the sink."""
        ...

    # ── Read (used by evaluator + repair + hitl) ───────────────

    @property
    def violations(self) -> list[Any]:
        """Events with contract_violation != None."""
        ...

    def by_type(self, event_type: str) -> list[Any]:
        """Filter events by event_type string."""
        ...

    @property
    def summary(self) -> dict[str, Any]:
        """JSON-safe summary dict for audit/display."""
        ...

    def __len__(self) -> int:
        """Total event count."""
        ...
