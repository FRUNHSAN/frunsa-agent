#!/usr/bin/env python3
"""PLAN5 Loop 1: Backlash — the real world teaches the contract.

Scenario: Contract evolves execution_autonomy to HIGH (Agent acts freely).
Reality bites: API timeouts, permission denials, execution failures.
Each failure generates a negative proposal -> contract downgrades autonomy.
The Agent learns: freedom without reliability is dangerous.
"""

from __future__ import annotations
import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.adapters.contract_evolution_engine import ContractEvolutionEngine

bp = DynamicBlueprint({
    "execution_autonomy": "HIGH",
    "response_verbose_level": "HIGH",
})
engine = ContractEvolutionEngine(trust_threshold=0.05)
trust = 0.30

# Simulated tool executions with HIGH autonomy
tools = [
    ("deploy_to_prod", "SUCCESS"),
    ("send_email", "SUCCESS"),
    ("delete_cache", "PERMISSION_DENIED"),   # ouch
    ("deploy_to_prod", "API_TIMEOUT"),       # ouch
    ("send_email", "SUCCESS"),
    ("delete_cache", "PERMISSION_DENIED"),   # again!
    ("deploy_to_prod", "API_TIMEOUT"),       # again!
    ("send_email", "SUCCESS"),
]

print("=" * 60)
print("[PLAN5] Loop 1: Backlash — reality teaches the contract")
print(f"  Initial: {bp.snapshot}")
print(f"  Trust: {trust:.2f}")
print("=" * 60)

for r, (tool, result) in enumerate(tools, 1):
    if result != "SUCCESS":
        # Failure -> negative proposal
        proposal = {
            "target_blueprint_key": "execution_autonomy",
            "new_value": "ASK_FIRST",
            "trigger_condition": f"tool_failure:{tool}",
            "human_reason": f"{tool} failed({result}). Autonomy is burning trust.",
        }
        accepted, reason = engine.evaluate(proposal, bp, trust)
        if accepted:
            bp.apply_proposal("execution_autonomy", "ASK_FIRST")
            print(f"  R{r}: {tool} -> {result} | [Autonomy DOWNGRADED] HIGH -> ASK_FIRST")
        else:
            print(f"  R{r}: {tool} -> {result} | [Rejected] {reason}")
        trust = max(0.0, trust - 0.04)
    else:
        trust = min(1.0, trust + 0.02)
        print(f"  R{r}: {tool} -> {result} | trust={trust:.2f}")

    # Decay tick
    bp.tick(half_life_rounds=20)

print(f"\n  Final: {bp.snapshot} | trust={trust:.2f}")
print(f"  Evolutions: {bp.applied_count}")

if bp.snapshot.get("execution_autonomy") != "HIGH":
    print(f"\n[PASS] Loop 1 verified. Reality taught the contract.")
    print(f"  Too many failures -> autonomy downgraded.")
    print(f"  The Agent learned: freedom without reliability is dangerous.")
else:
    print(f"\n[INFO] Autonomy unchanged. Not enough failures to trigger guard.")
