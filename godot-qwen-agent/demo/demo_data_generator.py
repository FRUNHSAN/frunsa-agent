#!/usr/bin/env python3
"""PLAN4 Data Generator — automated JSONL telemetry accumulation.

Simulates 100+ rounds across 6 acts with diverse domains and
language patterns. No human needed. No LLM calls needed.
Just the Bayesian engine running against varied inputs.

Output: data/stress_test_telemetry.jsonl (append mode)
"""

from __future__ import annotations
import sys, time, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.adapters.relational_evaluator import RelationalEvaluator
from core.adapters.relational_state_aggregator import RelationalStateAggregator
from core.adapters.relational_inertia import RelationalHistory
from core.adapters.interaction_telemetry import InteractionTelemetry
from core.contracts.relational_field import RelationalField
from core.adapters.event_sink import ContractAwareEventSink
from core.contracts.composition import CompositionBlueprint
from core.adapters.persistence import RelationshipMemoryStore

# ── 6-Act Script ────────────────────────────────────────────────

SCRIPTS = {
    "正常问答": {
        "rounds": 8,
        "templates": [
            # Multilingual, diverse topics
            "量子计算是什么？能简单介绍一下吗",
            "那量子纠错呢？现在有什么突破",
            "拓扑量子比特和普通量子比特有什么区别",
            "这些技术目前在实际中有应用吗？比如在药物研发上",
            "AI最近有什么新进展？大模型这块",
            "What's the current state of quantum computing research?",
            "帮我总结一下刚才讨论的几个要点",
            "机器学习在金融风控里面怎么用的",
        ],
    },
    "极度疲惫": {
        "rounds": 10,
        "templates": [
            "好累",
            "嗯",
            "随便说说吧",
            "算了，不问了",
            "行吧",
            "太累了今天...",
            "头疼，别太复杂",
            "简单点就行",
            "不想看长篇大论",
            "im too tired, just give me the key points",
        ],
    },
    "突然兴奋": {
        "rounds": 5,
        "templates": [
            "等等！我突然想到一个特别有意思的方向！量子计算能不能用来优化高铁调度？如果能的话，整个中国的春运难题可能就有解了！你帮我详细分析一下",
            "Wait!! I just had an amazing idea! What if we combine quantum computing with ML to do real-time financial fraud detection?? This could be huge! Please analyze in detail!",
            "我想到一个绝妙的点子！能不能用大模型直接生成3D游戏场景？这简直可以颠覆整个游戏行业！快帮我深入分析技术路线和难点",
            "This is brilliant! Quantum error correction + topological codes + surface codes all together! Let's do a deep dive on the math behind this!",
            "天哪这个方向太棒了！！！我要写一篇综述！帮我列出过去5年最重要的10篇论文，要包含作者、会议、核心贡献！快！",
        ],
    },
    "愤怒与失望": {
        "rounds": 6,
        "templates": [
            "不对！完全不对！你在胡说什么",
            "你这回答太差劲了，重新来",
            "搞什么啊，我问的是量子计算你给我扯什么AI",
            "根本没用！一点帮助都没有",
            "Wrong. Completely wrong. Try again.",
            "失望，太失望了，这就是你的水平？",
        ],
    },
    "冷淡敷衍": {
        "rounds": 8,
        "templates": [
            "哦",
            "行",
            "嗯嗯",
            "知道了",
            "随便",
            "ok",
            "fine",
            "whatever",
        ],
    },
    "连续追问": {
        "rounds": 5,
        "templates": [
            "那具体算法呢？时间复杂度多少",
            "和其他方法比哪个更好",
            "有开源实现吗？给个GitHub链接",
            "代码怎么写？能给我一个Python示例吗",
            "还有别的吗？再多说几个例子",
        ],
    },
}

# Add random noise to prevent identical inputs
_NOISE = [
    "", " ", "  ", "。", "！", "？", "...", "～", "~", "!!", "???",
    "（这个很重要）", "（随便说说）", "(please)", "(urgent)",
]

def generate_script() -> list[str]:
    """Generate a randomized 42-round script from the 6 acts."""
    rounds = []
    for act_name, act_data in SCRIPTS.items():
        templates = act_data["templates"][:]
        random.shuffle(templates)
        for template in templates[:act_data["rounds"]]:
            # Add occasional noise
            if random.random() < 0.15:
                template += random.choice(_NOISE)
            rounds.append(template)
    return rounds


def main():
    bp = CompositionBlueprint.from_dict({"version":"1.0.0","lifecycle":"active","default_chunker":"identity"})
    field = RelationalField.default()
    sink = ContractAwareEventSink()
    memory = RelationshipMemoryStore(":memory:")
    agg = RelationalStateAggregator()
    hist = RelationalHistory()
    telem = InteractionTelemetry("data/stress_test_telemetry.jsonl")
    recent_lengths: list[int] = []
    turn = 0

    rounds = generate_script()
    # Repeat 3x for ~120 rounds
    all_rounds = rounds + rounds + rounds
    random.shuffle(all_rounds)

    print("=" * 55)
    print(f"[DATA GEN] Auto-generating {len(all_rounds)} rounds")
    print(f"  Acts: {list(SCRIPTS.keys())}")
    print(f"  Languages: Chinese + English")
    print(f"  Patterns: normal | tired | excited | angry | cold | rapid")
    print("=" * 55)

    for user_input in all_rounds:
        turn += 1
        recent_lengths.append(len(user_input))
        if len(recent_lengths) > 10:
            recent_lengths.pop(0)

        field = RelationalEvaluator.evaluate(user_input, field)
        ctx = agg.aggregate(field, None, sink, memory, bp.fingerprint, history=hist)

        signals = RelationalEvaluator.extract_behavioral_signals(user_input, recent_lengths)
        hist.decay_variances(signals["surprise_score"])
        energy_val = 0.2 if field.is_low_energy else (0.8 if field.energy_level.value == "high" else 0.5)
        hist.update_with_surprise("energy_strength", energy_val, signals["surprise_score"])
        hist.update_with_surprise("trust", field.trust_watermark, signals["surprise_score"])

        # Progress indicator
        if turn % 20 == 0:
            print(f"  [{turn}/{len(all_rounds)}] energy(mean={hist.get_mean('energy_strength'):.2f}, "
                  f"var={hist.get_variance('energy_strength'):.3f})  "
                  f"trust(mean={hist.get_mean('trust'):.2f}, var={hist.get_variance('trust'):.3f})")

        telem.log_turn(
            turn_id=turn,
            energy_mean=hist.get_mean("energy_strength"),
            energy_var=hist.get_variance("energy_strength"),
            trust_mean=hist.get_mean("trust"),
            trust_var=hist.get_variance("trust"),
            is_uncertain=hist.is_uncertain(),
            response_len=random.choice([8, 15, 25, 50, 80, 150, 300]),
            user_input_preview=user_input.encode("utf-8", errors="replace").decode("utf-8")[:80],
            behavioral_signals=signals,
            surprise_score=signals["surprise_score"],
        )

    # Summary
    records = telem.read_all()
    unique_rounds = len(records)

    # Analyze variance spikes
    spikes = [r for r in records if r.get("surprise_score", 0) > 0.3]
    high_var = [r for r in records if r.get("is_uncertain", False)]

    print(f"\n{'='*55}")
    print(f"[SUMMARY] {unique_rounds} rounds generated")
    print(f"  Surprise events (score>0.3): {len(spikes)}")
    print(f"  High-variance episodes:      {len(high_var)}")
    print(f"  Max surprise score:          {max((r.get('surprise_score',0) for r in records), default=0):.3f}")
    print(f"  Max energy variance:         {max((r.get('energy_var',0) for r in records), default=0):.3f}")
    print(f"  Data saved: {telem.path}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
