#!/usr/bin/env python3
"""PLAN5 Live — production interactive loop.

Run: python run_live.py [user_id]

Every round:
  bp.tick() -> evaluate input -> apply proposals -> LLM response -> System2 audit -> persist

Exit: /quit or Ctrl+C
"""

from __future__ import annotations
import sys, json, threading, io
from datetime import datetime
from pathlib import Path

# Windows console encoding fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv; load_dotenv()
from LLM.deepseek import DeepSeekClient
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.contract_auditor import ContractAuditor

uid = sys.argv[1] if len(sys.argv) > 1 else "default"
base = str(Path(__file__).resolve().parent / "user_profiles")
print(f"Loading profile: {uid} (storage: {base})")

profile = UserProfile.load(uid, storage_path=base)
bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "execution_autonomy": "ASK_FIRST",
    "proactive_suggestions": "ENABLED",
    "explanation_style": "THEORETICAL",
})
engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
llm = DeepSeekClient(model="deepseek-chat", temperature=0.7)
auditor = ContractAuditor(llm, interval=10)

trust = 0.30
round_count = 0
pending: list[dict] = []

print("=" * 50)
print(f"PLAN5 Live — {uid}")
print(f"  blueprint: {bp.snapshot}")
print(f"  trust: {trust:.2f}")
print(f"  sessions: {profile.session_count}")
print("  /quit to exit")
print("=" * 50)

while True:
    # ── 1. Decay ──
    bp.tick(half_life_rounds=20)

    # ── 2. Input ──
    try:
        user = input(f"\n[{uid}]> ")
    except (EOFError, KeyboardInterrupt):
        break
    if user.strip().lower() in ("/quit", "/exit"):
        break
    if not user.strip():
        continue

    round_count += 1
    profile.start_session() if round_count == 1 else None

    # ── 3. Evaluate ──
    is_tired = any(w in user for w in ("累", "困", "睡了", "好晚", "不说了"))
    is_happy = any(w in user for w in ("谢谢", "懂了", "好", "对", "可以"))
    is_angry = any(w in user for w in ("错", "不对", "不行", "废话"))
    hour = datetime.now().hour

    if is_tired:
        trust = max(0.0, trust - 0.02)
    elif is_happy:
        trust = min(1.0, trust + 0.03)
    elif is_angry:
        trust = max(0.0, trust - 0.04)

    # ── 4. Apply pending proposals ──
    for prop in list(pending):
        accepted, reason = engine.evaluate(prop, bp, trust)
        if accepted:
            ok, msg = bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
            if ok:
                engine.record_evolution(trust)
                profile.record_modification(prop["target_blueprint_key"], prop["new_value"])
                print(f"  [contract] {prop['target_blueprint_key']} -> {prop['new_value']}")
        pending.remove(prop)

    # ── 5. Build prompt with contract state ──
    verbose = bp.fields.get("response_verbose_level", "HIGH")
    style = bp.fields.get("explanation_style", "THEORETICAL")
    contract_hint = ""
    if "BRIEF" in verbose.upper() or verbose.upper() == "LOW":
        contract_hint = "Keep your response short. Direct answer only. No theory buildup."
    elif verbose.upper() == "HIGH":
        contract_hint = "Feel free to explain thoroughly with theory and examples."

    system = (
        f"You are a helpful AI assistant. {contract_hint}\n"
        f"Current time: {datetime.now().strftime('%H:%M')}"
    )

    try:
        prompt = f"{system}\n\nUser: {user}"
        response = llm.generate(prompt)
    except Exception as e:
        response = f"(LLM error: {e})"
        trust = max(0.0, trust - 0.01)

    print(f"\n[agent] {response}")

    # ── 6. Post-evolution check ──
    rolled, reason = engine.post_check(bp, trust)
    if rolled:
        print(f"  [rollback] {reason}")

    # ── 7. System 2 audit ──
    if auditor.should_audit(round_count):
        print(f"  [system2] auditing... (circuit {'OPEN' if auditor._circuit_open else 'closed'})")
        auditor.audit_async(
            [user], bp.snapshot, datetime.now().strftime("%H:%M"),
            callback=lambda p: pending.append(p) if p else None,
        )

    # ── 8. Profile + amendments ──
    profile.record_trust_delta(0.0)
    for key in ("response_verbose_level",):
        amendment = profile.propose_amendment(key, bp.fields.get(key, "?"))
        if amendment:
            print(f"  [amendment] {amendment['human_reason'][:100]}")

    profile.save()

    # ── Status line ──
    print(f"  [trust={trust:.2f}] [verbose={verbose}] [round={round_count}] "
          f"[evolutions={bp.applied_count}] [circuit={'OFF' if auditor._circuit_open else 'OK'}]")

print(f"\nGoodbye. {round_count} rounds. Profile saved to {profile.storage_path_obj}")
profile.save()
