#!/usr/bin/env python3
"""PLAN5 Live — production interactive loop.

Run: python run_live.py [user_id]

Every round:
  bp.tick() -> evaluate -> proposals -> LLM (with history + contract) -> System2 -> persist
"""

from __future__ import annotations
import sys, json, threading, io
from datetime import datetime
from pathlib import Path

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

# ── PLAN6: Semantic Trust Engine (with keyword fallback) ──
try:
    from core.adapters.semantic_trust import SemanticTrustEngine
    sem = SemanticTrustEngine()
    print(f"  [PLAN6] Semantic trust loaded. dims={sem.dimensions}")
    USE_SEMANTIC = True
except (ImportError, OSError) as e:
    print(f"  [PLAN6] Semantic engine unavailable ({e}). Falling back to keywords.")
    USE_SEMANTIC = False
    sem = None

uid = sys.argv[1] if len(sys.argv) > 1 else "default"
base = str(Path(__file__).resolve().parent / "user_profiles")
print(f"\n{'='*50}")
print(f"PLAN5 Live — {uid}")
print(f"{'='*50}")

profile = UserProfile.load(uid, storage_path=base)
bp = DynamicBlueprint({
    "response_verbose_level": "HIGH",
    "execution_autonomy": "ASK_FIRST",
    "proactive_suggestions": "ENABLED",
    "explanation_style": "THEORETICAL",
})
engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
llm = DeepSeekClient(model="deepseek-chat", temperature=0.7, max_tokens=512)
auditor = ContractAuditor(llm, interval=10)

trust = 0.30
round_count = 0
pending: list[dict] = []
history: list[str] = []
contract_events: list[str] = []
_amendments_shown: set[str] = set()
_verbose_locked: bool = False        # Bug 2: once LOW, stay LOW
_trust_crisis_rounds: int = 0        # Bug 3: consecutive crisis counter

print(f"  blueprint: {bp.snapshot}")
print(f"  trust: {trust:.2f} | sessions: {profile.session_count}")
print(f"  /quit to exit | /new to start fresh conversation")
print(f"{'='*50}")

# ── Contract enforcement: hard constraint template ──
def build_contract_directive(verbose: str) -> str:
    """Hard constraint block. LLMs obey structured directives better than hints."""
    if "EXTREME" in verbose.upper() or "BRIEF" in verbose.upper():
        return (
            "[CONTRACT: EXTREME_BRIEF]\n"
            "MUST: One sentence. Under 50 words. Direct answer.\n"
            "MUST NOT: Greetings. Explanations. Questions. Lists. Emojis. Code.\n"
            "PENALTY: If you write more than 2 sentences, the user leaves."
        )
    if verbose.upper() == "LOW":
        return (
            "[CONTRACT: CONCISE]\n"
            "MUST: 2-3 sentences max. Under 100 words.\n"
            "MUST NOT: Questions unless user clearly invites discussion.\n"
            "MUST NOT: '哈哈' openings. '听起来像是' metaphors. AI-style framing.\n"
            "MUST NOT: Time-of-day references. Weather metaphors. Emoji overuse."
        )
    if verbose.upper() == "HIGH":
        return (
            "[CONTRACT: THOROUGH]\n"
            "MUST: Warm, brief, human. Like texting a friend.\n"
            "MUST NOT: Lectures. Bullet-points. More than 2 short paragraphs.\n"
            "MUST NOT: Questions unless genuinely curious. NEVER force a question.\n"
            "MUST NOT: '哈哈' openings. '听起来像是' '像是从X变成了Y' AI formulas.\n"
            "CRITICAL: If user says bye/拜拜/累了/先这样 — just say goodbye. No questions."
        )
    return ""

def build_context(history: list[str], events: list[str]) -> str:
    """Build context block: contract events + last few turns."""
    parts = []
    if events:
        parts.append("[CONTRACT HISTORY: " + " -> ".join(events[-3:]) + "]")
    if history:
        recent = history[-6:]  # last 3 exchanges
        parts.append("[RECENT CONTEXT]\n" + "\n".join(recent[-6:]))
    return "\n".join(parts) if parts else ""

# ── Main Loop ──

while True:
    bp.tick(half_life_rounds=20)

    try:
        user = input(f"\n[{uid}]> ")
    except (EOFError, KeyboardInterrupt):
        break
    cmd = user.strip().lower()

    if cmd in ("/quit", "/exit"):
        break
    if cmd == "/new":
        round_count = 0
        history.clear()
        contract_events.clear()
        _verbose_locked = False
        _trust_crisis_rounds = 0
        profile.start_session()
        print(f"  [new conversation] Session {profile.session_count} started. Fresh context.")
        continue
    if not user.strip():
        continue

    round_count += 1
    if round_count == 1:
        profile.start_session()
        print(f"  [new conversation] Session {profile.session_count}.")

    # ── PLAN6 Evaluate: semantic trust or keyword fallback ──
    trust_before = trust
    if USE_SEMANTIC and sem is not None:
        sig = sem.detect(user)
        dim, score = sig["dimension"], sig["score"]
        if dim == "fatigue":
            trust = max(0.0, trust - 0.01 * (1 + score))
        elif dim == "gratitude":
            trust = min(0.85, trust + 0.02 * (1 + score))
        elif dim == "frustration":
            trust = max(0.0, trust - 0.03 * (1 + score))
        # curiosity: neutral on trust, but logs engagement
        if dim:
            print(f"  [sense] {dim}={score:.3f}")
    else:
        # Keyword fallback
        is_tired = any(w in user for w in ("累", "困", "睡了", "好晚", "不说了"))
        is_happy = any(w in user for w in ("谢谢", "懂了", "好多了", "不错", "对的", "是的", "哈哈"))
        is_angry = any(w in user for w in ("错了", "不对", "不行", "废话", "别说了", "别问了"))
        if is_tired:
            trust = max(0.0, trust - 0.01)
        if is_happy:
            trust = min(0.85, trust + 0.02)
        if is_angry:
            trust = max(0.0, trust - 0.03)
    trust_delta = trust - trust_before

    # ── Apply proposals ──
    for prop in list(pending):
        accepted, reason = engine.evaluate(prop, bp, trust)
        if accepted:
            ok, msg = bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
            if ok:
                engine.record_evolution(trust)
                profile.record_modification(prop["target_blueprint_key"], prop["new_value"])
                event = f"[R{round_count}] {prop['target_blueprint_key']}: {prop.get('old_value','?')} -> {prop['new_value']}"
                contract_events.append(event)
                print(f"  [CONTRACT EVOLVED] {event}")
        pending.remove(prop)

    # ── Build prompt ──
    verbose = bp.fields.get("response_verbose_level", "HIGH")
    contract = build_contract_directive(verbose)
    context = build_context(history, contract_events)
    now = datetime.now().strftime("%H:%M")

    # ── Bug 1 fix: Signal → Constraint bridge ──
    signal_constraint = ""
    if USE_SEMANTIC and sem is not None and dim:
        if dim == "fatigue" and score > 0.6:
            signal_constraint = (
                f"\n[CRITICAL CONSTRAINT] User fatigue={score:.2f}. "
                "MUST: Very short. MUST NOT: ANY questions. End warmly, no follow-up."
            )
        elif dim == "frustration" and score > 0.6:
            signal_constraint = (
                f"\n[CRITICAL CONSTRAINT] User frustration={score:.2f}. "
                "MUST: Acknowledge briefly. MUST NOT: Questions. Defensiveness. Explanations."
            )

    system = (
        f"{contract}\n"
        f"Current time: {now}\n"
        f"{signal_constraint}\n"
        f"{context}"
    ).strip()

    print()
    full_prompt = f"{system}\n\nUser: {user}"
    full_response = ""
    try:
        for chunk in llm.generate_stream(full_prompt):
            # Strip markdown noise for terminal
            clean = chunk.replace("**", "").replace("__", "").replace("###", "").replace("---", "")
            print(clean, end="", flush=True)
            full_response += chunk
    except Exception as e:
        print(f"(LLM error: {e})")
        full_response = f"(LLM error: {e})"
        trust = max(0.0, trust - 0.01)
    print()

    # ── Save history ──
    history.append(f"User: {user}")
    history.append(f"Agent: {full_response[:200]}")
    if len(history) > 40:
        history = history[-40:]

    # ── Bug 2: Verbose lock — LOW is sticky ──
    current_verbose = bp.fields.get("response_verbose_level", "HIGH")
    if "LOW" in str(current_verbose).upper() or "BRIEF" in str(current_verbose).upper():
        _verbose_locked = True
    if _verbose_locked and current_verbose == "HIGH":
        # System tried to bounce back — override
        bp.fields["response_verbose_level"] = "LOW"
        print(f"  [LOCK] Verbose locked at LOW. Use /new to reset.")

    # ── Bug 3: Trust crisis recovery ──
    if trust < 0.05:
        _trust_crisis_rounds += 1
    else:
        _trust_crisis_rounds = 0
    if _trust_crisis_rounds >= 3:
        trust = max(trust, 0.08)  # Small repair — break the freeze
        _trust_crisis_rounds = 0
        print(f"  [RECOVERY] Trust crisis detected. Small repair applied. trust={trust:.2f}")

    # ── Emergency downgrade: trust critically low ──
    if trust < 0.05 and bp.fields.get("response_verbose_level") != "LOW":
        ok, _ = bp.apply_proposal("response_verbose_level", "LOW", ignore_cooldown=True)
        if ok:
            _verbose_locked = True
            print(f"  [EMERGENCY] Trust {trust:.2f} — forcing verbose: HIGH -> LOW")
    if trust < 0.03 and bp.fields.get("proactive_suggestions") != "DISABLED":
        ok, _ = bp.apply_proposal("proactive_suggestions", "DISABLED", ignore_cooldown=True)
        if ok:
            print(f"  [EMERGENCY] Trust {trust:.2f} — forcing suggestions: DISABLED")

    # ── Post-check ──
    rolled, reason = engine.post_check(bp, trust)
    if rolled:
        contract_events.append(f"[R{round_count}] ROLLBACK: {reason[:60]}")
        print(f"  [ROLLBACK] {reason}")

    # ── System 2 ──
    if auditor.should_audit(round_count):
        auditor.audit_async(
            history[-20:], bp.snapshot, datetime.now().strftime("%H:%M"),
            callback=lambda p: pending.append(p) if p else None,
        )

    # ── Profile ──
    profile.record_trust_delta(trust_delta)
    amendment = profile.propose_amendment("response_verbose_level", verbose)
    if amendment and amendment["target_blueprint_key"] not in _amendments_shown:
        _amendments_shown.add(amendment["target_blueprint_key"])
        print(f"  [AMENDMENT] {amendment['human_reason'][:120]}")
    profile.save()

    # ── Status ──
    status_parts = [f"trust={trust:.2f}", f"verbose={verbose}", f"round={round_count}"]
    if bp.applied_count > 0:
        status_parts.append(f"evolutions={bp.applied_count}")
    print(f"  [{' | '.join(status_parts)}]")

print(f"\n{'='*50}")
print(f"Done. {round_count} rounds. Profile: {profile.storage_path_obj}")
print(f"  Contract events: {len(contract_events)}")
print(f"  Evolutions applied: {bp.applied_count}")
print(f"{'='*50}")
profile.save()
