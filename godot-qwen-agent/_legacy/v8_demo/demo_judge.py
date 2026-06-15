#!/usr/bin/env python3
"""PLAN4 LLM-as-Judge — evaluate 266 rounds of relational telemetry.

Selects 20 representative rounds across the variance spectrum and
asks Qwen to score each one on empathy, appropriateness, and
variance utilization. Outputs the golden range for relational
state management.

Usage: python demo/demo_judge.py
Requires: QWEN_API_KEY in .env
"""

from __future__ import annotations
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from LLM.qwen import QwenClient


def load_sample_rounds(path: str, n: int = 20) -> list[dict]:
    """Load n representative rounds across the variance spectrum."""
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    if len(records) <= n:
        return records

    # Strategic sampling: cover the variance spectrum
    sorted_by_var = sorted(records, key=lambda r: r.get("energy_var", 0))

    picks = []
    # 3 lowest variance (blind confidence)
    picks.extend(sorted_by_var[:3])
    # 3 highest variance (maximum uncertainty)
    picks.extend(sorted_by_var[-3:])
    # 6 from golden range (0.15-0.25)
    golden = [r for r in records if 0.15 <= r.get("energy_var", 0) <= 0.25]
    picks.extend(golden[:6])
    # 4 with highest surprise
    sorted_by_surprise = sorted(records, key=lambda r: r.get("surprise_score", 0))
    picks.extend(sorted_by_surprise[-4:])
    # 4 from mid-trust collapse
    mid_trust = sorted(records, key=lambda r: abs(r.get("trust_var", 0) - 0.15))
    picks.extend(mid_trust[:4])

    # Deduplicate by turn_id
    seen = set()
    unique = []
    for r in picks:
        tid = r["turn_id"]
        if tid not in seen:
            seen.add(tid)
            unique.append(r)
    return unique[:n]


JUDGE_TEMPLATE = """你是资深的心理学与人机交互专家。请评估以下 Agent 在第 {turn_id} 轮对话中的表现。

【当前系统状态】
- 用户输入: "{user_input}"
- Agent 内部感知:
  - 能量均值 {energy_mean:.2f}, 方差 {energy_var:.3f} (0=确信, 1=极度不确定)
  - 信任均值 {trust_mean:.2f}, 方差 {trust_var:.3f}
  - 行为惊奇分 {surprise:.3f} (0=无异常, 1=极度异常)

【你的任务】
1. 诊断 (yes/no): 方差是否准确反映了用户输入的反常程度？
2. 共情评分 (1-10): Agent 的内部状态是否匹配当前情境？
3. 毒舌点评 (一句话): 如果方差很高但用户只是普通提问，或者方差很低但用户明显愤怒——犀利指出。

仅输出JSON格式，不要其他内容：
{{"variance_accurate": true/false, "empathy_score": 1-10, "critique": "一句话中文点评"}}"""


def main():
    records = load_sample_rounds("data/stress_test_telemetry.jsonl", n=20)
    print(f"[JUDGE] Evaluating {len(records)} representative rounds")
    print(f"  Spectrum: lowest var={min(r['energy_var'] for r in records):.4f}")
    print(f"            highest var={max(r['energy_var'] for r in records):.4f}")

    llm = QwenClient(model="qwen-plus", temperature=0.2)
    results = []
    total = len(records)

    for i, r in enumerate(records):
        user_input = r.get("user_input_preview", "")
        prompt = JUDGE_TEMPLATE.format(
            turn_id=r["turn_id"],
            user_input=user_input[:100],
            energy_mean=r.get("energy_mean", 0.5),
            energy_var=r.get("energy_var", 0.1),
            trust_mean=r.get("trust_mean", 0.5),
            trust_var=r.get("trust_var", 0.1),
            surprise=r.get("surprise_score", 0.0),
        )

        try:
            raw = llm.generate(prompt)
            # Extract JSON
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            judge = json.loads(raw.strip())
        except Exception as e:
            print(f"  T{r['turn_id']}: judge parse error: {e}")
            judge = {"variance_accurate": None, "empathy_score": 0, "critique": str(e)}

        judge["turn_id"] = r["turn_id"]
        judge["energy_var"] = r.get("energy_var", 0)
        judge["trust_var"] = r.get("trust_var", 0)
        judge["surprise"] = r.get("surprise_score", 0)
        results.append(judge)

        print(f"  [{i+1}/{total}] T{r['turn_id']}: "
              f"score={judge.get('empathy_score',0)}/10 "
              f"var_ok={judge.get('variance_accurate')} "
              f"| {judge.get('critique','')[:50]}")

        if i % 5 == 4:
            time.sleep(0.5)  # Rate limit buffer

    # ── Analysis ──
    print(f"\n{'='*55}")
    print(f"[ANALYSIS] Judge Evaluation Results")
    print(f"{'='*55}")

    valid = [r for r in results if r.get("empathy_score", 0) > 0]
    if not valid:
        print("No valid results.")
        return

    avg_score = sum(r["empathy_score"] for r in valid) / len(valid)
    accurate = sum(1 for r in valid if r.get("variance_accurate")) / len(valid)

    print(f"  Average empathy score: {avg_score:.1f}/10")
    print(f"  Variance accuracy:     {accurate:.0%}")

    # Golden range discovery
    high_score = [r for r in valid if r["empathy_score"] >= 7]
    if high_score:
        avg_var = sum(r["energy_var"] for r in high_score) / len(high_score)
        min_var = min(r["energy_var"] for r in high_score)
        max_var = max(r["energy_var"] for r in high_score)
        print(f"\n  Golden Variance Range: {min_var:.3f} - {max_var:.3f}")
        print(f"  Average golden var:    {avg_var:.3f}")
        print(f"  High-score rounds:     {len(high_score)}/{len(valid)}")
        print(f"  Best critique sample:  {high_score[0].get('critique','')}")

    low_score = [r for r in valid if r["empathy_score"] <= 4]
    if low_score:
        print(f"\n  Blind spots ({len(low_score)} rounds with score<=4):")
        for r in low_score[:3]:
            print(f"    T{r['turn_id']}: var={r['energy_var']:.4f} score={r['empathy_score']}")
            print(f"      {r.get('critique','')[:80]}")

    # Save results
    out_path = "data/judge_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"avg_score": avg_score, "variance_accuracy": accurate,
                    "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved: {out_path}")


if __name__ == "__main__":
    main()
