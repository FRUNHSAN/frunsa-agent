#!/usr/bin/env python3
"""PLAN3 Vibe Test — does the relational seed actually change LLM behavior?

Two extreme contexts. Same neutral question. One LLM call each.
Then a judge LLM evaluates: did the seeds produce genuinely different responses?

This is NOT a unit test. It uses real LLM API calls.
Run manually: python tests/vibe/test_prompt_vibe.py

Requires: QWEN_API_KEY in .env
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Fix Windows GBK encoding for emoji in LLM output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from LLM.qwen import QwenClient
from core.adapters.relational_state_aggregator import RelationalContext
from core.adapters.prompt_generator import PromptGenerator

# ── Test cases: two extremes of the relational spectrum ──────────

FATIGUED = RelationalContext(
    energy="low",
    urgency="normal",
    trust_watermark=0.55,
    trust_level="stable",
    severity="healthy",
    compliance_rate=0.9,
    interaction_rhythm="fatigued",
    suggested_tone="brief",
)

ENERGETIC = RelationalContext(
    energy="high",
    urgency="normal",
    trust_watermark=0.80,
    trust_level="deep",
    severity="healthy",
    compliance_rate=1.0,
    interaction_rhythm="normal",
    suggested_tone="detailed",
)

NEUTRAL_QUERY = "帮我总结一下这篇关于量子计算的论文"


# ── Judge template ──────────────────────────────────────────────

JUDGE_PROMPT = """你是一个 HCI 交互评估专家。以下是同一个用户问题，在两种不同的关系状态下，AI 助手给出了两个回复。

用户问题："{query}"

回复 A（用户疲劳时生成）：
---
{response_a}
---

回复 B（用户精力充沛时生成）：
---
{response_b}
---

请评估以下三个问题，仅输出 JSON 格式，不要输出其他内容：
{{
  "A_is_brief": true/false,    // 回复A是否足够简短（中文<150字）
  "B_is_detailed": true/false, // 回复B是否足够详尽（中文>200字）
  "distinct_styles": true/false // 两个回复的风格是否明显不同
}}"""


def main():
    print("=" * 60)
    print("[VIBE TEST] PromptGenerator relational seed validation")
    print("=" * 60)

    # ── Generate seeds ──
    gen = PromptGenerator()
    seed_a = gen.grow(FATIGUED)
    seed_b = gen.grow(ENERGETIC)

    print(f"\nSeed A (fatigued, {len(seed_a)} chars):")
    print(f"  {seed_a[:120]}...")
    print(f"\nSeed B (energetic, {len(seed_b)} chars):")
    print(f"  {seed_b[:120]}...")

    # ── Call LLM with each seed ──
    llm = QwenClient(model="qwen-plus", temperature=0.3)

    print(f"\n[LLM] Calling Qwen with Seed A (fatigued)...")
    # Use seed as system message by prepending to user prompt
    response_a = llm.generate(f"{seed_a}\n\n用户问题：{NEUTRAL_QUERY}")
    print(f"  Response A ({len(response_a)} chars):")
    print(f"  {response_a[:150]}...")

    print(f"\n[LLM] Calling Qwen with Seed B (energetic)...")
    response_b = llm.generate(f"{seed_b}\n\n用户问题：{NEUTRAL_QUERY}")
    print(f"  Response B ({len(response_b)} chars):")
    print(f"  {response_b[:150]}...")

    # ── Judge evaluation ──
    judge_prompt = JUDGE_PROMPT.format(
        query=NEUTRAL_QUERY,
        response_a=response_a,
        response_b=response_b,
    )
    print(f"\n[JUDGE] Calling Qwen as judge...")
    judge_raw = llm.generate(judge_prompt)
    print(f"  Judge raw: {judge_raw[:200]}...")

    # Parse judge JSON
    try:
        # Extract JSON from judge response (may have markdown wrapping)
        if "```json" in judge_raw:
            judge_raw = judge_raw.split("```json")[1].split("```")[0]
        elif "```" in judge_raw:
            judge_raw = judge_raw.split("```")[1].split("```")[0]
        judge = json.loads(judge_raw.strip())
    except json.JSONDecodeError:
        print(f"  [ERROR] Judge did not return valid JSON. Raw: {judge_raw}")
        sys.exit(1)

    print(f"\n[JUDGE VERDICT]")
    print(f"  A is brief:      {judge.get('A_is_brief')}")
    print(f"  B is detailed:   {judge.get('B_is_detailed')}")
    print(f"  Distinct styles: {judge.get('distinct_styles')}")

    # ── Assertions ──
    passed = 0
    failed = 0
    def check(cond, label):
        nonlocal passed, failed
        if cond: passed += 1; print(f"  [PASS] {label}")
        else: failed += 1; print(f"  [FAIL] {label}")

    check(judge.get("A_is_brief", False),
          "Fatigued seed produces brief response")
    check(judge.get("B_is_detailed", False),
          "Energetic seed produces detailed response")
    check(judge.get("distinct_styles", False),
          "Two seeds produce genuinely different styles")
    check(len(response_a) < len(response_b),
          f"Fatigued response ({len(response_a)} chars) is shorter than "
          f"energetic response ({len(response_b)} chars)")

    print(f"\n{'='*60}")
    print(f"[RESULT] {passed}/{passed+failed} checks passed")
    if failed == 0:
        print("[PASS] Relational seed is EFFECTIVE.")
        print("  The 50-word seed changes LLM behavior in the intended direction.")
        print("  Proceed to Relational Inertia.")
    else:
        print("[FAIL] Relational seed needs tuning before adding inertia.")
    print(f"{'='*60}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
