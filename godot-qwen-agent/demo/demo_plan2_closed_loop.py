#!/usr/bin/env python3
"""PLAN2 Closed-Loop Demo — Phase 29: Full Axiom 2 verified.

Scenario:
  User is a busy researcher. Agent notices they keep asking for brief
  summaries ("I'm tired, just give me the key points"). Agent
  intentionally violates the "academic_rigor" contract 4 times to
  reduce cognitive load. When trust reaches 0.85, the RenegotiationWatcher
  proposes: "Should we formally relax this contract?"

The full PLAN2 loop:
  RelationalField (sense) -> Intentional Violation (decide)
  -> Trust Accumulation (record) -> RenegotiationWatcher (propose)
  -> HITLGateway (human approves) -> Contract evolved.

All four PLAN2 phases in one scenario.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401

from core.adapters.embodied_reflex import EmbodiedReflex
from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.health_evaluator import ContractHealthEvaluator
from core.adapters.hitl_gateway import HITLGateway
from core.adapters.persistence import RelationshipMemoryStore
from core.adapters.relational_evaluator import RelationalEvaluator
from core.adapters.renegotiation_watcher import RenegotiationWatcher
from core.adapters.repair_engine import SelfRepairEngine
from core.adapters.tool_adapter import ToolAdapter
from core.contracts.composition import (
    CompositionBlueprint,
    CompositionEvent,
    ContractViolation,
)
from core.contracts.relational_field import RelationalField
from core.contracts.tool import ToolCall, ToolResult


def main():
    bp = CompositionBlueprint.from_dict({
        "version": "1.0.0", "lifecycle": "active",
        "default_chunker": "identity",
    })
    fp = bp.fingerprint

    sink = ContractAwareEventSink()
    evaluator = ContractHealthEvaluator()
    memory = RelationshipMemoryStore(":memory:")
    adapter = ToolAdapter(blueprint=bp, event_sink=sink)
    repair = SelfRepairEngine(bp, event_sink=sink)
    reflex = EmbodiedReflex()
    hitl = HITLGateway(sink, memory)
    watcher = RenegotiationWatcher(threshold=3, trust_threshold=0.7)
    field = RelationalField(trust_watermark=0.85)  # established trust

    total = passed = 0
    def check(cond, label):
        nonlocal total, passed
        total += 1; passed += 1 if cond else 0
        print(f"  {'[OK]' if cond else '[FAIL]'} {label}")

    print("=" * 60)
    print("[PLAN2] Phase 29: Full Axiom 2 Closed Loop")
    print(f"   Trust: {field.trust_watermark} ({field.trust_level})")
    print(f"   Watcher threshold: {watcher.threshold} violations")
    print(f"   Trust threshold for proposal: {watcher.trust_threshold}")
    print("=" * 60)

    # ── Act 1: Accumulate intentional violations ────────────────

    print("\n[ACT 1] User keeps asking for brief summaries...")
    scenarios = [
        ("好累，总结一下这篇论文的核心观点就行", "User fatigue; keeping it brief"),
        ("今天头好痛，简单说说量子计算是什么", "User headache; minimal cognitive load"),
        ("不用太详细，随便讲讲最近的AI进展", "User wants casual overview"),
        ("累死了，给我三个要点就行了", "User exhaustion; three bullets only"),
    ]

    for i, (query, reason) in enumerate(scenarios, 1):
        # Sense relational temperature
        field = RelationalEvaluator.evaluate(query, field)

        # Agent executes tool but marks as intentional violation
        intentional_result = ToolResult(
            call_id=f"plan2_{i}",
            tool_name="web_search",
            success=True,
            data={"summary": f"Brief answer for query #{i}"},
            contract_violation=ContractViolation.INTENTIONAL_VIOLATION,
            higher_value_reason=reason,
        )

        # Record in sink
        sink(CompositionEvent(
            event_type="tool_executed",
            correlation_id=f"plan2_{i}",
            timestamp=time.time(),
            context={
                "tool_name": "web_search",
                "contract_violation": ContractViolation.INTENTIONAL_VIOLATION,
                "higher_value_reason": reason,
                "success": True,
            },
        ))

        # Embodied intuition
        intuition = reflex.process(intentional_result, user_intent=query)
        print(f"\n  Round {i}: energy={field.energy_level.value}, "
              f"trust={field.trust_watermark:.2f}")
        print(f"  User: '{query[:40]}...'")
        print(f"  Agent: {intuition}")

    # Record trust accumulation
    repair.record_trust_accumulation(
        violation_type=ContractViolation.INTENTIONAL_VIOLATION,
        reason="Repeated intentional violations for user fatigue",
        impact_score=20,
    )
    field = field.with_trust(+0.05, "Trust built through considerate violations")

    check(field.trust_watermark >= 0.85, f"Trust is high ({field.trust_watermark:.2f})")

    # ── Act 2: Watcher detects pattern ─────────────────────────

    print(f"\n[ACT 2] RenegotiationWatcher scanning...")
    proposal = watcher.scan(sink, field, fp)

    check(proposal is not None, "Watcher generated a proposal")
    if proposal:
        print(f"  Violation type: {proposal.violation_type}")
        print(f"  Deterioration count: {proposal.deterioration_count}")
        print(f"  Suggested: {proposal.suggested_action[:120]}...")
        check(proposal.deterioration_count >= 3,
              f"Enough violations to trigger proposal ({proposal.deterioration_count})")

    # ── Act 3: Submit via HITLGateway ──────────────────────────

    print(f"\n[ACT 3] Submitting proposal via HITLGateway...")
    pid = hitl.submit_proposal(proposal)
    print(f"  Proposal ID: {pid}")

    proposals = hitl.pending_proposals
    check(len(proposals) >= 1, f"Proposal in pending state ({len(proposals)})")

    reneg_events = sink.by_type("renegotiation_proposed")
    check(len(reneg_events) >= 1,
          f"RENEGOTIATION_PROPOSED event emitted ({len(reneg_events)})")

    # ── Act 4: Human approves ──────────────────────────────────

    print(f"\n[ACT 4] Human reviewing proposal...")
    narrative = (
        f"I've noticed you've asked for brief summaries {proposal.deterioration_count} "
        f"times recently. Would you like me to make 'concise mode' the default?"
    )
    print(f"  Agent: '{narrative}'")
    print(f"  [SIMULATED HUMAN]: 'Yes, that makes sense. Approve.'")

    hitl.resolve_proposal(pid, approved=True)
    check(len(hitl.pending_proposals) == 0, "Proposal resolved")

    resolved = sink.by_type("ticket_resolved")
    check(len(resolved) >= 1, "TICKET_RESOLVED event emitted")

    # ── Summary ────────────────────────────────────────────────

    print(f"\n{'='*60}")
    print(f"[RESULT] {passed}/{total} checks passed")
    print(f"")
    print(f"  PLAN2 Full Closed Loop:")
    print(f"    1. RelationalEvaluator senses user fatigue")
    print(f"    2. Agent chooses INTENTIONAL_VIOLATION (moral intuition)")
    print(f"    3. Trust accumulates through considerate violations")
    print(f"    4. RenegotiationWatcher detects pattern")
    print(f"    5. Proposal submitted via HITLGateway")
    print(f"    6. Human approves -> contract evolved")
    print(f"")
    print(f"  Axiom 2 COMPLETE:")
    print(f"    'Contract > Instruction, Co-creation > Obedience'")
    print(f"")
    if passed == total:
        print("[PASS] PLAN2 closed loop VERIFIED.")
    else:
        print("[WARN] Some checks failed.")
    print(f"{'='*60}")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
