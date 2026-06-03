"""ContractEvolutionEngine — PLAN5: accept, reject, or rollback proposals.

Decides whether a contract modification should be applied based on
relational state and post-evolution outcomes. Implements:
  - Constitution guard: reject proposals touching immutable genes
  - Trust gate: reject if trust too low
  - Post-evolution check: auto-rollback if trust drops after change
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.contracts.dynamic_blueprint import DynamicBlueprint


@dataclass
class ContractEvolutionEngine:
    """Gatekeeper for contract modifications.

    Usage:
        engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
        if engine.evaluate(proposal, blueprint, trust):
            blueprint.apply_proposal(...)
            engine.record_evolution(trust_before)
        # ... 3 rounds later ...
        engine.post_check(blueprint, trust_now)  # May auto-rollback
    """

    trust_threshold: float = 0.10       # Min trust to accept any proposal
    rollback_window: int = 3            # Rounds to monitor after evolution
    rollback_trust_drop: float = 0.05   # Trust drop that triggers auto-rollback
    _trust_at_evolution: float | None = field(default=None, repr=False)
    _rounds_since_evolution: int = field(default=0, repr=False)

    def evaluate(
        self, proposal: dict, blueprint: DynamicBlueprint, trust: float,
    ) -> tuple[bool, str]:
        """Decide whether to accept a proposal.

        Returns (accepted, reason).
        """
        target = proposal.get("target_blueprint_key", "")

        # Constitution guard: immutable genes
        from core.contracts.dynamic_blueprint import CONSTITUTION
        if target in CONSTITUTION:
            return False, f"Gene lock: '{target}' is an immutable constitutional gene."

        # Trust gate: relationship too damaged
        if trust < self.trust_threshold:
            return False, (
                f"Trust gate: trust={trust:.2f} below threshold "
                f"{self.trust_threshold}. Rebuild trust before proposing."
            )

        return True, "Accepted."

    def record_evolution(self, trust_before: float) -> None:
        """Record that an evolution was applied. Used for post-check."""
        self._trust_at_evolution = trust_before
        self._rounds_since_evolution = 0

    def post_check(
        self, blueprint: DynamicBlueprint, trust_now: float,
    ) -> tuple[bool, str]:
        """Check if recent evolution worsened the relationship.

        Called each round after an evolution. If trust drops significantly
        within the rollback window, auto-rollback.

        Returns (rolled_back, reason).
        """
        if self._trust_at_evolution is None:
            return False, "No pending evolution to check."

        self._rounds_since_evolution += 1

        if self._rounds_since_evolution >= self.rollback_window:
            if trust_now < self._trust_at_evolution - self.rollback_trust_drop:
                blueprint.rollback()
                self._trust_at_evolution = None
                return True, (
                    f"Auto-rollback: trust dropped from "
                    f"{self._trust_at_evolution:.2f} to {trust_now:.2f} "
                    f"after evolution. Contract reverted."
                )
            # Window passed, trust is fine — clear monitoring
            self._trust_at_evolution = None

        return False, (
            f"Monitoring: round {self._rounds_since_evolution}/"
            f"{self.rollback_window}"
        )
