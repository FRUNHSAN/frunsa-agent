"""Contract-Aware Event Sink — structured storage for CompositionEvents.

Phase 19 defined event_sink as a Callable[[CompositionEvent], None] injection point.
Phase 19.5 gives it a spine: structured storage, query, and contract violation awareness.

This is the first "nerve" of the relationship layer. Every event that flows through
this sink carries the DNA for future contract health assessment (Phase 25+).

Design invariants:
  - Callable interface — drop-in replacement for any event_sink parameter
  - Thread-safe append (for future async engines, not needed today but costless)
  - Query by correlation_id (cross-event tracing for a single document)
  - Query by event_type (filter rule_matched / document_failed / etc.)
  - Violation extraction — surface events that indicate breached contracts
  - Zero logging framework coupling — engines never import logging
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from core.contracts.composition import AssemblyDiagnostic, CompositionEvent
from core.contracts.event_sink import EventSink


class ContractAwareEventSink(EventSink):
    """Structured in-memory sink for CompositionEvents.

    Callable — drop it in wherever event_sink is expected.
    Queryable — ask it what happened, per document, per violation, per rule.

    Lifecycle:
      sink = ContractAwareEventSink()
      router = SourceRouter(blueprint, event_sink=sink)
      assembler = PipelineAssembler(event_sink=sink)
      # ... composition runs, events flow into sink ...
      sink.violations  # → events with contract_violation context
      sink.by_correlation("abc123")  # → all events for that document
    """

    def __init__(self) -> None:
        self._events: List[CompositionEvent] = []
        self._lock = threading.Lock()

    # ── Callable interface (drop-in event_sink) ─────────────────

    def __call__(self, event: CompositionEvent) -> None:
        """Receive a CompositionEvent. Thread-safe append."""
        with self._lock:
            self._events.append(event)

    # ── Query ───────────────────────────────────────────────────

    @property
    def events(self) -> List[CompositionEvent]:
        """All recorded events, in arrival order."""
        with self._lock:
            return list(self._events)

    def by_correlation(self, correlation_id: str) -> List[CompositionEvent]:
        """All events for a single document (same correlation_id)."""
        with self._lock:
            return [e for e in self._events if e.correlation_id == correlation_id]

    def by_type(self, event_type: str) -> List[CompositionEvent]:
        """Filter by event_type (rule_matched, document_failed, etc.)."""
        with self._lock:
            return [e for e in self._events if e.event_type == event_type]

    # ── Violation awareness (Phase 19.5) ───────────────────────

    @property
    def violations(self) -> List[CompositionEvent]:
        """Events that carry contract violation indicators.

        A CompositionEvent indicates a contract violation when its context
        contains 'contract_violation' with a non-None value. This is set by
        PipelineAssembler._record_failure when it classifies the failure.
        """
        with self._lock:
            return [
                e for e in self._events
                if e.context.get("contract_violation") is not None
            ]

    @property
    def violation_count(self) -> int:
        """Number of contract violation events."""
        return len(self.violations)

    def violations_by_type(self) -> Dict[str, List[CompositionEvent]]:
        """Group violations by their contract_violation category."""
        result: Dict[str, List[CompositionEvent]] = {}
        for e in self.violations:
            cv = e.context.get("contract_violation", "unknown")
            if cv not in result:
                result[cv] = []
            result[cv].append(e)
        return result

    # ── Summary (audit / display) ──────────────────────────────

    @property
    def summary(self) -> Dict[str, Any]:
        """Human-readable summary for audit logs or startup printout.

        Returns a dict safe for JSON serialization, suitable for inclusion
        in audit_manifest or health_check output.
        """
        with self._lock:
            total = len(self._events)
            by_type: Dict[str, int] = {}
            violation_cats: Dict[str, int] = {}
            correlation_ids: set[str] = set()
            violation_total = 0

            for e in self._events:
                by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
                if e.correlation_id:
                    correlation_ids.add(e.correlation_id)
                cv = e.context.get("contract_violation")
                if cv is not None:
                    violation_total += 1
                    violation_cats[cv] = violation_cats.get(cv, 0) + 1

        return {
            "total_events": total,
            "events_by_type": by_type,
            "documents_tracked": len(correlation_ids),
            "violation_count": violation_total,
            "violations_by_category": violation_cats,
        }

    # ── Lifecycle ──────────────────────────────────────────────

    def clear(self) -> None:
        """Reset for reuse (e.g. between test cases)."""
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def __repr__(self) -> str:
        with self._lock:
            vcount = sum(
                1 for e in self._events
                if e.context.get("contract_violation") is not None
            )
            return (
                f"ContractAwareEventSink(events={len(self._events)}, "
                f"violations={vcount})"
            )
