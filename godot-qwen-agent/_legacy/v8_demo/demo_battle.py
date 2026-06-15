#!/usr/bin/env python3
"""Phase 22 Battle Script — 契约自适应闭环验证.

Scenario: Quantum Computing Research
  Agent needs to search for three topics.
  web_search works for the first two, then hits rate_limit on the third.
  SelfRepairEngine detects the violation, finds brave_search as replacement,
  consumes repair budget, and the retry succeeds.

This is BOTH a demo and an integration test. Every assertion that fails
means the self-repair loop is broken.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure tools are registered before anything else
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401 — trigger @register

# Disable SimulatedWebSearch auto-failure for this battle scenario.
# We test contract violations (TOOL_NOT_FOUND), not technical failures.
components.tools.simulated_search.SimulatedWebSearch._global_fail_on_call = None

from core.adapters.composer import PipelineComposer
from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.health_evaluator import ContractHealthEvaluator
from core.adapters.repair_engine import (
    RepairBudget,
    RepairStrategy,
    SelfRepairEngine,
)
from core.adapters.persistence import RelationshipMemoryStore
from core.adapters.tool_adapter import ToolAdapter
from core.contracts import COMPONENT_REGISTRY
from core.contracts.composition import (
    CompositionBlueprint,
    ContractHealthReport,
    ContractViolation,
)
from core.contracts.tool import ToolCall


# ── Setup ────────────────────────────────────────────────────────────

def setup_battlefield():
    """Assemble all components for the battle.

    Returns a dict with all the pieces wired together.
    """
    blueprint = CompositionBlueprint.from_dict({
        "version": "1.0.0",
        "lifecycle": "active",
        "default_chunker": "identity",
    })

    sink = ContractAwareEventSink()
    evaluator = ContractHealthEvaluator()
    memory = RelationshipMemoryStore(":memory:")
    tool_adapter = ToolAdapter(blueprint=blueprint, event_sink=sink)
    repair_engine = SelfRepairEngine(
        blueprint=blueprint,
        event_sink=sink,
        budget=RepairBudget(max_total=3, max_per_type=2),
    )

    return {
        "blueprint": blueprint,
        "sink": sink,
        "evaluator": evaluator,
        "memory": memory,
        "tool_adapter": tool_adapter,
        "repair_engine": repair_engine,
    }


# ── Battle ───────────────────────────────────────────────────────────

def run_battle(battlefield: dict):
    """Execute the quantum computing research scenario.

    Returns (passed, failed) assertion counts.
    """
    passed = 0
    failed = 0

    def check(condition, label: str):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"    [OK] {label}")
        else:
            failed += 1
            print(f"  [FAIL] FAIL: {label}")

    bp = battlefield["blueprint"]
    sink = battlefield["sink"]
    evaluator = battlefield["evaluator"]
    memory = battlefield["memory"]
    adapter = battlefield["tool_adapter"]
    repair = battlefield["repair_engine"]

    fp = bp.fingerprint

    print("=" * 60)
    print("[BATTLE]  Phase 22 Battle: Quantum Computing Research")
    print(f"   Blueprint: {fp}")
    print(f"   Registered tools: {COMPONENT_REGISTRY.list_strategies('tool')}")
    print(f"   Repair budget: {repair.budget.max_total} total, "
          f"{repair.budget.max_per_type} per type")
    print("=" * 60)

    # ── Round 1: Normal operation ─────────────────────────────────

    print("\n[ROUND] Round 1: Searching 'quantum computing 2026'...")
    tc1 = ToolCall(tool_name="web_search",
                   parameters={"query": "quantum computing 2026"})
    r1 = adapter.execute(tc1)
    check(r1.success, "web_search returned success")
    check(r1.data is not None, "web_search returned data")
    check(r1.contract_violation is None, "No contract violation")
    print(f"   Result source: {r1.data.get('source') if r1.data else 'N/A'}")

    # ── Round 2: Still normal ─────────────────────────────────────

    print("\n[ROUND] Round 2: Searching 'quantum error correction'...")
    tc2 = ToolCall(tool_name="web_search",
                   parameters={"query": "quantum error correction"})
    r2 = adapter.execute(tc2)
    check(r2.success, "web_search second call succeeded")
    print(f"   Result source: {r2.data.get('source') if r2.data else 'N/A'}")

    # ── Round 3: LLM hallucinates a nonexistent tool ──────────────

    print("\n[FAIL] Round 3: LLM hallucinates 'google_search' tool (doesn't exist)...")
    tc3 = ToolCall(tool_name="google_search",
                   parameters={"query": "topological qubits"})
    r3 = adapter.execute(tc3)
    check(not r3.success, "google_search call FAILED (not found)")
    check(r3.contract_violation == ContractViolation.TOOL_NOT_FOUND,
          "Contract violation: TOOL_NOT_FOUND")
    print(f"   Violation: {r3.contract_violation}")
    print(f"   Error: {r3.error}")

    # ── Health Evaluation ─────────────────────────────────────────

    print("\n[HEALTH] Health Evaluation:")
    report = evaluator.evaluate(sink)
    print(f"   Severity: {report.severity}")
    print(f"   Compliance rate: {report.compliance_rate:.2f}")
    print(f"   Violations: {dict(report.violation_counts)}")
    print(f"   Lifecycle distribution: {dict(report.lifecycle_distribution)}")

    check(report.severity in ("degraded", "critical"),
          "Health severity is degraded or critical")
    check(report.compliance_rate < 1.0,
          "Compliance rate dropped below 1.0")

    # ── Self-Repair Decision ──────────────────────────────────────

    print("\n[REPAIR] Self-Repair Engine:")
    actions = repair.decide(report, sink)
    print(f"   Actions decided: {len(actions)}")
    for a in actions:
        print(f"   → {a.strategy.value}: {a.violation_type} "
              f"→ target={a.target_component}, replacement={a.replacement}")
        print(f"     Reason: {a.reason}")

    check(len(actions) >= 1, "At least one repair action was decided")

    # Find the REPLACE_COMPONENT action (should be the one for tool)
    replace_action = next(
        (a for a in actions
         if a.strategy == RepairStrategy.REPLACE_COMPONENT),
        None,
    )
    check(replace_action is not None,
          "REPLACE_COMPONENT strategy was chosen")
    if replace_action:
        check(replace_action.target_component == "tool",
              "Target component is 'tool'")
        check(replace_action.replacement is not None,
              "A replacement tool was found")
        print(f"   Replacement found: {replace_action.replacement}")

    # Execute repairs
    results = repair.execute_all(actions)
    check(len(results) >= 1, "Repair actions were executed")
    check(results[0]["applied"], "Repair was applied (not GIVE_UP)")

    # ── Round 4: Retry with replacement ───────────────────────────

    print("\n[RETRY] Round 4: Retrying with replacement tool...")
    replacement_name = replace_action.replacement if replace_action else "brave_search"
    tc4 = ToolCall(tool_name=replacement_name,
                   parameters={"query": "topological qubits"})
    r4 = adapter.execute(tc4)
    check(r4.success, f"Replacement tool '{replacement_name}' succeeded")
    if r4.data:
        print(f"   Result source: {r4.data.get('source', 'N/A')}")
    check(r4.contract_violation is None,
          "No contract violation from replacement tool")

    # ── Post-Repair Health ────────────────────────────────────────

    print("\n[HEALTH] Post-Repair Health Evaluation:")
    report2 = evaluator.evaluate(sink, previous=report)
    print(f"   Severity: {report2.severity}")
    print(f"   Compliance rate: {report2.compliance_rate:.2f}")
    print(f"   Trend: {report2.trend}")
    print(f"   Lifecycle distribution: {dict(report2.lifecycle_distribution)}")

    # Note: severity may still be degraded/critical because historical
    # violations persist in the sink. The real signal is trend + compliance.
    check(report2.trend == "improving",
          f"Trend is improving (got: {report2.trend})")
    check(report2.compliance_rate > report.compliance_rate,
          f"Compliance rate improved: {report.compliance_rate:.2f} -> {report2.compliance_rate:.2f}")

    # ── Memory: Record transitions ────────────────────────────────

    print("\n[MEMORY] Relationship Memory:")
    memory.record_transition(None, report, fp, lifecycle="active")
    memory.record_transition(report, report2, fp, lifecycle="active")

    history = memory.get_history(fp)
    check(len(history) >= 2,
          f"Memory recorded at least 2 transitions (got: {len(history)})")

    latest = memory.get_latest(fp)
    check(latest is not None, "Latest transition is retrievable")
    check(latest["severity_after"] in ("degraded", "critical", "healthy"),
          f"Latest severity_after is valid (got: {latest['severity_after']})")
    check(latest["compliance_delta"] > 0,
          f"Latest delta is positive (improvement) (got: {latest['compliance_delta']})")

    deterioration = memory.get_deterioration_count(fp)
    print(f"   Transitions recorded: {memory.count_transitions(fp)}")
    print(f"   Deterioration events: {deterioration}")
    print(f"   Latest delta: {latest['compliance_delta']:.4f}")

    # ── Events audit ──────────────────────────────────────────────

    print(f"\n[AUDIT] Event Sink Summary:")
    summary = sink.summary
    print(f"   Total events: {summary['total_events']}")
    print(f"   Documents tracked: {summary['documents_tracked']}")
    print(f"   Violations: {summary['violation_count']}")
    print(f"   Events by type: {summary['events_by_type']}")
    print(f"   Violations by category: {summary['violations_by_category']}")

    check(summary["total_events"] >= 5,
          f"At least 5 events recorded (got: {summary['total_events']})")
    # Should have repair events
    repair_events = sink.by_type("repair_attempted")
    check(len(repair_events) >= 1,
          f"Repair attempted events recorded (got: {len(repair_events)})")

    return passed, failed


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    battlefield = setup_battlefield()
    passed, failed = run_battle(battlefield)

    print("\n" + "=" * 60)
    print(f"[RESULT] Battle Complete: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\n[BROKEN] SELF-REPAIR LOOP BROKEN — check failures above.")
        sys.exit(1)
    else:
        print("\n[PASS] ALL CHECKS PASSED — self-repair loop verified.")
        print("   The contract-adaptive muscle layer is battle-ready.")
        sys.exit(0)
