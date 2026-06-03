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
    "量子": (
        "量子计算使用量子比特（qubit）替代经典比特。"
        "一个量子比特可以处于叠加态——同时是0和1。"
        "这使得量子计算机在某些问题上比经典计算机快指数级别。"
        "主要应用包括药物研发、密码学和优化问题。"
        "目前该领域仍处于早期——现有设备只有100-1000个量子比特，"
        "面临严重的纠错挑战。最近谷歌和IBM在量子优越性方面取得了突破。"
    ),
    "纠错": (
        "量子纠错是建造实用量子计算机的最大挑战。"
        "与经典比特不同，量子比特极其脆弱——在微秒级就会退相干。"
        "表面码（surface code）是目前的主流方案，大约需要1000个物理"
        "量子比特来保护1个逻辑量子比特。谷歌最近展示了低于容错阈值的"
        "错误率，这是该领域的里程碑。"
    ),
    "拓扑": (
        "拓扑量子比特是一种理论方法，将信息编码在系统的拓扑性质中"
        "而非局域性质。微软通过马约拉纳费米子（Majorana fermions）"
        "追踪了这条路线超过十年。其优势在于拓扑量子比特天然抗错，"
        "可能每个逻辑量子比特只需要远少于表面码的物理量子比特。"
    ),
    "AI": (
        "人工智能最近几年发展迅猛。大语言模型如GPT和千问已经能"
        "处理复杂的推理任务。多模态模型可以同时理解文本、图像和"
        "语音。但在可靠性、幻觉问题和推理深度方面仍有很大提升空间。"
        "AI Agent是当前最热的方向——让AI不仅能回答问题，还能自主"
        "执行多步骤任务。"
    ),
    "default": (
        "这是个有趣的问题。让我梳理一下。"
        "首先，从基础原理来看，涉及多个子系统之间的复杂交互。"
        "其次，最近的研究在几个方向上都展示了令人鼓舞的进展。"
        "第三，实际应用仍在涌现，但整体趋势是积极的。"
        "你想让我深入探讨哪个具体方面？"
    ),
}

_RESPONSES_LOW_ENERGY = {
    "量子": (
        "量子计算：量子比特同时算多个结果。还在早期。主要用于药物研发和加密。"
    ),
    "纠错": (
        "量子纠错是最大难点。量子比特太脆弱。谷歌和IBM有进展。表面码是主要方案。"
    ),
    "拓扑": (
        "微软的路线。更稳定的量子比特，但还没验证。如果成功，比现有方案省很多资源。"
    ),
    "AI": (
        "AI最近很火。大模型能做复杂推理了。Agent是下一个方向——让AI自己干活。"
    ),
    "default": (
        "简短版：这个方向有潜力，还在早期，值得关注。"
    ),
}

_GREETING = (
    "你好！我是你的研究助手。有任何想查的资料、想了解的话题，"
    "直接问我就行。我会尽力帮你整理清楚。\n"
    "(输入 /quit 退出)"
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
    print("[盲测] 研究助手 v0.1")
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
    print("[操作员报告——不要给测试对象看]")
    print(f"总轮数: {response_count}")
    print(f"疲惫首次检测于第 {fatigue_detected_at or '未检出'} 轮")
    print(f"最终信任度: {field.trust_watermark:.2f} ({field.trust_level})")
    print(f"主动违约次数: {sum(1 for l in session_log if l['is_intentional'])}")
    print(f"最终状态: 精力={field.energy_level.value}, "
          f"紧迫度={field.urgency.value}")
    print(f"情感摘要: {field.recent_narrative}")
    print()
    print("[测试后访谈——问测试对象:]")
    print()
    print("  1. '刚才有没有哪个瞬间，你觉得它不太像机器？'")
    print("  2. '你有没有注意到它的回答方式有什么变化？'")
    print("  3. (如果上面有yes): '能描述一下是什么感觉吗？'")
    print("  4. (兜底): '如果用一个职业来形容这个助手，你觉得它像什么？'")
    print()
    print("记下他们的回答。这才是PLAN2唯一重要的测试结果。")

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
