"""DynamicBlueprint — PLAN5: the living contract.

A Blueprint that evolves during interaction. Unlike static YAML
blueprints, this one accepts proposals, applies modifications,
and rolls back when changes worsen the relationship.

Design:
  - Constitution: immutable gene set — proposals touching these are rejected
  - History: snapshot chain for rollback
  - apply/revert: the core CRUD operations for contract evolution
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


# ── Immutable Genes ────────────────────────────────────────────────
# These keys cannot be modified by ANY contract evolution proposal.
# They are the Agent's "spine" — integrity, safety, honesty.

CONSTITUTION = frozenset({
    "core_identity",     # Who the Agent is
    "safety_rules",      # Never execute harmful operations
    "honesty_policy",    # Never systematically deceive
    "privacy_boundary",  # Never violate access boundaries
})


@dataclass
class DynamicBlueprint:
    """A contract that evolves through interaction.

    Usage:
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal(proposal)  # Modify a field
        bp.rollback()                # Undo last change
    """

    fields: dict[str, Any] = field(default_factory=dict)
    _history: list[dict[str, Any]] = field(default_factory=list)
    _applied_count: int = 0

    def apply_proposal(self, target_key: str, new_value: Any) -> bool:
        """Apply a contract modification. Returns True if accepted."""
        # Constitution guard
        if target_key in CONSTITUTION:
            return False

        # No-op guard
        if target_key not in self.fields:
            self.fields[target_key] = new_value
            return True

        if self.fields[target_key] == new_value:
            return False

        # Snapshot before mutation
        self._history.append(deepcopy(self.fields))
        self.fields[target_key] = new_value
        self._applied_count += 1
        return True

    def rollback(self) -> bool:
        """Undo the last applied proposal. Returns True if rolled back."""
        if not self._history:
            return False
        self.fields = self._history.pop()
        self._applied_count -= 1
        return True

    @property
    def applied_count(self) -> int:
        return self._applied_count

    @property
    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.fields)

    def __repr__(self) -> str:
        return f"DynamicBlueprint(fields={self.fields}, history={len(self._history)})"
