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
    _rejection_log: list[dict] = field(default_factory=list)  # for System 2
    _instructions: dict[str, str] = field(default_factory=dict)  # (field:value) → instruction
    _instruction_last_used: dict[str, int] = field(default_factory=dict)  # (field:value) → round last used
    _baseline: dict[str, Any] = field(default_factory=dict)
    _last_modified: dict[str, float] = field(default_factory=dict)
    _round_counter: int = 0

    # ── Safety valves ──
    cooldown_rounds: int = 5       # Same field can't change twice within this
    min_autonomy: str = "ASK_FIRST"  # execution_autonomy can't drop below this

    def __post_init__(self) -> None:
        if not self._baseline:
            self._baseline = deepcopy(self.fields)

    def apply_proposal(
        self, target_key: str, new_value: Any, ignore_cooldown: bool = False,
        instruction: str = "",
    ) -> tuple[bool, str]:
        """Apply a contract modification.

        Returns (accepted, reason). Guards:
          - Constitution: immutable genes rejected
          - Schema: value must be valid per BLUEPRINT_SCHEMA, OR provide instruction for novel value
          - Cooldown: same field can't change twice within cooldown_rounds
          - Min autonomy: execution_autonomy can't drop below min_autonomy
        """
        if target_key in CONSTITUTION:
            self._log_rejection(target_key, new_value, f"Gene lock: immutable")
            return False, f"Gene lock: '{target_key}' is immutable."

        # ── Schema validation ──
        try:
            from .blueprint_schema import BLUEPRINT_SCHEMA
            field_schema = BLUEPRINT_SCHEMA.get(target_key)
            if field_schema and field_schema["type"] == "enum":
                if new_value not in field_schema["values"]:
                    # Novel value: requires instruction
                    if not instruction or len(instruction) < 5:
                        self._log_rejection(target_key, new_value,
                            f"Schema: '{new_value}' not in schema and no valid instruction")
                        return False, (
                            f"Novel value '{new_value}' requires instruction (≥5 chars)."
                        )
                    if len(instruction) > 80:
                        self._log_rejection(target_key, new_value,
                            "Instruction too long")
                        return False, "Instruction must be ≤80 characters."
                    # Accept novel value with instruction
                    self._instructions[f"{target_key}:{new_value}"] = instruction
        except ImportError:
            pass

        # ── Cooldown guard ──
        if not ignore_cooldown and target_key in self._last_modified:
            rounds_since = self._round_counter - self._last_modified[target_key]
            if rounds_since < self.cooldown_rounds:
                self._log_rejection(target_key, new_value,
                    f"Cooldown: changed {rounds_since}r ago")
                return False, (
                    f"Cooldown active: '{target_key}' changed "
                    f"{rounds_since} rounds ago (needs {self.cooldown_rounds})."
                )

        # ── Min autonomy floor ──
        if target_key == "execution_autonomy":
            from .dynamic_blueprint import AUTONOMY_SCALE
            current_num = AUTONOMY_SCALE.get(self.fields.get(target_key, self.min_autonomy), 99)
            new_num = AUTONOMY_SCALE.get(new_value, 99)
            min_num = AUTONOMY_SCALE.get(self.min_autonomy, 1)
            if new_num < min_num:
                self._log_rejection(target_key, new_value,
                    f"Min autonomy floor: {self.min_autonomy}")
                return False, (
                    f"Min autonomy floor: can't drop below "
                    f"'{self.min_autonomy}'. Rejecting '{new_value}'."
                )
            if new_num == current_num:
                return False, "No-op: same value."

        elif target_key not in self.fields:
            self.fields[target_key] = new_value
            self._last_modified[target_key] = self._round_counter
            return True, "Created new field."

        elif self.fields[target_key] == new_value:
            return False, "No-op: same value."

        # ── Accept ──
        self._history.append(deepcopy(self.fields))
        self.fields[target_key] = new_value
        self._last_modified[target_key] = self._round_counter
        self._applied_count += 1
        return True, "Accepted."

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
        # Periodic GC: clean stale instructions every 10 rounds
        if self._round_counter % 10 == 0:
            self.gc_instructions(stale_rounds=60)
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

    # ── Enforcement interface ──
    def _log_rejection(self, key: str, value: Any, reason: str) -> None:
        self._rejection_log.append({
            "key": key, "value": str(value),
            "reason": reason, "round": self._round_counter,
        })
        if len(self._rejection_log) > 20:
            self._rejection_log = self._rejection_log[-20:]

    @property
    def rejection_log(self) -> list[dict]:
        return list(self._rejection_log)

    def enforce(self, key: str) -> Any | None:
        """Hard read of a contract field. For code-level enforcement.

        Unlike Prompt rendering (soft read), this is a physical constraint.
        Any component can query: 'what does the contract require of me?'
        """
        return self.fields.get(key)

    def get_instruction(self, key: str) -> str:
        """Get execution instruction for a field's current value."""
        val = self.fields.get(key, "")
        if val:
            self._instruction_last_used[f"{key}:{val}"] = self._round_counter
        return self._instructions.get(f"{key}:{val}", "")

    def gc_instructions(self, stale_rounds: int = 60) -> int:
        """Remove novel values unused for ≥stale_rounds. Returns count removed."""
        removed = 0
        for kv in list(self._instructions.keys()):
            last = self._instruction_last_used.get(kv, 0)
            if self._round_counter - last >= stale_rounds:
                del self._instructions[kv]
                self._instruction_last_used.pop(kv, None)
                removed += 1
        return removed

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

