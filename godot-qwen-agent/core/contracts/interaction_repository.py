"""InteractionRepository Protocol — Phase 25 anti-corruption layer.

Defines the contract between business logic and persistence.
Business code depends ONLY on this Protocol, never on sqlite3,
SQL strings, or table names. The concrete implementation
(SqliteInteractionRepository) can be swapped for PostgreSQL,
MongoDB, or an in-memory mock without touching any business logic.

Design invariant:
  - Zero SQL in this file — no SELECT, INSERT, table names
  - Zero third-party imports — pure Python Protocol
  - Methods return domain types (HumanTicket, dict), never cursors or rows
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InteractionRepository(Protocol):
    """Contract for human-interaction and health-tracking persistence.

    Implementations: SqliteInteractionRepository (current),
    PostgresInteractionRepository (future), MockRepository (testing).
    """

    # ── Health Transitions (Phase 22c) ───────────────────────────

    def record_transition(
        self,
        previous: object | None,
        current: object,
        blueprint_fingerprint: str,
        lifecycle: str = "active",
    ) -> None:
        """Persist a health transition between two assessments."""
        ...

    def get_history(
        self, blueprint_fingerprint: str, days: int = 7, limit: int = 100,
    ) -> list[dict]:
        """Get transition history for a blueprint."""
        ...

    def get_latest(self, blueprint_fingerprint: str) -> dict | None:
        """Get the most recent transition."""
        ...

    def count_transitions(
        self, blueprint_fingerprint: str, days: int = 7,
    ) -> int:
        """Count transitions in the last N days."""
        ...

    def get_deterioration_count(
        self, blueprint_fingerprint: str, days: int = 7,
    ) -> int:
        """Count deterioration events (negative delta)."""
        ...

    def get_chronic_violators(
        self, threshold: int = 3, days: int = 7,
    ) -> list[dict]:
        """Find blueprints with sustained deterioration."""
        ...

    # ── Human Tickets — Intervention (Phase 24) ──────────────────

    def create_ticket(
        self, ticket_id: str, blueprint_fingerprint: str,
        report_json: str, created_at: float,
    ) -> None:
        """Create a blocking intervention ticket."""
        ...

    def resolve_ticket(self, ticket_id: str, decision: str) -> None:
        """Resolve a ticket with human decision."""
        ...

    def get_pending_tickets(self) -> list[dict]:
        """Return all unresolved intervention tickets."""
        ...

    # ── Proposals — Renegotiation (Phase 25) ─────────────────────

    def create_proposal(
        self, proposal_id: str, blueprint_fingerprint: str,
        violation_type: str, deterioration_count: int,
        suggested_action: str, severity: str, created_at: float,
    ) -> None:
        """Create a non-blocking renegotiation proposal."""
        ...

    def resolve_proposal(self, proposal_id: str, approved: bool) -> None:
        """Resolve a proposal."""
        ...

    def get_pending_proposals(self) -> list[dict]:
        """Return all unresolved proposals."""
        ...

    # ── Lifecycle ────────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all data (test isolation)."""
        ...

    @property
    def transition_count(self) -> int:
        """Total transitions across all blueprints."""
        ...
