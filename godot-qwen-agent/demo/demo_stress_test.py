#!/usr/bin/env python3
"""PLAN4 Stress Test — Bayesian variance under pressure.

Simple CLI. Every round records telemetry with mean+variance.
After /quit, prints the variance timeline.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import components.tools.simulated_search  # noqa

from core.adapters.relational_evaluator import RelationalEvaluator
from core.adapters.relational_state_aggregator import RelationalStateAggregator
from core.adapters.relational_inertia import RelationalHistory
from core.adapters.interaction_telemetry import InteractionTelemetry
from core.contracts.relational_field import RelationalField
from core.adapters.event_sink import ContractAwareEventSink
from core.contracts.composition import CompositionBlueprint
from core.adapters.persistence import RelationshipMemoryStore

bp = CompositionBlueprint.from_dict({"version":"1.0.0","lifecycle":"active","default_chunker":"identity"})
field = RelationalField.default()
sink = ContractAwareEventSink()
memory = RelationshipMemoryStore(":memory:")
agg = RelationalStateAggregator()
hist = RelationalHistory()
telem = InteractionTelemetry("data/stress_test_telemetry.jsonl")
recent_lengths: list[int] = []
turn = 0

print("=" * 50)
print("[STRESS TEST] Bayesian Variance Monitor")
print("  Type to chat. /quit to exit.")
print("  After exit, variance timeline will be shown.")
print("=" * 50)

while True:
    try:
        user = input(f"\n[{turn+1}] You: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not user: continue
    if user.lower() in ("/quit","/exit","quit","exit"): break

    turn += 1
    recent_lengths.append(len(user))
    if len(recent_lengths) > 10:
        recent_lengths.pop(0)

    field = RelationalEvaluator.evaluate(user, field)
    ctx = agg.aggregate(field, None, sink, memory, bp.fingerprint, history=hist)

    # Extract behavioral signals (PLAN4 Surprise Detector)
    signals = RelationalEvaluator.extract_behavioral_signals(user, recent_lengths)

    # Smart Decay: calm rounds naturally reduce uncertainty
    hist.decay_variances(signals["surprise_score"])
    hist.apply_baseline_drift(signals["surprise_score"])

    # Bayesian update with surprise injection
    energy_val = 0.2 if field.is_low_energy else (0.8 if field.energy_level.value == "high" else 0.5)
    hist.update_with_surprise("energy_strength", energy_val, signals["surprise_score"])
    hist.update_with_surprise("trust", field.trust_watermark, signals["surprise_score"])

    # Response adaptation based on energy state
    prev_energy = field.energy_level.value
    if field.is_low_energy:
        resp = f"[简约模式] 关于'{user[:15]}...'：核心结论已记录。"
    else:
        resp = (f"[标准模式] 关于'{user[:30]}...'：这是一个详细的回复，"
                f"包含了多个方面的分析。您可以继续追问或换一个话题。")

    # Show state change when it happens
    energy_var = hist.get_variance("energy_strength")
    trust_var = hist.get_variance("trust")
    state_marker = ""
    if energy_var > 0.4:
        state_marker = f" [高方差:{energy_var:.2f}]"
    if hist.is_uncertain():
        state_marker += " [保守模式]"

    print(f"    [{prev_energy}] Assistant{state_marker}: {resp}")

    telem.log_turn(
        turn_id=turn,
        energy_mean=hist.get_mean("energy_strength"),
        energy_var=energy_var,
        trust_mean=hist.get_mean("trust"),
        trust_var=trust_var,
        is_uncertain=hist.is_uncertain(),
        response_len=len(resp),
        user_input_preview=user.encode("utf-8", errors="replace").decode("utf-8")[:60],
        behavioral_signals=signals,
        surprise_score=signals["surprise_score"],
    )

# Summary
print("\n" + "=" * 50)
print("[VARIANCE TIMELINE]")
records = telem.read_all()
for r in records:
    flag = " ⚡ HIGH VARIANCE" if r["is_uncertain"] else ""
    print(f"  T{r['turn_id']}: energy(mean={r['energy_mean']:.2f}, var={r['energy_var']:.3f})  "
          f"trust(mean={r['trust_mean']:.2f}, var={r['trust_var']:.3f}){flag}")
print(f"\nTotal rounds: {len(records)}")
print(f"Data saved: {telem.path}")
