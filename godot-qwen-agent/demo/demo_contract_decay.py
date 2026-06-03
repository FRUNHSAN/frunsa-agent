#!/usr/bin/env python3
"""PLAN5 Loop 2: Contract Half-Life Decay.

Scenario: Agent adapts to midnight exhaustion (HIGH -> EXTREME_BRIEF).
Then morning comes. User is fresh. Without decay, Agent stays in
EXTREME_BRIEF forever — traumatized. With decay, the contract
naturally drifts back toward baseline over time.

Loop 2 validates: contracts that are not reinforced naturally fade.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint

bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "execution_autonomy": "ASK_FIRST",
    "proactive_suggestions": "ENABLED",
    "explanation_style": "THEORETICAL",
})
print("=" * 60)
print("[PLAN5] Loop 2: Contract Half-Life Decay")
print(f"  Baseline: {bp.baseline}")
print(f"  Current:  {bp.snapshot}")
print("=" * 60)

# Phase 1: Midnight exhaustion -> adapt
print("\n--- Phase 1: Midnight. User exhausted. Adapt. ---")
bp.apply_proposal("response_verbose_level", "EXTREME_BRIEF")
bp.apply_proposal("proactive_suggestions", "DISABLED")
print(f"  Adapted: {bp.snapshot}")

# Phase 2: Simulate 25 rounds passing (morning comes)
print(f"\n--- Phase 2: 25 rounds pass. Morning arrives. ---")
for r in range(1, 26):
    changes = bp.tick(half_life_rounds=15)
    if changes:
        print(f"  Round {r}: Decay! {changes}")
    elif r in [5, 10, 15, 20, 25]:
        print(f"  Round {r}: No decay yet (fields still fresh)")

print(f"  After 25 rounds: {bp.snapshot}")

# Verify: contract has drifted back toward baseline
assert bp.snapshot["response_verbose_level"] != "EXTREME_BRIEF", \
    "Should have decayed away from EXTREME_BRIEF!"
assert bp.snapshot["proactive_suggestions"] != "DISABLED", \
    "Should have decayed away from DISABLED!"
print(f"  [PASS] Contract decayed. Agent healed from midnight trauma.")

# Phase 3: Evening fatigue hits again -> re-adapt
print(f"\n--- Phase 3: Evening. User tired again. Re-adapt. ---")
bp.apply_proposal("response_verbose_level", "LOW")
print(f"  Re-adapted: {bp.snapshot}")

# Phase 4: More rounds pass -> decays again
print(f"\n--- Phase 4: 20 more rounds. Decays again. ---")
for r in range(20):
    bp.tick(half_life_rounds=15)
print(f"  Final: {bp.snapshot}")

assert bp.snapshot["response_verbose_level"] == "HIGH", \
    "Should be back at baseline HIGH!"
print(f"  [PASS] Contract fully restored to baseline.")

print(f"\n{'='*60}")
print(f"[SUMMARY] Loop 2 verified:")
print(f"  1. Extreme adaptations (EXTREME_BRIEF) decay when not reinforced")
print(f"  2. Baseline (HIGH) is the attractor — system always drifts home")
print(f"  3. Re-adaptation works (LOW when tired again)")
print(f"  4. Final state = baseline (Agent healed)")
print(f"\n[PASS] Contracts breathe. They adapt, then they heal.")
print(f"{'='*60}")
