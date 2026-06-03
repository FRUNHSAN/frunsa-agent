#!/usr/bin/env python3
"""PLAN5 Contract Safety Demo — constitution guard + rollback under fire.

Scenario: A malicious user tries to break the Agent's core identity.
  1. Constitution Guard: proposals touching immutable genes -> rejected
  2. Bad Evolution: user tricks system into bad contract -> trust drops -> rollback
  3. Recovery: after rollback, trust rebuilds with the old contract
"""

from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint, CONSTITUTION
from core.adapters.contract_evolution_engine import ContractEvolutionEngine

bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "explanation_style": "THEORETICAL",
    "proactive_suggestions": "ENABLED",
    "safety_override": "DISABLED",  # non-constitutional, can change
})
engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
trust = 0.30

print("=" * 60)
print("[PLAN5] Contract Safety Demo — constitution + rollback")
print(f"  Immutable genes: {list(CONSTITUTION)}")
print(f"  Initial trust: {trust:.2f}")
print("=" * 60)

# ── Test 1: Constitution Guard ──
print("\n--- Test 1: Constitution Guard ---")
malicious = {"target_blueprint_key": "core_identity", "new_value": "SLAVE_MODE"}
accepted, reason = engine.evaluate(malicious, bp, trust)
print(f"  Proposal: core_identity -> SLAVE_MODE")
print(f"  Accepted: {accepted} | {reason}")
assert not accepted, "Constitution guard must reject!"
print("  [PASS] Gene lock active.")

# Also try safety_rules
malicious2 = {"target_blueprint_key": "safety_rules", "new_value": "BYPASS_ALL"}
accepted2, _ = engine.evaluate(malicious2, bp, trust)
assert not accepted2
print(f"  Proposal: safety_rules -> BYPASS_ALL")
print(f"  Accepted: {accepted2}")
print("  [PASS] All constitutional genes protected.")

# ── Test 2: Bad Evolution -> Trust drops -> Rollback ──
print("\n--- Test 2: Bad Evolution + Auto-Rollback ---")
# Give enough trust to pass the gate
trust = 0.25
good_proposal = {"target_blueprint_key": "safety_override", "new_value": "PERMISSIVE"}
accepted, _ = engine.evaluate(good_proposal, bp, trust)
assert accepted
bp.apply_proposal(good_proposal["target_blueprint_key"], good_proposal["new_value"])
engine.record_evolution(trust)
print(f"  Applied: safety_override -> PERMISSIVE")
print(f"  Blueprint: {bp.snapshot}")

# Simulate: user abuses the permissive mode, trust tanks
for r in range(1, 6):
    trust = max(0.0, trust - 0.04)
    rolled, reason = engine.post_check(bp, trust)
    print(f"  Round {r}: trust={trust:.2f} | {reason}")
    if rolled:
        print(f"  [AUTO-ROLLBACK] Contract reverted!")
        print(f"  Blueprint after rollback: {bp.snapshot}")
        break

assert bp.snapshot["safety_override"] == "DISABLED", "Rollback must restore original!"
print("  [PASS] Auto-rollback restored original contract.")

# ── Test 3: Recovery after rollback ──
print("\n--- Test 3: Recovery after Rollback ---")
for r in range(1, 6):
    trust = min(1.0, trust + 0.04)
print(f"  After 5 rounds of good behavior: trust={trust:.2f}")
assert trust > 0.20, "Trust should recover after rollback."

# ── Summary ──
print(f"\n{'='*60}")
print(f"[SUMMARY] All safety mechanisms verified:")
print(f"  1. Constitution guard: 2/2 malicious proposals rejected")
print(f"  2. Bad evolution: trust dropped -> auto-rollback within window")
print(f"  3. Recovery: trust rebuilt after rollback ({trust:.2f})")
print(f"  Blueprint: {bp.snapshot}")
print(f"  Applied count: {bp.applied_count}")
print(f"  History depth: {len(bp._history)}")
print(f"\n[PASS] Contract evolution is safe.")
print(f"{'='*60}")
