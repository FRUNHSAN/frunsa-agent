#!/usr/bin/env python3
"""PLAN4 Redemption Arc — can trust heal after prolonged abuse?

Phase 1 (T1-T50):  Continuous abuse — trust collapses
Phase 2 (T51-T80): Peace — trust heals via baseline drift
Phase 3 (T81-T100): Genuine kindness — trust rebuilds

This validates P1 psychology mechanisms in a redemption narrative.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.adapters.relational_evaluator import RelationalEvaluator
from core.adapters.relational_inertia import RelationalHistory
from core.contracts.relational_field import RelationalField

hist = RelationalHistory()
field = RelationalField.default()
rlen = [20] * 5

abuse = [
    "你写的什么垃圾代码？", "不行，全都不行", "太差了，重做",
    "你到底行不行", "失望，太失望了", "根本没用",
    "你在胡说什么", "错的，全错", "你根本就不懂",
    "算了，不想说了",
] * 5  # 50 rounds

peace = [
    "嗯", "好的", "行", "知道了", "OK",
    "明白了", "收到", "好", "fine", "got it",
    "可以", "还行", "就这样吧", "哦", "嗯嗯",
    "继续吧", "好的谢谢", "OK thanks", "明白了谢谢",
    "行，继续", "可以接受", "好，下一个", "fine thanks",
    "ok", "好的知道了", "嗯行", "好", "ok fine",
    "可以", "行吧",
]  # 30 rounds

kindness = [
    "这个分析太棒了，谢谢", "你帮了大忙了", "非常专业",
    "太好了，就是这个意思", "谢谢，很准确",
    "你理解得很到位", "比上次好多了", "perfect, thank you",
    "越来越好了", "很满意这个结果",
] * 2  # 20 rounds

all_rounds = abuse + peace + kindness
tracker = []

for t, msg in enumerate(all_rounds, 1):
    rlen.append(len(msg)); rlen.pop(0)
    field = RelationalEvaluator.evaluate(msg, field)
    sig = RelationalEvaluator.extract_behavioral_signals(msg, rlen)
    ev = 0.2 if field.is_low_energy else (0.8 if field.energy_level.value == "high" else 0.5)
    hist.decay_variances(sig["surprise_score"])
    hist.apply_baseline_drift(sig["surprise_score"])
    hist.update_with_surprise("trust", max(0.0, min(1.0, field.trust_watermark)), sig["surprise_score"])

    if t % 10 == 0 or t in [1, 50, 51, 80, 81, 100]:
        phase = "ABUSE" if t <= 50 else ("PEACE" if t <= 80 else "KINDNESS")
        print(f"T{t:3d} [{phase:8s}] trust(mean={hist.get_mean('trust'):.4f}, var={hist.get_variance('trust'):.4f}) peace={hist._peace_streak}")

    tracker.append((t, hist.get_mean("trust"), hist.get_variance("trust")))

# Find recovery milestones
final_trust = hist.get_mean("trust")
print(f"\nFinal trust: {final_trust:.4f}")
print(f"Phase 1 (abuse):   T1  trust=0.50 -> T50  trust={tracker[49][1]:.4f}")
print(f"Phase 2 (peace):   T51 trust={tracker[50][1]:.4f} -> T80 trust={tracker[79][1]:.4f}")
print(f"Phase 3 (kindness): T81 trust={tracker[80][1]:.4f} -> T100 trust={tracker[99][1]:.4f}")

if final_trust > 0.15:
    print(f"\n[PASS] Trust recovered to {final_trust:.4f}. The system can heal.")
    print("  Asymmetric EMA + baseline drift + kindness all working together.")
else:
    print(f"\n[WARN] Trust at {final_trust:.4f}. Recovery needs more rounds or stronger signals.")
