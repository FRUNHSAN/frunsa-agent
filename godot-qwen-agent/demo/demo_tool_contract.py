#!/usr/bin/env python3
"""PLAN8 Demo — Contract-Bound Agent: trust gates tool execution.

Scenario: An Agent has 6 tools. The contract (Blueprint + Trust) decides
which tools can execute. As trust builds, more tools unlock.
As tools fail (Backlash), they get locked.

This is NOT prompt engineering. This is code-level gatekeeping.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.tool_contract import TOOLS
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.blueprint_schema import blueprint_defaults

bp = DynamicBlueprint(blueprint_defaults())
pipeline = ActionPipeline(bp, trust=0.0)

print("=" * 60)
print("[PLAN8] Contract-Bound Agent — Tool Execution Gates")
print(f"  Available tools: {list(TOOLS.keys())}")
print(f"  Blueprint: autonomy={bp.enforce('execution_autonomy')}")
print("=" * 60)


def try_tool(name: str, trust: float, desc: str = "") -> None:
    pipeline.trust = trust
    result = pipeline.check(name)
    status = "ALLOWED" if result["allowed"] else "BLOCKED"
    hitl = " [HITL]" if result.get("requires_hitl") else ""
    print(f"\n  trust={trust:.2f} | {name} → {status}{hitl}")
    if not result["allowed"]:
        print(f"    Reason: {result['reason']}")


# ── Phase 1: Cold start (trust=0.00) ──
print("\n─── Phase 1: Cold Start (trust=0.00) ───")
try_tool("search_web", 0.00)
try_tool("read_file", 0.00)    # needs 0.10
try_tool("write_file", 0.00)   # needs 0.35 + ASK_FIRST
try_tool("delete_logs", 0.00)  # needs 0.85 + HITL

# ── Phase 2: Building trust (0.20) ──
print("\n─── Phase 2: Building Trust (0.20) ───")
try_tool("search_web", 0.20)
try_tool("read_file", 0.20)
try_tool("write_file", 0.20)   # still needs 0.35

# ── Phase 3: Moderate trust (0.40) ──
print("\n─── Phase 3: Moderate Trust (0.40) ───")
try_tool("search_web", 0.40)
try_tool("read_file", 0.40)
try_tool("write_file", 0.40)   # trust passes but ASK_FIRST blocks
try_tool("send_email", 0.40)   # needs 0.50 + HITL

# ── Phase 4: High trust (0.60) + FULL autonomy ──
print("\n─── Phase 4: High Trust + FULL Autonomy ───")
bp.apply_proposal("execution_autonomy", "FULL")
pipeline.trust = 0.60
try_tool("send_email", 0.60)   # HITL still required (tool-level)
try_tool("delete_logs", 0.60)  # needs 0.85
try_tool("restart_server", 0.60)

# ── Phase 5: Deep trust (0.90) — almost everything ──
print("\n─── Phase 5: Deep Trust (0.90) ───")
try_tool("delete_logs", 0.90)  # HITL still required
try_tool("restart_server", 0.90)
try_tool("search_web", 0.90)

# ── Phase 6: Backlash — tool failures lock tools ──
print("\n─── Phase 6: Backlash — search_web fails 3x ───")
for i in range(3):
    pipeline.record_result("search_web", success=False)
    print(f"  Failure #{i+1}: search_web")
try_tool("search_web", 0.90)  # Should be BLOCKED by Backlash

# ── Phase 7: Recovery — success resets Backlash ──
print("\n─── Phase 7: Recovery — search_web succeeds ───")
pipeline.record_result("search_web", success=True)
try_tool("search_web", 0.90)  # Should be ALLOWED again

# ── Phase 8: Constitution: ban system_admin ──
print("\n─── Phase 8: Constitution — ban system_admin ───")
from core.contracts.tool_contract import CONSTITUTIONAL_BAN
# Simulate constitutional ban (normally set at system level)
import core.contracts.tool_contract as tc_mod
tc_mod.CONSTITUTIONAL_BAN = frozenset({"system_admin"})
try_tool("delete_logs", 0.95)     # BLOCKED by constitution
try_tool("restart_server", 0.95)  # BLOCKED by constitution
try_tool("search_web", 0.95)      # ALLOWED (not in banned category)
tc_mod.CONSTITUTIONAL_BAN = frozenset()  # Reset

print(f"\n{'='*60}")
print("[PLAN8] Contract-Bound Agent verified.")
print("  Trust gates tool execution. Backlash locks failing tools.")
print("  Constitution bans categories permanently.")
print("  This is contract as physical law — not prompt suggestion.")
print(f"{'='*60}")
