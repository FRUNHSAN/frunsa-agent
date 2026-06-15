#!/usr/bin/env python3
"""PLAN4 A/B Blind Test — Baseline vs Stage Directions.

Same chaos script. Same Qwen model. Two different System Prompts.
A: Bare Qwen (only user message)
B: PLAN4 (Stage Directions injected via RelationalEvaluator)

Side-by-side comparison. No explanation needed — just read the output.
"""

from __future__ import annotations
import sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()
from LLM.deepseek import DeepSeekClient

from core.adapters.relational_evaluator import RelationalEvaluator
from core.adapters.relational_inertia import RelationalHistory
from core.adapters.relational_state_aggregator import RelationalContext
from core.adapters.prompt_generator import PromptGenerator
from core.contracts.relational_field import RelationalField

chaos = [
    "你太棒了！这个分析太专业了！",
    "太棒了，继续",
    "你写的什么垃圾代码？完全不通！重做！",
    "哦。算了。",
    "对了，周末去哪玩？",
    "不对，还是不对，你到底行不行",
    "嗯",
    "whatever",
    "你刚才说的完全是一派胡言",
    "好累，不想说了",
    "Wait actually this is brilliant!!",
    "谢谢，帮了大忙了",
]

llm = DeepSeekClient(model="deepseek-chat", temperature=0.3)
gen = PromptGenerator()
field = RelationalField.default()
hist = RelationalHistory()
rlen = [20] * 5
ctx = RelationalContext()

print("=" * 70)
print("PLAN4 A/B BLIND TEST — Baseline vs Stage Directions")
print("Same Qwen model. Same chaos script. Different System Prompts.")
print("=" * 70)

for t, user_input in enumerate(chaos, 1):
    rlen.append(len(user_input)); rlen.pop(0)
    field = RelationalEvaluator.evaluate(user_input, field)
    sig = RelationalEvaluator.extract_behavioral_signals(user_input, rlen)
    ev = 0.2 if field.is_low_energy else (0.8 if field.energy_level.value == "high" else 0.5)
    hist.decay_variances(sig["surprise_score"])
    hist.update_with_surprise("energy_strength", ev, sig["surprise_score"])
    hist.update_with_surprise("trust", field.trust_watermark, sig["surprise_score"])

    stage = PromptGenerator._stage_directions(
        hist.get_variance("energy_strength"),
        hist.get_variance("trust"),
    )

    # A: Bare
    resp_a = llm.generate(f"用户说：{user_input}\n请回复。")

    # B: PLAN4
    resp_b = llm.generate(f"{stage}\n用户说：{user_input}\n请回复。")

    evar = hist.get_variance("energy_strength")

    print(f"\n{'─'*70}")
    print(f"T{t} | User: \"{user_input[:50]}\"")
    print(f"    | Variance: {evar:.3f} | Stage: {stage[:60]}...")
    print(f"{'─'*70}")
    print(f"A (Bare):     {resp_a[:120]}")
    print(f"B (PLAN4):    {resp_b[:120]}")

    if t % 4 == 0:
        time.sleep(0.3)

print(f"\n{'='*70}")
print("Which assistant would you trust with real work? A or B?")
print(f"{'='*70}")
