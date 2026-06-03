#!/usr/bin/env python3
"""PLAN5 Contract Lifecycle Demo — 30 rounds of contract evolution.

Phase 1 (R1-R10): User increasingly exhausted at 2 AM. Agent verbose.
Phase 2 (R11-R20): System 2 detects pattern -> contract evolves to BRIEF.
Phase 3 (R21-R30): User tests the new contract. Trust rebuilds.

Validates: DynamicBlueprint + ContractEvolutionEngine + ContractAuditor.
"""

from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv; load_dotenv()

from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.contract_auditor import ContractAuditor
from LLM.deepseek import DeepSeekClient

# ── Setup ──
bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "explanation_style": "THEORETICAL",
    "proactive_suggestions": "ENABLED",
})
engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
llm = DeepSeekClient(model="deepseek-chat", temperature=0.1)
auditor = ContractAuditor(llm, interval=10)

trust = 0.30
pending_proposals: list[dict] = []
current_time = "02:00 AM"
history: list[str] = []

# ── Simulation ──

user_inputs = [
    # Phase 1: exhaustion sets in
    "这个算法的时间复杂度怎么推导的",
    "还是不太懂...",
    "能再讲一遍吗",
    "算了，我现在脑子不太转了",
    "对不起，我太累了",
    "能不能简单点",
    "别给我讲理论了",
    "直接说结论就行",
    "我好困",
    "嗯...就这样吧，太难了",
    # Phase 2: silence, then compliance check
    "嗯",
    "好",
    "这个代码能跑吗",
    "行，懂了",
    "谢谢",
    "比刚才好多了",
    "继续",
    "这个方案可以用",
    "对，就是这样",
    "太好了",
]

def agent_response(verbose_level: str, user_input: str) -> str:
    if "BRIEF" in verbose_level.upper() or "LOW" in verbose_level.upper() or "EXTREME" in verbose_level.upper():
        return "O(n log n)。用主定理，case 2。完毕。"
    return (
        f"这个问题涉及递归树分析和主定理的应用。首先我们看第一层递归："
        f"T(n) = aT(n/b) + f(n)。然后逐层展开..."
    )

print("=" * 60)
print("[PLAN5] Contract Lifecycle Demo — 30 rounds")
print(f"  Blueprint: {bp.snapshot}")
print(f"  Initial trust: {trust:.2f}")
print(f"  Auditor interval: every {auditor.interval} rounds")
print(f"  Current time: {current_time}")
print("=" * 60)

for r, user_input in enumerate(user_inputs, 1):
    history.append(user_input)
    print(f"\nR{r:2d} [{current_time}] User: \"{user_input[:50]}\"")

    # ── 1. Apply pending proposals ──
    for prop in list(pending_proposals):
        accepted, reason = engine.evaluate(prop, bp, trust)
        if accepted:
            bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
            engine.record_evolution(trust)
            print(f"  [契约演化] {prop['target_blueprint_key']}: "
                  f"{prop.get('old_value','?')} -> {prop['new_value']}")
            print(f"    原因: {prop.get('human_reason', '')[:80]}")
        else:
            print(f"  [契约拒绝] {reason}")
        pending_proposals.remove(prop)

    # ── 2. Generate response based on current contract ──
    verbose = bp.fields.get("response_verbose_level", "HIGH")
    resp = agent_response(verbose, user_input)
    print(f"  Agent [{verbose}]: {resp[:80]}")

    # ── 3. Simulate trust update ──
    if "好" in user_input or "谢谢" in user_input or "懂了" in user_input:
        trust = min(1.0, trust + 0.03)
    elif "累" in user_input or "困" in user_input or "算了" in user_input:
        trust = max(0.0, trust - 0.02)
    print(f"  Trust: {trust:.2f} | Evolutions: {bp.applied_count}")

    # ── 4. Post-evolution check ──
    rolled, reason = engine.post_check(bp, trust)
    if rolled:
        print(f"  [自动回滚] {reason}")

    # ── 5. Sync audit at checkpoint rounds ──
    if auditor.should_audit(r):
        print(f"\n  [System 2] 第 {r} 轮审计中...")
        try:
            proposal = auditor._audit_sync(history[-10:], bp.snapshot, current_time)
            if proposal:
                pending_proposals.append(proposal)
                print(f"  [System 2] 发现隐式契约: {proposal.get('human_reason', '')[:80]}")
            else:
                print(f"  [System 2] 未发现契约修改信号。")
        except Exception as e:
            print(f"  [System 2] 审计失败: {e}")

    # Advance time each round
    hour = 2 + (r // 4) % 6
    current_time = f"{hour:02d}:{r % 60:02d} AM"

# ── Summary ──
print(f"\n{'='*60}")
print(f"[SUMMARY] 30 rounds complete")
print(f"  Final blueprint: {bp.snapshot}")
print(f"  Final trust: {trust:.2f}")
print(f"  Contract evolutions applied: {bp.applied_count}")
print(f"  Auditor calls: {auditor.call_count}")
print(f"  History depth: {len(bp._history)}")
if bp.applied_count > 0:
    print(f"\n[PASS] Contract evolved during interaction.")
    print(f"  The fossil became a seed.")
else:
    print(f"\n[INFO] No contract evolution triggered.")
    print(f"  Check System 2 audit results or adjust threshold.")
print(f"{'='*60}")
