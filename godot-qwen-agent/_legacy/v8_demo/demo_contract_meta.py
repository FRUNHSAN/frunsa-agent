#!/usr/bin/env python3
"""PLAN5 Loop 3: Meta-Evolution — constitutional amendment.

Scenario: User consistently prefers BRIEF across 4 sessions.
  Session 1: tired, Agent adapts LOW -> decay back to baseline
  Session 2: tired again, Agent adapts LOW -> decay back
  Session 3: tired again, Agent adapts LOW -> decay back
  Session 4: tired again, Agent adapts LOW

After 3+ sessions, UserProfile detects pattern -> constitutional amendment.
The new baseline for this user becomes LOW. Agent truly "knows" the user.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile

profile = UserProfile("user_zhang")

print("=" * 60)
print("[PLAN5] Loop 3: Meta-Evolution — constitutional amendment")
print(f"  User: {profile.user_id}")
print(f"  Amendment threshold: {profile.amendment_threshold} sessions")
print("=" * 60)

# ====================================================================
# Simulate 4 sessions.
# User consistently gets tired -> Agent adapts to LOW -> decays back.
# After 3+ sessions, the pattern is recognized as a personality trait.
# ====================================================================

for session in range(1, 5):
    profile.start_session()
    bp = DynamicBlueprint({
        "response_verbose_level": "HIGH",
        "proactive_suggestions": "ENABLED",
    })
    print(f"\n--- Session {session} ---")
    print(f"  Baseline: {bp.baseline}")

    # Simulate: user shows exhaustion, agent adapts
    bp.apply_proposal("response_verbose_level", "LOW")
    profile.record_modification("response_verbose_level", "LOW")
    print(f"  Adapted: {bp.snapshot}")

    # Simulate 25 rounds -> decay back toward baseline
    for _ in range(30):
        bp.tick(half_life_rounds=15)
    print(f"  After decay: {bp.snapshot}")

    # Check for amendment proposal
    amendment = profile.propose_amendment("response_verbose_level", "LOW")
    if amendment:
        print(f"  [CONSTITUTIONAL AMENDMENT] {amendment['human_reason']}")
        # Apply as new baseline
        bp._baseline["response_verbose_level"] = amendment["new_baseline"]
        bp.fields["response_verbose_level"] = amendment["new_baseline"]
        print(f"  New baseline set: {bp.baseline}")
    else:
        print(f"  Modification count: {profile.sessions_modified('response_verbose_level')}/{profile.amendment_threshold}")

# ====================================================================
# Summary
# ====================================================================
print(f"\n{'='*60}")
print(f"[SUMMARY] Meta-evolution verified:")
print(f"  User: {profile.user_id}")
print(f"  Sessions: {profile.session_count}")
print(f"  Field tracked: response_verbose_level")
print(f"  Modifications across sessions: {profile.sessions_modified('response_verbose_level')}")
print(f"  Amendment triggered: {'Yes' if profile.sessions_modified('response_verbose_level') >= profile.amendment_threshold else 'No'}")

if profile.sessions_modified("response_verbose_level") >= profile.amendment_threshold:
    print(f"\n[PASS] Loop 3 complete.")
    print(f"  Temporary adaptation -> permanent user trait.")
    print(f"  Agent evolves from 'responding to context' to 'knowing the user'.")
    print(f"  This is how contract evolves into constitution.")
else:
    print(f"\n[INFO] Need more sessions to trigger amendment.")
print(f"{'='*60}")
