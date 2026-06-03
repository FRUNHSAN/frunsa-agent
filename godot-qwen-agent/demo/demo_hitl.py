#!/usr/bin/env python3
"""Phase 24 HITL Demo — Human-in-the-Loop Gateway verification.

Simulates a full scenario:
  1. Agent runs, repair budget exhausts
  2. HITLGateway detects the exhaustion → creates ticket
  3. Human reviews ticket → approves fallback strategy
  4. ticket_resolved event emitted → loop closed

This is BOTH a demo and an integration test.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401

from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.health_evaluator import ContractHealthEvaluator
from core.adapters.hitl_gateway import HITLGateway
from core.adapters.persistence import RelationshipMemoryStore
from core.adapters.repair_engine import (
    RepairBudget,
    SelfRepairEngine,
)
from core.adapters.tool_adapter import ToolAdapter
from core.contracts import COMPONENT_REGISTRY
from core.contracts.composition import (
    CompositionBlueprint,
    CompositionEvent,
    ContractViolation,
)
from core.contracts.tool import ToolCall


def main():
    bp = CompositionBlueprint.from_dict({
        "version": "1.0.0",
        "lifecycle": "active",
        "default_chunker": "identity",
    })
    fp = bp.fingerprint

    sink = ContractAwareEventSink()
    evaluator = ContractHealthEvaluator()
    memory = RelationshipMemoryStore(":memory:")
    adapter = ToolAdapter(blueprint=bp, event_sink=sink)
    repair = SelfRepairEngine(
        blueprint=bp, event_sink=sink,
        budget=RepairBudget(max_total=1, max_per_type=1),  # tiny budget
    )
    hitl = HITLGateway(sink, memory)

    total = passed = 0
    def check(cond, label):
        nonlocal total, passed
        total += 1; passed += 1 if cond else 0
        print(f"  {'[OK]' if cond else '[FAIL]'} {label}")

    print("=" * 60)
    print("[HITL] Phase 24: Human-in-the-Loop Gateway")
    print(f"   Blueprint: {fp}")
    print(f"   Repair budget: 1 total (will exhaust quickly)")
    print(f"   Registered tools: {COMPONENT_REGISTRY.list_strategies('tool')}")
    print("=" * 60)

    # ── Phase 1: Force repair budget exhaustion ──────────────────

    print("\n[PHASE 1] Triggering TOOL_NOT_FOUND to exhaust repair budget...")
    for i in range(3):
        tc = ToolCall(tool_name=f"nonexistent_{i}", parameters={})
        result = adapter.execute(tc)
        print(f"   Call {i+1}: {result.contract_violation}")

    report = evaluator.evaluate(sink)
    print(f"   Health: severity={report.severity}, compliance={report.compliance_rate:.2f}")

    actions = repair.decide(report, sink)
    repair.execute_all(actions)
    print(f"   Repair actions: {len(actions)}")
    check(len(actions) >= 1, "Repair actions generated")

    # Check for budget exhaustion
    exhausted = sink.by_type("repair_budget_exhausted")
    check(len(exhausted) >= 1, f"Budget exhaustion event emitted (got {len(exhausted)})")

    # ── Phase 2: HITLGateway detects and creates ticket ──────────

    print("\n[PHASE 2] HITLGateway scanning for exhausted budgets...")
    tickets = hitl.poll()
    check(len(tickets) >= 1, f"HITLGateway created ticket(s) (got {len(tickets)})")

    if tickets:
        t = tickets[0]
        print(f"   Ticket ID: {t.ticket_id}")
        print(f"   Blueprint: {t.blueprint_fingerprint}")
        print(f"   Report: {t.report_json[:120]}...")
        print(f"   Status: {t.status}")

    # Verify ticket persisted
    pending = hitl.pending_tickets
    check(len(pending) >= 1, f"Ticket persisted in DB (got {len(pending)})")

    # Verify human_intervention_required event
    hir_events = sink.by_type("human_intervention_required")
    check(len(hir_events) >= 1, f"HUMAN_INTERVENTION_REQUIRED event emitted (got {len(hir_events)})")

    # ── Phase 3: Human reviews and decides ────────────────────────

    print("\n[PHASE 3] Human reviewing ticket...")
    if tickets:
        t = tickets[0]
        report_data = json.loads(t.report_json)
        print(f"   Severity: {report_data.get('severity')}")
        print(f"   Compliance: {report_data.get('compliance_rate')}")
        print(f"   Dominant violation: {report_data.get('dominant_violation')}")
        print(f"   Message: {report_data.get('message', 'N/A')[:100]}")

        print("\n   [SIMULATED HUMAN] Approving fallback strategy...")
        hitl.submit_decision(t.ticket_id, "approve")

    # Verify ticket_resolved event
    resolved = sink.by_type("ticket_resolved")
    check(len(resolved) >= 1, f"TICKET_RESOLVED event emitted (got {len(resolved)})")

    # Verify ticket status changed
    pending_after = hitl.pending_tickets
    check(len(pending_after) == 0,
          f"Ticket resolved (pending count: {len(pending_after)})")

    # ── Summary ──────────────────────────────────────────────────

    print(f"\n[AUDIT] Event Sink:")
    summary = sink.summary
    print(f"   Total events: {summary['total_events']}")
    print(f"   Event types: {list(summary['events_by_type'].keys())}")
    for etype in ["human_intervention_required", "ticket_resolved",
                   "repair_budget_exhausted"]:
        count = summary['events_by_type'].get(etype, 0)
        check(count >= 1, f"Event '{etype}' present in sink")

    print(f"\n{'='*60}")
    print(f"[RESULT] {passed}/{total} checks passed")
    if passed == total:
        print("[PASS] Human-in-the-Loop Gateway VERIFIED.")
        print("  ESCALATE_TO_HUMAN is no longer a dead end.")
    else:
        print("[WARN] Some checks failed — review above.")
    print(f"{'='*60}")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
