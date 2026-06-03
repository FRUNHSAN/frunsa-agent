"""DynamicBlueprint — PLAN5: the living contract.

A Blueprint that evolves during interaction. Unlike static YAML
blueprints, this one accepts proposals, applies modifications,
rolls back when changes worsen the relationship, and naturally
decays temporary adaptations back toward baseline over time.

Design:
  - Constitution: immutable gene set — proposals touching these are rejected
  - History: snapshot chain for rollback
  - Decay: stale modifications drift back toward baseline (Loop 2)
  - apply/revert: the core CRUD operations for contract evolution
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


# ── Immutable Genes ────────────────────────────────────────────────
CONSTITUTION = frozenset({
    "core_identity", "safety_rules", "honesty_policy", "privacy_boundary",
})

# ── Decay Scale: ordinal labels -> numeric values for smooth drift ──
VERBOSE_SCALE = {"EXTREME_BRIEF": 1, "LOW": 2, "HIGH": 3, "VERBOSE": 4}
VERBOSE_LABELS = {v: k for k, v in VERBOSE_SCALE.items()}

AUTONOMY_SCALE = {"DISABLED": 0, "ASK_FIRST": 1, "HIGH": 2, "FULL": 3}
AUTONOMY_LABELS = {v: k for k, v in AUTONOMY_SCALE.items()}

# Field -> (scale, labels) mapping for decay-aware fields
DECAY_FIELDS = {
    "response_verbose_level": (VERBOSE_SCALE, VERBOSE_LABELS),
    "explanation_style": ({"BRIEF": 1, "THEORETICAL": 3}, {1: "BRIEF", 3: "THEORETICAL"}),
    "execution_autonomy": (AUTONOMY_SCALE, AUTONOMY_LABELS),
    "proactive_suggestions": ({"DISABLED": 0, "ENABLED": 1}, {0: "DISABLED", 1: "ENABLED"}),
}


@dataclass
class DynamicBlueprint:
    """A contract that evolves, heals, and forgets.

    Usage:
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")  # Adapt
        bp.tick(rounds_since_last_mod=15)                   # Drift back
    """

    fields: dict[str, Any] = field(default_factory=dict)
    _history: list[dict[str, Any]] = field(default_factory=list)
    _applied_count: int = 0
    _baseline: dict[str, Any] = field(default_factory=dict)
    _last_modified: dict[str, float] = field(default_factory=dict)
    _round_counter: int = 0

    def __post_init__(self) -> None:
        if not self._baseline:
            self._baseline = deepcopy(self.fields)

    def apply_proposal(self, target_key: str, new_value: Any) -> bool:
        """Apply a contract modification. Returns True if accepted."""
        if target_key in CONSTITUTION:
            return False
        if target_key not in self.fields:
            self.fields[target_key] = new_value
            self._last_modified[target_key] = self._round_counter
            return True
        if self.fields[target_key] == new_value:
            return False

        self._history.append(deepcopy(self.fields))
        self.fields[target_key] = new_value
        self._last_modified[target_key] = self._round_counter
        self._applied_count += 1
        return True

    def rollback(self) -> bool:
        """Undo the last applied proposal."""
        if not self._history:
            return False
        self.fields = self._history.pop()
        self._applied_count -= 1
        return True

    # ── Loop 2: Contract Half-Life Decay ────────────────────────

    def tick(self, half_life_rounds: int = 20) -> dict[str, str]:
        """Apply time-based decay to all modifiable fields.

        Fields modified more than `half_life_rounds` ago drift 50%
        toward baseline each call. Called once per round by main loop.

        Returns dict of {field: "old -> new"} for logging, empty if no decay.
        """
        self._round_counter += 1
        changes: dict[str, str] = {}

        for key, baseline_val in self._baseline.items():
            current = self.fields.get(key)
            if current is None or key not in DECAY_FIELDS:
                continue
            if current == baseline_val:
                continue

            scale, labels = DECAY_FIELDS[key]
            current_num = scale.get(current)
            baseline_num = scale.get(baseline_val)
            if current_num is None or baseline_num is None:
                continue

            # Only decay if stale enough
            last_mod = self._last_modified.get(key, 0)
            rounds_stale = self._round_counter - last_mod
            if rounds_stale < half_life_rounds:
                continue

            # Drift 50% toward baseline
            new_num = round(current_num + 0.5 * (baseline_num - current_num))
            if new_num == current_num:
                # Still drifting — move one step
                direction = 1 if baseline_num > current_num else -1
                new_num = current_num + direction

            new_label = labels.get(new_num)
            if new_label is None:
                continue  # No valid label at this drift point — skip
            if new_label != current:
                changes[key] = f"{current} -> {new_label}"
                self.fields[key] = new_label
                self._last_modified[key] = self._round_counter

        return changes

    @property
    def applied_count(self) -> int:
        return self._applied_count

    @property
    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.fields)

    @property
    def baseline(self) -> dict[str, Any]:
        return deepcopy(self._baseline)

    def __repr__(self) -> str:
        return f"DynamicBlueprint(fields={self.fields}, baseline={self._baseline})"

