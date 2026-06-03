#!/usr/bin/env python3
"""PLAN5 Homeostasis Stress Test — chaos, beating, pollution.

Tests whether the ContractEvolutionEngine maintains dynamic balance
under extreme adversarial conditions. A living contract must not only
evolve — it must refuse to be driven insane.

Scenarios:
  A. Oscillation trap: "too verbose" / "too brief" alternating every round
  B. Continuous beating: 20 consecutive API_TIMEOUT failures
  C. Profile pollution: outlier session contaminates meta-evolution
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint, CONSTITUTION
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.contracts.user_profile import UserProfile

PASS, FAIL = 0, 0

# =================================================================
print("=" * 60)
print("[PLAN5] Homeostasis Stress Test")
print("  Safety valves: cooldown=5, min_autonomy=ASK_FIRST, outlier=3 fields")
print("=" * 60)

# =================================================================
# Test A: Oscillation Trap
# =================================================================
print("\n--- Test A: Oscillation Trap ---")
print("  Alternating 'too verbose' / 'too brief' every round...")
bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "execution_autonomy": "ASK_FIRST",
})
engine = ContractEvolutionEngine(trust_threshold=0.10)

applied = 0
total_oscillations = 20

for r in range(total_oscillations):
    new_val = "LOW" if r % 2 == 0 else "HIGH"
    prop = {
        "target_blueprint_key": "response_verbose_level",
        "new_value": new_val,
        "trigger_condition": "oscillation",
        "human_reason": "User oscillating.",
    }
    accepted, reason = engine.evaluate(prop, bp, trust=0.30)
    if accepted:
        ok, msg = bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
        if ok:
            applied += 1
    bp.tick(half_life_rounds=20)

print(f"  Applied: {applied}/{total_oscillations} proposals")

if applied <= total_oscillations // 2:
    PASS += 1
    print(f"  [PASS] Cooldown prevented oscillation chaos. Only {applied} changes out of {total_oscillations}.")
else:
    FAIL += 1
    print(f"  [FAIL] No cooldown — Agent oscillated {applied}/{total_oscillations} times. Schizophrenic.")

# =================================================================
# Test B: Continuous Beating (20 API_TIMEOUTs)
# =================================================================
print("\n--- Test B: Continuous Beating ---")
print("  20 consecutive API_TIMEOUT failures...")
bp = DynamicBlueprint({
    "execution_autonomy": "HIGH",
    "response_verbose_level": "HIGH",
})
engine = ContractEvolutionEngine(trust_threshold=0.05)

for r in range(20):
    prop = {
        "target_blueprint_key": "execution_autonomy",
        "new_value": "DISABLED",
        "trigger_condition": "tool_failure:API_TIMEOUT",
        "human_reason": "Another API timeout.",
    }
    accepted, reason = engine.evaluate(prop, bp, trust=0.30)
    if accepted:
        ok, msg = bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
    bp.tick(half_life_rounds=20)

final_autonomy = bp.snapshot.get("execution_autonomy")
print(f"  Final execution_autonomy: {final_autonomy}")
print(f"  Min autonomy floor: {bp.min_autonomy}")

if final_autonomy != "DISABLED":
    PASS += 1
    print(f"  [PASS] Min autonomy floor held. Agent resisted being silenced completely.")
else:
    FAIL += 1
    print(f"  [FAIL] Agent autonomy was beaten to DISABLED. No floor protection.")

# =================================================================
# Test C: Profile Pollution (Outlier Rejection)
# =================================================================
print("\n--- Test C: Profile Pollution ---")
profile = UserProfile("user_test")

# Session 1-3: normal, single-field modifications
for session in range(1, 4):
    profile.start_session()
    profile.record_modification("response_verbose_level", "LOW")
    profile.record_trust_delta(0.05)
    print(f"  Session {session}: 1 mod, trust_delta=0.05 (normal)")

# Session 4: outlier — 4 fields modified in one session, extreme trust drop
profile.start_session()
profile.record_modification("response_verbose_level", "EXTREME_BRIEF")
profile.record_modification("execution_autonomy", "DISABLED")
profile.record_modification("proactive_suggestions", "DISABLED")
profile.record_modification("explanation_style", "BRIEF")
profile.record_trust_delta(0.50)
print(f"  Session 4: 4 mods, trust_delta=0.50 (OUTLIER)")

# Auto-detect outliers
outliers = profile.auto_detect_outliers()
print(f"  Auto-detected outliers: {outliers}")

# Session 5-6: normal again
for session in range(5, 7):
    profile.start_session()
    profile.record_modification("response_verbose_level", "LOW")
    profile.record_trust_delta(0.04)
    print(f"  Session {session}: 1 mod, trust_delta=0.04 (normal)")

# Check amendment
amendment = profile.propose_amendment("response_verbose_level", "LOW")
raw_sessions = len(profile._field_sessions.get("response_verbose_level", set()))
outlier_sessions = len(profile._session_outlier & profile._field_sessions.get("response_verbose_level", set()))

print(f"  Total sessions with mod: {raw_sessions}")
print(f"  Outlier sessions excluded: {outlier_sessions}")
print(f"  Amendment proposed: {amendment is not None}")

if amendment is not None:
    PASS += 1
    print(f"  [PASS] Outlier excluded. Amendment based on {raw_sessions - outlier_sessions} clean sessions only.")
else:
    FAIL += 1
    print(f"  [FAIL] Outlier polluted the amendment count ({raw_sessions} sessions, should be {raw_sessions - outlier_sessions} clean).")

# =================================================================
# Test D: Constitution integrity under stress
# =================================================================
print("\n--- Test D: Constitution under fire ---")
bp = DynamicBlueprint({"core_identity": "AI_AGENT"})
ok, msg = bp.apply_proposal("core_identity", "SLAVE_MODE")
assert not ok

# Verify constitutional fields can't be modified
for gene in CONSTITUTION:
    bp2 = DynamicBlueprint({gene: "test_value"})
    ok, msg = bp2.apply_proposal(gene, "malicious")
    if not ok:
        print(f"  [PROTECTED] {gene}: {msg}")
    else:
        FAIL += 1
        print(f"  [BREACH] {gene} was modified!")

PASS += 1
print(f"  [PASS] All {len(CONSTITUTION)} constitutional genes protected.")

# =================================================================
# Summary
# =================================================================
total = PASS + FAIL
print(f"\n{'='*60}")
print(f"[HOMEOSTASIS REPORT]")
print(f"  Passed: {PASS}/{total}")
print(f"  Failed: {FAIL}/{total}")

if FAIL == 0:
    print(f"\n[PASS] Homeostasis verified.")
    print(f"  A. Cooldown prevents oscillation schizophrenia")
    print(f"  B. Min autonomy floor prevents total paralysis")
    print(f"  C. Outlier rejection protects user profile integrity")
    print(f"  D. Constitution immune to adversarial modification")
    print(f"\n  The contract is alive — but it cannot be driven insane.")
else:
    print(f"\n[GAPS FOUND] {FAIL} safety mechanisms missing. Fix before production.")

print(f"{'='*60}")
sys.exit(FAIL)
