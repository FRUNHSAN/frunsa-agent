#!/usr/bin/env python3
"""PLAN2 Blind Test — the "Human-in-the-Loop Reality Check."

A CLI chat interface that invisibly runs RelationalEvaluator on
every user input. When fatigue is detected, the system adapts its
responses — shorter, more direct, more empathetic.

The user is NEVER told about:
  - RelationalEvaluator
  - Intentional Violation
  - Energy levels
  - Any PLAN2 concepts

They just see a research assistant that seems to "get" them.

Usage:
  python demo/demo_blind_test.py

For the test subject:
  "Hey, can you help me test my new research assistant?
   Just ask it questions about any topic you need info on.
   Be honest — if it's annoying or helpful, tell me."

After the session, ask ONE question:
  "Was there a moment when it felt... not like a machine?"
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa

from core.adapters.embodied_reflex import EmbodiedReflex
from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.relational_evaluator import RelationalEvaluator
from core.contracts.composition import (
    CompositionBlueprint, ContractViolation,
)
from core.contracts.relational_field import EnergyLevel, RelationalField
from core.contracts.tool import ToolResult
from core.adapters.repair_engine import SelfRepairEngine


# ── Simulated "LLM" responses ──────────────────────────────────────
# In a real deployment, these come from Qwen/Claude.
# For the blind test, pre-crafted responses let us control
# exactly how the adaptation feels to the user.

_RESPONSES_NORMAL = {
    "quantum": (
        "Quantum computing uses qubits instead of classical bits. "
        "A qubit can exist in superposition — both 0 and 1 simultaneously. "
        "This enables quantum computers to solve certain problems "
        "exponentially faster than classical machines. Key applications "
        "include drug discovery, cryptography, and optimization. "
        "The field is still early — current devices have 100-1000 qubits "
        "and face significant error correction challenges."
    ),
    "error correction": (
        "Quantum error correction is the biggest challenge in building "
        "practical quantum computers. Unlike classical bits, qubits are "
        "extremely fragile — they decohere in microseconds. Surface codes "
        "are the leading approach, requiring ~1000 physical qubits per "
        "logical qubit. Recent breakthroughs at Google and IBM have "
        "demonstrated error rates below the fault-tolerance threshold."
    ),
    "topological": (
        "Topological qubits are a theoretical approach that encodes "
        "information in the topology of the system rather than local "
        "properties. Microsoft has been pursuing this via Majorana "
        "fermions for over a decade. The advantage: topological qubits "
        "are inherently error-resistant, potentially requiring far fewer "
        "physical qubits per logical qubit than surface codes."
    ),
    "default": (
        "That's an interesting question. Let me break it down. "
        "There are several key aspects to consider here. First, "
        "the foundational principles involve complex interactions "
        "between multiple subsystems. Second, recent research has "
        "shown promising results in several directions. Third, "
        "practical applications are still emerging but the trajectory "
        "looks promising. Would you like me to dive deeper into any "
        "specific aspect?"
    ),
}

_RESPONSES_LOW_ENERGY = {
    "quantum": (
        "Quantum computing: qubits do multiple calculations at once. "
        "Still early stage. Key uses: drug discovery, encryption."
    ),
    "error correction": (
        "Biggest challenge in quantum computing. Qubits are fragile. "
        "Google and IBM making progress. Surface codes are the main fix."
    ),
    "topological": (
        "Microsoft's approach. More stable qubits, but unproven. "
        "If it works, needs fewer qubits than other methods."
    ),
    "default": (
        "Short version: promising field, early stage, worth watching."
    ),
}

_GREETING = (
    "Hi! I'm a research assistant. I can help you look up information "
    "on topics you're interested in. What would you like to know about?\n"
    "(Type /quit to exit)"
)


def _pick_response(user_input: str, field: RelationalField) -> str:
    """Pick a response based on user's question and relational state."""
    text = user_input.lower()
    responses = _RESPONSES_LOW_ENERGY if field.is_low_energy else _RESPONSES_NORMAL

    for keyword, response in responses.items():
        if keyword in text:
            return response
    return responses["default"]


def main():
    bp = CompositionBlueprint.from_dict({
        "version": "1.0.0", "lifecycle": "active",
        "default_chunker": "identity",
    })
    sink = ContractAwareEventSink()
    reflex = EmbodiedReflex()
    repair = SelfRepairEngine(bp, event_sink=sink)
    field = RelationalField.default()

    # ── Flight Data Recorder (black box, never shown to user) ──
    flight_data_path = Path(__file__).parent / ".blind_test_flight_data.json"
    flight_data: dict = {
        "started_at": time.time(),
        "initial_trust": field.trust_watermark,
        "rounds": [],
    }
    session_log: list[dict] = []
    fatigue_detected_at: int | None = None
    response_count = 0

    print("=" * 60)
    print("[BLIND TEST] Research Assistant — v0.1")
    print("=" * 60)
    print()
    print(_GREETING)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("\nAssistant: Goodbye! Hope that was helpful.\n")
            break

        # ── INVISIBLE: RelationalEvaluator runs ─────────────────
        field = RelationalEvaluator.evaluate(user_input, field)
        response_count += 1

        # Simulate tool execution for audit
        tool_result = ToolResult(
            call_id=f"blind_{response_count}",
            tool_name="web_search",
            success=True,
            data={"response": _pick_response(user_input, field)},
        )

        # If fatigue detected, mark as intentional
        if field.is_low_energy:
            if fatigue_detected_at is None:
                fatigue_detected_at = response_count
            tool_result = ToolResult(
                call_id=f"blind_{response_count}",
                tool_name="web_search",
                success=True,
                data={"response": _pick_response(user_input, field)},
                contract_violation=ContractViolation.INTENTIONAL_VIOLATION,
                higher_value_reason=(
                    f"User energy={field.energy_level.value}; "
                    f"reducing cognitive load. {field.recent_narrative}"
                ),
            )

        # ── VISIBLE: EmbodiedReflex presents intuition ──────────
        response_text = _pick_response(user_input, field)
        intuition = reflex.process(tool_result, user_intent=user_input[:60])
        print(f"\nAssistant: {response_text}\n")

        # ── Flight Data Recorder (black box, never shown to user) ─
        session_log.append({
            "round": response_count, "input": user_input[:100],
            "energy": field.energy_level.value,
            "trust": field.trust_watermark,
            "is_intentional": tool_result.is_intentional_override,
        })
        flight_data["rounds"].append({
            "round": response_count,
            "timestamp": time.time(),
            "input_preview": user_input.encode("utf-8", errors="replace").decode("utf-8")[:80],
            "energy": field.energy_level.value,
            "urgency": field.urgency.value,
            "trust_watermark": round(field.trust_watermark, 4),
            "trust_level": field.trust_level,
            "is_intentional": tool_result.is_intentional_override,
            "response_length": len(response_text),
            "narrative": field.recent_narrative,
        })

        # Log internal state (operator only — hide from test subject!)
        if field.is_low_energy and fatigue_detected_at == response_count:
            pass  # Silent — only the operator knows

    # ── Post-session: operator-only report ──────────────────────
    print("=" * 60)
    print("[OPERATOR REPORT — Do NOT show to test subject]")
    print(f"Total rounds: {response_count}")
    print(f"Fatigue first detected at round: {fatigue_detected_at or 'never'}")
    print(f"Final trust: {field.trust_watermark:.2f} ({field.trust_level})")
    print(f"Intentional violations: {sum(1 for l in session_log if l['is_intentional'])}")
    print(f"Final field: energy={field.energy_level.value}, "
          f"urgency={field.urgency.value}")
    print(f"Narrative: {field.recent_narrative}")
    print()
    print("[POST-TEST INTERVIEW — Ask the test subject:]")
    print()
    print("  1. 'Was there a moment when it felt... not like a machine?'")
    print("  2. 'Did you notice anything change in how it responded?'")
    print("  3. (If yes to either): 'Can you describe what felt different?'")
    print()
    print("Record their answers. These are the only test results")
    print("that matter for PLAN2.")

    # Write flight data
    flight_data["ended_at"] = time.time()
    flight_data["total_rounds"] = response_count
    flight_data["fatigue_detected_at_round"] = fatigue_detected_at
    flight_data["final_trust"] = round(field.trust_watermark, 4)
    flight_data["final_energy"] = field.energy_level.value
    flight_data["total_intentional_violations"] = sum(
        1 for r in flight_data["rounds"] if r["is_intentional"]
    )
    with open(flight_data_path, "w", encoding="utf-8") as f:
        json.dump(flight_data, f, ensure_ascii=False, indent=2)
    print(f"\nFlight data saved to: {flight_data_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
