#!/usr/bin/env python3
"""Phase 28 Demo — PLAN1 vs PLAN2: Embodied Reflex.

Same tool calls. Two different experiences.

PLAN1 (old): User sees "Calling web_search...", "Calling brave_search..."
PLAN2 (new): User sees "(Intuition: I recall several key points...)"

Same backend. Different frontend. This is Axiom 1:
"Tech Recesses, Relation Emerges."
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401

from core.adapters.embodied_reflex import EmbodiedReflex
from core.adapters.tool_adapter import ToolAdapter
from core.contracts.composition import CompositionBlueprint
from core.contracts.tool import ToolCall


def main():
    bp = CompositionBlueprint.from_dict({
        "version": "1.0.0", "lifecycle": "active",
        "default_chunker": "identity",
    })
    adapter = ToolAdapter(blueprint=bp)
    reflex = EmbodiedReflex()

    queries = [
        ("量子计算最新进展", "web_search"),
        ("明天的天气怎么样", "weather_api"),
        ("回忆用户偏好", "brave_search"),
    ]

    total = passed = 0
    def check(cond, label):
        nonlocal total, passed
        total += 1; passed += 1 if cond else 0
        print(f"  {'[OK]' if cond else '[FAIL]'} {label}")

    print("=" * 60)
    print("[EMBODIED] Phase 28: PLAN1 vs PLAN2 — Embodied Reflex")
    print("=" * 60)

    for intent, tool_name in queries:
        print(f"\n{'─'*60}")
        print(f"User: '帮我查一下{intent}'")

        # ── PLAN1: Raw ToolCall display ──
        tc = ToolCall(tool_name=tool_name, parameters={"query": intent})
        result = adapter.execute(tc)

        print(f"\n  PLAN1 (Old Paradigm):")
        if result.success:
            print(f"  [Calling {tool_name}...]")
            print(f"  [Result received: {str(result.data)[:80]}...]")
        else:
            print(f"  [Calling {tool_name}...]")
            print(f"  [ERROR: {result.error}]")

        # ── PLAN2: Embodied Reflex ──
        print(f"\n  PLAN2 (Embodied Reflex):")
        intuition = reflex.process(result, user_intent=intent)
        print(f"  {intuition}")

        check(len(intuition) > 0, f"Intuition generated for '{intent}'")
        check("web_search" not in intuition, f"No raw tool name in intuition")
        check("brave_search" not in intuition, f"No raw tool name exposed")

    # ── Intentional violation in PLAN2 ──
    print(f"\n{'─'*60}")
    print(f"User: '今天好累，简单总结一下量子计算就行'")

    fatigue_result = ToolAdapter(blueprint=bp).execute(
        ToolCall(tool_name="web_search", parameters={"query": "量子计算简介"})
    )
    # Simulate a deliberate skip: Agent detects fatigue, marks as intentional
    from core.contracts.composition import ContractViolation
    from core.contracts.tool import ToolResult as TR
    intentional_result = TR(
        call_id="embodied_test",
        tool_name="web_search",
        success=True,
        data={"summary": "量子计算使用量子比特进行计算"},
        contract_violation=ContractViolation.INTENTIONAL_VIOLATION,
        higher_value_reason="User fatigue; kept it minimal",
    )

    print(f"\n  PLAN2 (Embodied + Intentional):")
    intuition2 = reflex.process(intentional_result, user_intent="量子计算简介")
    print(f"  {intuition2}")
    check("fatigue" in intuition2.lower() or "kept it brief" in intuition2.lower(),
          "Intentional override reflected in intuition")

    # ── Failure intuition ──
    print(f"\n{'─'*60}")
    print(f"User: '用 google_search 搜一下量子纠错'")

    hallucination_result = adapter.execute(
        ToolCall(tool_name="google_search", parameters={"query": "量子纠错"})
    )
    print(f"\n  PLAN2 (Failure -> Graceful Intuition):")
    intuition3 = reflex.process(hallucination_result, user_intent="量子纠错")
    print(f"  {intuition3}")
    check("couldn't" in intuition3.lower() or "pause" in intuition3.lower(),
          "Failure presented as intuition gap, not error")

    print(f"\n{'='*60}")
    print(f"[RESULT] {passed}/{total} checks passed")
    if passed == total:
        print("[PASS] Embodied Reflex VERIFIED.")
        print("  PLAN1: User sees tool calls (tech exposed)")
        print("  PLAN2: User feels intuition   (tech recessed)")
    else:
        print("[WARN] Some checks failed.")
    print(f"{'='*60}")

    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
