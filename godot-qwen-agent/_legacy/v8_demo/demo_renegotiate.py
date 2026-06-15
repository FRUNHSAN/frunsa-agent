#!/usr/bin/env python3
"""Phase 25 Renegotiation Demo — chronic violation -> proposal -> human approval.

Validates:
  1. RelationshipMemoryStore detects chronic violators
  2. HITLGateway.submit_proposal() creates a NON-BLOCKING proposal
  3. Proposal stored in SEPARATE proposals table (not human_tickets)
  4. Human reviews and approves -> proposal resolved
  5. renegotiation_proposed event emitted
  """

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401

from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.hitl_gateway import HITLGateway
from core.adapters.persistence import RelationshipMemoryStore
from core.contracts.composition import (
    CompositionBlueprint,
    CompositionEvent,
    RenegotiationProposal,
)


def main():
    bp = CompositionBlueprint.from_dict({
        "version": "1.0.0", "lifecycle": "active",
        "default_chunker": "identity",
    })
    fp = bp.fingerprint

    sink = ContractAwareEventSink()
    memory = RelationshipMemoryStore(":memory:")
    hitl = HITLGateway(sink, memory)

    total = passed = 0
    def check(cond, label):
        nonlocal total, passed
        total += 1; passed += 1 if cond else 0
        print(f"  {'[OK]' if cond else '[FAIL]'} {label}")

    print("=" * 60)
    print("[RENEG] Phase 25: Contract Renegotiator")
    print(f"   Blueprint: {fp}")
    print("=" * 60)

    # ── Phase 1: Simulate chronic deterioration ──────────────────

    print("\n[PHASE 1] Simulating 4 deterioration events over time...")
    prev = None
    for i in range(4):
        from core.contracts.composition import ContractHealthReport
        curr = ContractHealthReport(
            compliance_rate=1.0 - (0.15 * (i + 1)),
            severity="critical" if i >= 2 else "degraded",
            dominant_violation_type="tool_not_found",
            trend="deteriorating",
            total_documents=10, total_events=10,
            violation_counts={"tool_not_found": i + 1},
            evaluated_at=time.time(),
        )
        memory.record_transition(prev, curr, fp, lifecycle="active")
        prev = curr
    print(f"   Transitions recorded: {memory.count_transitions(fp)}")
    check(memory.count_transitions(fp) == 4, "4 transitions recorded")

    # ── Phase 2: Memory Inspector finds chronic violators ─────────

    print("\n[PHASE 2] Memory Inspector scanning for chronic violators...")
    violators = memory.get_chronic_violators(threshold=2, days=7)
    print(f"   Chronic violators: {len(violators)}")
    for v in violators:
        print(f"   -> {v['blueprint_fingerprint']}: "
              f"deterioration={v['deterioration_count']}, "
              f"top_violation={v.get('top_violation')}")
    check(len(violators) >= 1, "Chronic violator detected")

    # ── Phase 3: ContractRenegotiator generates proposal ──────────

    print("\n[PHASE 3] ContractRenegotiator generating proposal...")
    v = violators[0]
    proposal = RenegotiationProposal(
        blueprint_fingerprint=v["blueprint_fingerprint"],
        violation_type=v.get("top_violation", "unknown"),
        deterioration_count=v["deterioration_count"],
        suggested_action=(
            f"Deprecate tools causing {v.get('top_violation')} "
            f"and evaluate alternatives from Registry"
        ),
        severity=v.get("current_severity", "degraded"),
    )
    print(f"   Violation: {proposal.violation_type}")
    print(f"   Deterioration: {proposal.deterioration_count}")
    print(f"   Suggestion: {proposal.suggested_action}")

    # ── Phase 4: Submit via HITLGateway (non-blocking path) ───────

    print("\n[PHASE 4] Submitting proposal via HITLGateway...")
    proposal_id = hitl.submit_proposal(proposal)
    print(f"   Proposal ID: {proposal_id}")

    # Verify: separate table, NOT in human_tickets
    tickets = hitl.pending_tickets
    proposals = hitl.pending_proposals
    check(len(tickets) == 0,
          f"No intervention tickets created (got {len(tickets)})")
    check(len(proposals) == 1,
          f"Proposal in separate proposals table (got {len(proposals)})")

    # Verify: renegotiation_proposed event, NOT human_intervention_required
    hir = sink.by_type("human_intervention_required")
    ren = sink.by_type("renegotiation_proposed")
    check(len(hir) == 0,
          f"No HUMAN_INTERVENTION_REQUIRED (proposals are non-blocking) (got {len(hir)})")
    check(len(ren) == 1,
          f"RENEGOTIATION_PROPOSED event emitted (got {len(ren)})")

    # ── Phase 5: Human approves ───────────────────────────────────

    print("\n[PHASE 5] Human reviewing proposal...")
    print(f"   [SIMULATED HUMAN] Approved.")
    hitl.resolve_proposal(proposal_id, approved=True)

    pending_after = hitl.pending_proposals
    check(len(pending_after) == 0,
          f"Proposal resolved (pending count: {len(pending_after)})")

    resolved = sink.by_type("ticket_resolved")
    check(len(resolved) >= 1,
          f"TICKET_RESOLVED event emitted (got {len(resolved)})")

    # ── Summary ──────────────────────────────────────────────────

    print(f"\n{'='*60}")
    print(f"[RESULT] {passed}/{total} checks passed")
    print(f"  Intervention path (blocking):     HITLGateway.poll() + submit_decision()")
    print(f"  Proposal path   (non-blocking):   HITLGateway.submit_proposal() + resolve_proposal()")
    print(f"  Two paths, one gateway, zero semantic contamination.")
    if passed == total:
        print("[PASS] Contract Renegotiator VERIFIED.")
    else:
        print("[WARN] Some checks failed.")
    print(f"{'='*60}")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
