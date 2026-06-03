"""Renegotiation Watcher — Phase 29 (PLAN2 Axiom 2 complete).

Background scanner that watches for accumulated INTENTIONAL_VIOLATION
events. When the same contract is intentionally violated enough times
AND trust is high enough, the watcher crystallizes trust into a
RenegotiationProposal — inviting the human to evolve the contract together.

This is the final piece of PLAN2:
  Phase 26 (Intentional) -> Phase 27 (RelationalField) -> Phase 29 (Watcher)
  The Agent doesn't just follow contracts — it co-evolves them.

Design:
  - Stateless scan: reads EventSink, produces proposals
  - Trust-gated: only proposes when trust_watermark >= 0.7
  - Threshold: >= 3 intentional violations against the same target
  - Submits via HITLGateway (reuses Phase 25 proposal channel)
  - Trust cost: proposing consumes -0.1 trust (social courage)
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from core.contracts.composition import (
    ContractViolation,
    RenegotiationProposal,
)
from core.contracts.event_sink import EventSink
from core.contracts.relational_field import RelationalField


class RenegotiationWatcher:
    """Background scanner: intentional violations -> renegotiation proposals.

    Usage:
        watcher = RenegotiationWatcher(threshold=3, trust_threshold=0.7)
        proposal = watcher.scan(sink, field, bp_fingerprint)
        if proposal:
            hitl.submit_proposal(proposal)
    """

    def __init__(
        self,
        threshold: int = 3,
        trust_threshold: float = 0.7,
        trust_cost: float = 0.1,
    ) -> None:
        self._threshold = threshold
        self._trust_threshold = trust_threshold
        self._trust_cost = trust_cost

    def scan(
        self,
        sink: EventSink,
        field: RelationalField,
        blueprint_fingerprint: str,
    ) -> RenegotiationProposal | None:
        """Scan for accumulated intentional violations.

        Args:
            sink:                 EventSink with violation history
            field:                Current RelationalField (trust gating)
            blueprint_fingerprint: Which contract blueprint to scan for

        Returns:
            RenegotiationProposal if conditions are met, None otherwise.
        """
        # 1. Gate: trust must be high enough to propose
        if field.trust_watermark < self._trust_threshold:
            return None

        # 2. Extract all INTENTIONAL_VIOLATION events from the sink
        intentional_events = [
            e for e in sink.violations
            if e.context.get("contract_violation") == ContractViolation.INTENTIONAL_VIOLATION
        ]

        if len(intentional_events) < self._threshold:
            return None

        # 3. Pattern recognition: which tool/contract is most challenged?
        tool_hits = Counter(
            e.context.get("tool_name", "unknown")
            for e in intentional_events
        )
        most_challenged, count = tool_hits.most_common(1)[0]

        if count < self._threshold:
            return None

        # 4. Attribution: why did the Agent keep violating?
        reasons = [
            e.context.get("higher_value_reason", "")
            for e in intentional_events
            if e.context.get("tool_name") == most_challenged
        ]
        reason_counter = Counter(r for r in reasons if r)
        dominant_reason = (
            reason_counter.most_common(1)[0][0]
            if reason_counter else "User preference patterns detected"
        )

        # 5. Crystallize: generate proposal
        return RenegotiationProposal(
            blueprint_fingerprint=blueprint_fingerprint,
            violation_type=ContractViolation.INTENTIONAL_VIOLATION,
            deterioration_count=count,
            suggested_action=(
                f"Relax strict constraints on '{most_challenged}'. "
                f"Agent has intentionally overridden this contract {count} times "
                f"for higher values (dominant reason: {dominant_reason}). "
                f"Suggested: downgrade to DRAFT or modify parameters."
            ),
            severity=field.energy_level.value,
        )

    # ── Properties ────────────────────────────────────────────────

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def trust_threshold(self) -> float:
        return self._trust_threshold

    @property
    def trust_cost(self) -> float:
        """How much trust is consumed when a proposal is made."""
        return self._trust_cost
