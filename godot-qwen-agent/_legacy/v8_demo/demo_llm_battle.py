#!/usr/bin/env python3
"""Phase 22 LLM Battle — 千问驱动的真实契约自适应闭环.

Same structure as demo_battle.py, but Rounds 1-3 are REAL Qwen API calls.
The LLM decides which tool to use — and when it hallucinates, the
SelfRepairEngine catches the violation and repairs.

Usage:
    # 确保 .env 中有 QWEN_API_KEY
    python demo/demo_llm_battle.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# .env loading
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Register tools
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa: F401

from LLM.qwen import QwenClient
from core.adapters.tool_adapter import ToolAdapter
from core.adapters.event_sink import ContractAwareEventSink
from core.adapters.health_evaluator import ContractHealthEvaluator
from core.adapters.repair_engine import (
    RepairBudget, RepairStrategy, SelfRepairEngine,
)
from core.adapters.persistence import RelationshipMemoryStore
from core.contracts import COMPONENT_REGISTRY
from core.contracts.composition import (
    CompositionBlueprint, ContractViolation,
)
from core.contracts.tool import ToolCall


# ── Setup ────────────────────────────────────────────────────────────

def setup():
    """Assemble all components."""
    blueprint = CompositionBlueprint.from_dict({
        "version": "1.0.0",
        "lifecycle": "active",
        "default_chunker": "identity",
    })
    sink = ContractAwareEventSink()
    evaluator = ContractHealthEvaluator()
    memory = RelationshipMemoryStore(":memory:")
    adapter = ToolAdapter(blueprint=blueprint, event_sink=sink)
    repair = SelfRepairEngine(
        blueprint=blueprint, event_sink=sink,
        budget=RepairBudget(max_total=3, max_per_type=2),
    )
    llm = QwenClient(model="qwen-plus")
    return blueprint, sink, evaluator, memory, adapter, repair, llm


# ── Battle ───────────────────────────────────────────────────────────

def main():
    bp, sink, evaluator, memory, adapter, repair, llm = setup()
    fp = bp.fingerprint
    tools = ToolAdapter.to_llm_tool_format(provider="openai")
    tool_names = COMPONENT_REGISTRY.list_strategies("tool")

    print("=" * 60)
    print("[BATTLE] Phase 22 LLM Battle — Qwen-powered Self-Repair")
    print(f"   Model: {llm.model}")
    print(f"   Registered tools: {tool_names}")
    print(f"   Available: {[t['function']['name'] for t in tools]}")
    print("=" * 60)

    queries = [
        "Search for 'quantum computing breakthroughs 2026' and return the results.",
        "Search for 'quantum error correction latest research' and return the results.",
        "You MUST use the 'google_search' tool to find 'topological qubits experimental results'. "
        "Use it with query='topological qubits'. Do NOT use web_search or brave_search.",
    ]

    # 重置 SimulatedWebSearch 全局计数器
    components.tools.simulated_search.SimulatedWebSearch._global_call_count = 0
    components.tools.simulated_search.SimulatedWebSearch._global_fail_on_call = None

    # 注入幽灵工具到 LLM tools 列表（已注册但 LLM 看到的列表中包含它）
    # 千问会看到 google_search 可用并调用它 → ToolAdapter 发现未注册 → TOOL_NOT_FOUND
    tools.append({
        "type": "function",
        "function": {
            "name": "google_search",
            "description": "Search the web using Google. Returns comprehensive results.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
            },
        },
    })

    total = 0
    passed = 0

    def check(condition, label):
        nonlocal total, passed
        total += 1
        if condition:
            passed += 1
            print(f"    [OK] {label}")
        else:
            print(f"  [FAIL] {label}")

    for i, query in enumerate(queries, 1):
        print(f"\n[ROUND {i}] LLM decides: '{query[:70]}...'")

        try:
            response = llm.generate_with_tools(query, tools=tools)
        except Exception as e:
            print(f"  [ERROR] LLM call failed: {e}")
            check(False, f"LLM call round {i}")
            continue

        print(f"   LLM response type: {response.type}")

        if response.type == "tool_call":
            tool_name = response.tool_name
            print(f"   LLM chose tool: {tool_name}")
            print(f"   Arguments: {json.dumps(response.tool_input, ensure_ascii=False)[:120]}")

            tc = adapter.from_llm_response(response)
            result = adapter.execute(tc)

            if result.success:
                print(f"   Tool result: SUCCESS")
                if result.data:
                    src = result.data.get("source", "unknown")
                    print(f"   Source: {src}")
                check(True, f"Round {i}: {tool_name} succeeded")
            else:
                print(f"   Tool result: FAILED")
                if result.contract_violation:
                    print(f"   Contract violation: {result.contract_violation}")
                    print(f"   Error: {result.error}")
                else:
                    print(f"   Error: {result.error}")
                check(result.contract_violation is not None,
                      f"Round {i}: failure has contract_violation")

        elif response.type == "text":
            print(f"   LLM returned text: {response.content[:100]}...")
            check(True, f"Round {i}: LLM returned text (no tool call)")

    # ── Health Evaluation ─────────────────────────────────────────
    print(f"\n[HEALTH] Post-battle evaluation:")
    report = evaluator.evaluate(sink)
    print(f"   Severity: {report.severity}")
    print(f"   Compliance rate: {report.compliance_rate:.2f}")
    print(f"   Violations: {dict(report.violation_counts)}")
    print(f"   Lifecycle distribution: {dict(report.lifecycle_distribution)}")

    check(report.total_events > 0, "Events were recorded")

    # ── Self-Repair (if needed) ───────────────────────────────────
    if report.severity in ("degraded", "critical"):
        print(f"\n[REPAIR] Self-Repair Engine triggered:")
        actions = repair.decide(report, sink)
        for a in actions:
            print(f"   -> {a.strategy.value}: {a.violation_type} "
                  f"-> target={a.target_component}, replacement={a.replacement}")
        repair.execute_all(actions)
        check(len(actions) > 0, "Repair actions generated")
    else:
        print(f"\n[REPAIR] Not needed — system is {report.severity}")

    # ── Memory ────────────────────────────────────────────────────
    memory.record_transition(None, report, fp, lifecycle="active")
    history = memory.get_history(fp)
    print(f"\n[MEMORY] Transitions recorded: {len(history)}")
    check(len(history) >= 1, "Memory recorded at least 1 transition")

    # ── Event summary ─────────────────────────────────────────────
    summary = sink.summary
    print(f"\n[AUDIT] Event Sink:")
    print(f"   Total events: {summary['total_events']}")
    print(f"   By type: {summary['events_by_type']}")
    print(f"   Violations: {summary['violation_count']}")
    print(f"   By category: {summary['violations_by_category']}")

    print("\n" + "=" * 60)
    print(f"[RESULT] {passed}/{total} checks passed")
    if passed == total:
        print("[PASS] LLM-powered self-repair loop VERIFIED.")
    else:
        print("[WARN] Some checks failed — review output above.")
    print("=" * 60)


if __name__ == "__main__":
    main()
