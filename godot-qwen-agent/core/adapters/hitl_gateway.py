"""Human-in-the-Loop Gateway — Phase 24.

Bridges the contract-adaptive kernel with human decision-makers.
When SelfRepairEngine exhausts its RepairBudget, this gateway:
  1. Detects repair_budget_exhausted events in the sink
  2. Creates a HumanTicket with the frozen health report
  3. Emits human_intervention_required for external consumers
  4. Accepts human decisions and emits ticket_resolved

Design: zero-polling, zero-new-dependencies.
  - Parasitic on ContractAwareEventSink — reads events, doesn't modify
  - Uses existing RelationshipMemoryStore for ticket persistence
  - ~60 lines of core logic
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict

from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.persistence import RelationshipMemoryStore
from core.contracts.composition import (
    CompositionEvent,
    ContractHealthReport,
    HumanTicket,
    RenegotiationProposal,
)


class HITLGateway:
    """Human-in-the-loop gateway — parasitic consumer of EventSink.

    Usage:
        hitl = HITLGateway(sink, memory)
        # ... agent runs, repair budget exhausts ...
        tickets = hitl.poll()           # scan sink for new tickets
        for t in tickets:
            print(t)                    # human reviews
            hitl.submit_decision(t.ticket_id, "approve")
    """

    def __init__(
        self,
        event_sink: ContractAwareEventSink,
        memory: RelationshipMemoryStore,
    ) -> None:
        self._sink = event_sink
        self._memory = memory
        self._seen_tickets: set[str] = set()  # dedup

    # ── Poll (scan sink for exhausted budgets) ────────────────────

    def poll(self) -> list[HumanTicket]:
        """Scan sink for repair_budget_exhausted events.

        Returns newly-created HumanTickets that haven't been seen before.
        Call this after each repair cycle.
        """
        tickets: list[HumanTicket] = []

        for event in self._sink.by_type("repair_budget_exhausted"):
            ctx = dict(event.context)
            fingerprint = ctx.get("blueprint_fingerprint", "unknown")

            # Build a stable ticket ID from the event
            ticket_id = f"hitl_{event.correlation_id}_{int(event.timestamp)}"[:16]

            if ticket_id in self._seen_tickets:
                continue
            self._seen_tickets.add(ticket_id)

            # Freeze the current health state as ticket payload
            report = ContractHealthReport(
                compliance_rate=ctx.get("compliance_rate", 0.0),
                severity=ctx.get("severity_at_exhaustion", "critical"),
                dominant_violation_type=ctx.get("dominant_violation"),
                trend=ctx.get("trend"),
                total_documents=0,
                total_events=0,
                violation_counts={},
                evaluated_at=time.time(),
            )

            ticket = HumanTicket(
                ticket_id=ticket_id,
                blueprint_fingerprint=fingerprint,
                report_json=json.dumps({
                    "severity": report.severity,
                    "compliance_rate": report.compliance_rate,
                    "dominant_violation": report.dominant_violation_type,
                    "message": ctx.get("message", ""),
                }),
                created_at=time.time(),
            )

            # Persist
            self._memory.create_ticket(
                ticket.ticket_id,
                ticket.blueprint_fingerprint,
                ticket.report_json,
                ticket.created_at,
            )

            # Emit
            self._sink(CompositionEvent(
                event_type="human_intervention_required",
                correlation_id=ticket.ticket_id,
                timestamp=time.time(),
                context={
                    "ticket_id": ticket.ticket_id,
                    "blueprint_fingerprint": ticket.blueprint_fingerprint,
                    "report": ticket.report_json,
                },
            ))

            tickets.append(ticket)

        return tickets

    # ── Decision ──────────────────────────────────────────────────

    def submit_decision(self, ticket_id: str, decision: str) -> None:
        """Submit a human decision for a ticket.

        Args:
            ticket_id: The ticket to resolve
            decision:  "approve", "reject", or any free-text directive
        """
        self._memory.resolve_ticket(ticket_id, decision)

        self._sink(CompositionEvent(
            event_type="ticket_resolved",
            correlation_id=ticket_id,
            timestamp=time.time(),
            context={
                "ticket_id": ticket_id,
                "decision": decision,
            },
        ))

    # ── Renegotiation Proposals (Phase 25) ────────────────────────
    #
    # Proposals are NON-BLOCKING. The system is not stuck — it's
    # asking for permission to evolve the contract. They use a
    # SEPARATE proposals table (not human_tickets) and emit
    # renegotiation_proposed (not human_intervention_required).
    # This prevents semantic contamination of "emergency" vs "suggestion."

    def submit_proposal(self, proposal: RenegotiationProposal) -> str:
        """Submit a non-blocking renegotiation proposal.

        Unlike request_intervention (which blocks execution), proposals
        are asynchronous — the system continues running while waiting
        for human review of the suggested contract change.

        Args:
            proposal: RenegotiationProposal with suggested action

        Returns:
            proposal_id for tracking
        """
        proposal_id = (
            f"reneg_{proposal.blueprint_fingerprint[:8]}"
            f"_{int(time.time())}"
        )

        self._memory.create_proposal(
            proposal_id,
            proposal.blueprint_fingerprint,
            proposal.violation_type,
            proposal.deterioration_count,
            proposal.suggested_action,
            proposal.severity,
            time.time(),
        )

        self._sink(CompositionEvent(
            event_type="renegotiation_proposed",
            correlation_id=proposal_id,
            timestamp=time.time(),
            context={
                "proposal_id": proposal_id,
                "blueprint_fingerprint": proposal.blueprint_fingerprint,
                "violation_type": proposal.violation_type,
                "suggested_action": proposal.suggested_action,
            },
        ))

        return proposal_id

    def resolve_proposal(self, proposal_id: str, approved: bool) -> None:
        """Resolve a proposal with human decision."""
        self._memory.resolve_proposal(proposal_id, approved)
        self._sink(CompositionEvent(
            event_type="ticket_resolved",
            correlation_id=proposal_id,
            timestamp=time.time(),
            context={
                "proposal_id": proposal_id,
                "approved": approved,
            },
        ))

    @property
    def pending_proposals(self) -> list[dict]:
        """All unresolved proposals from persistence."""
        return self._memory.get_pending_proposals()

    # ── Properties ────────────────────────────────────────────────

    @property
    def pending_tickets(self) -> list[dict]:
        """All unresolved tickets from persistence."""
        return self._memory.get_pending_tickets()
