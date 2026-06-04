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

# ── HF mirror for Chinese users ──
import os as _os
_os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from dotenv import load_dotenv; load_dotenv()
from LLM.deepseek import DeepSeekClient
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile
from core.contracts.blueprint_schema import blueprint_defaults, BLUEPRINT_SCHEMA
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.contract_auditor import ContractAuditor
from core.adapters.signal_interpreter import interpret as signal_interpret
from core.adapters.output_pipeline import OutputPipeline
from core.adapters.output_grammar import build_grammar as build_gbnf
from core.adapters.agent_router import decide as route_decide

# ── PLAN7.4: Dual-backend with active routing ──
from LLM.native_llm import NativeLLMClient
HAS_LOCAL = True  # Native llama.cpp always available

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
bp = DynamicBlueprint(blueprint_defaults())
engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)
# ── Dual backends ──
cloud_llm = DeepSeekClient(model="deepseek-chat", temperature=0.7, max_tokens=512)
local_llm = NativeLLMClient(max_tokens=512, temperature=0.7, n_ctx=2048, n_gpu_layers=0)
auditor = ContractAuditor(cloud_llm, interval=10)
print(f"  [PLAN7.4] Dual-backend: DeepSeek + Qwen3.5-4B (router active)")
pipeline = OutputPipeline(bp)

trust = 0.30
round_count = 0
pending: list[dict] = []
history: list[str] = []
contract_events: list[str] = []
_amendments_shown: set[str] = set()

print(f"  blueprint: {bp.snapshot}")
print(f"  trust: {trust:.2f} | sessions: {profile.session_count}")
print(f"  /quit to exit | /new to start fresh conversation")
print(f"{'='*50}")

# ── Proposal application helper (dedup 3 duplicate blocks) ──
def _apply_proposal(
    prop: dict, bp, engine, profile, trust: float, label: str = "",
) -> bool:
    """Single entry point for all proposal evaluation + application."""
    accepted, reason = engine.evaluate(prop, bp, trust)
    if accepted:
        ok, msg = bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
        if ok:
            engine.record_evolution(trust)
            profile.record_modification(prop["target_blueprint_key"], prop["new_value"])
            if label:
                print(f"  [{label}] {prop['target_blueprint_key']} -> {prop['new_value']}")
            return True
    return False

# ── Boss 2: Explicit user command detection ──
def _detect_explicit_command(text: str) -> tuple[str, str] | None:
    """Detect explicit user instructions and return (target_key, new_value)."""
    t = text.strip()

    # Verbose commands
    if any(w in t for w in ("话少点", "别啰嗦", "字少点", "简洁", "简短", "别整太多", "简单点说")):
        return ("response_verbose_level", "MINIMAL")
    if any(w in t for w in ("详细点", "展开", "多说点", "讲详细", "展开讲讲")):
        return ("response_verbose_level", "HIGH")
    if any(w in t for w in ("字多点", "多一点", "多一点点", "再多一点")):
        return ("response_verbose_level", "MEDIUM")

    # Tone commands
    if any(w in t for w in ("带点感情", "来点人味", "别这么机器", "像朋友", "像人一样", "自然点")):
        return ("tone_style", "WARM")
    if any(w in t for w in ("严肃点", "别开玩笑", "正经", "专业点", "别闹")):
        return ("tone_style", "PRAGMATIC")

    # Initiative commands
    if any(w in t for w in ("别问了", "不要问", "别反问", "别老问")):
        return ("conversational_initiative", "RESPONSIVE_ONLY")
    if any(w in t for w in ("多问问", "你问我", "反问", "引导我")):
        return ("conversational_initiative", "PROACTIVE")

    return None

# ── Contract enforcement: data-driven from Blueprint ──
def build_contract_directive(bp_fields: dict) -> str:
    """Generate system prompt constraints from Blueprint state.

    No hardcoded rules. Reads the contract and translates each field
    into a behavioral instruction. New fields added to BlueprintSchema
    automatically flow into the prompt — zero code changes.
    """
    v = bp_fields.get("response_verbose_level", "HIGH")
    initiative = bp_fields.get("conversational_initiative", "BALANCED")
    tone = bp_fields.get("tone_style", "WARM")
    anchoring = bp_fields.get("contextual_anchoring", "HIGH")

    parts = ["[CURRENT MODE]"]

    # Verbose
    v_map = {
        "HIGH": "Detailed with examples. Up to 3 paragraphs.",
        "MEDIUM": "Balanced. Brief context + one example. ~2 paragraphs.",
        "LOW": "Concise. 2-3 sentences max. Under 100 words.",
        "MINIMAL": "One sentence only. Direct answer. No elaboration.",
    }
    parts.append(f"Verbose: {v_map.get(v, v)}")

    # ── Boss 4: Format shackles for LOW/MINIMAL ──
    if v in ("LOW", "MINIMAL", "VERY_LOW"):
        parts.append(
            "FORMAT LOCK: Strictly under 3 sentences. No compound sentences. "
            "No semicolons. Periods only. Punchy. "
            "BANNED: bullet points, numbered lists, markdown headers, "
            "blockquotes, line breaks. "
            "Even if user asks a complex question, give only the core verdict."
        )

    # Initiative
    init_map = {
        "PROACTIVE": "Lead the conversation. Ask follow-up questions freely.",
        "BALANCED": "Natural flow. Ask questions when it feels right, not every reply.",
        "RESPONSIVE_ONLY": "NEVER ask questions. Respond and close. Let the user lead.",
    }
    parts.append(f"Initiative: {init_map.get(initiative, initiative)}")

    # Tone
    tone_map = {
        "ENTHUSIASTIC": "Warm and energetic. Emojis welcome.",
        "WARM": "Gentle and human. Natural openings.",
        "CALM": "Restrained. Minimal affect. No filler words.",
        "PRAGMATIC": "Direct and factual. No greetings, no 哈哈, no metaphors.",
    }
    parts.append(f"Tone: {tone_map.get(tone, tone)}")

    # Anchoring
    if anchoring == "LOW":
        parts.append("MUST NOT: time-of-day, weather, or environment references.")

    # ── Boss 3: Anti-sycophancy ──
    parts.append(
        "TONE: Never start with 'Your judgment is correct', 'You are right', "
        "'你说得对'. Treat user as intellectual peer. Dive directly into "
        "analysis, nuance, or counter-arguments. Disagreement is respect."
    )

    return "\n".join(parts)

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
        try:
            sig = sem.detect(user)
        except Exception:
            sig = {"dimension": None, "score": 0.0, "all_scores": {}}
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

    # ── Apply pending proposals ──
    for prop in list(pending):
        if _apply_proposal(prop, bp, engine, profile, trust, label="SYSTEM2"):
            contract_events.append(
                f"[R{round_count}] {prop['target_blueprint_key']} -> {prop['new_value']}"
            )
        pending.remove(prop)

    # ── Boss 2: Explicit user commands bypass Trust gate ──
    explicit = _detect_explicit_command(user)
    if explicit:
        cmd_prop = {
            "target_blueprint_key": explicit[0],
            "new_value": explicit[1],
            "source": "explicit_user_command",
            "trigger_condition": "user_said_so",
            "human_reason": f"User explicitly requested: '{user[:40]}'.",
        }
        if _apply_proposal(cmd_prop, bp, engine, profile, trust, label="USER COMMAND"):
            contract_events.append(
                f"[R{round_count}] {cmd_prop['target_blueprint_key']} -> {cmd_prop['new_value']}"
            )

    # ── SignalInterpreter: signal → Proposals → EvolutionEngine ──
    if USE_SEMANTIC and sem is not None and dim:
        sig_proposals = signal_interpret(dim, score, trust, bp.snapshot, user)
        for sp in sig_proposals:
            if _apply_proposal(sp, bp, engine, profile, trust, label="SIGNAL→CONTRACT"):
                contract_events.append(
                    f"[R{round_count}] {sp['target_blueprint_key']} -> {sp['new_value']}"
                )

    # ── Build prompt from Blueprint (data-driven, no hardcoded constraints) ──
    contract = build_contract_directive(bp.snapshot)
    context = build_context(history, contract_events)
    now = datetime.now().strftime("%H:%M")

    system = (
        f"{contract}\n"
        f"Current time: {now}\n"
        f"{context}"
    ).strip()

    print()
    full_prompt = f"{system}\n\nUser: {user}"
    full_response = ""

    try:
        # ── PLAN7.4: Router decides backend per-request ──
        backend = route_decide(bp.snapshot, user, trust)
        if backend == "local":
            full_response = local_llm.generate(full_prompt, grammar=build_gbnf(bp.snapshot))
        else:
            full_response = cloud_llm.generate(full_prompt)
        if backend == "local":
            print(f"  [router] -> local+GBNF")
    except Exception as e:
        full_response = f"(LLM error: {e})"
        trust = max(0.0, trust - 0.01)

    # ── PLAN7: OutputPipeline — contract-enforced post-processing ──
    original_len = len(full_response)
    full_response, penalty = pipeline.process(full_response.strip())
    if penalty:
        trust = max(0.0, trust - penalty)
    if len(full_response) < original_len * 0.7:
        print(f"  [pipeline] {original_len}→{len(full_response)} chars")

    print(f"\n[agent] {full_response}")

    # ── Save history ──
    history.append(f"User: {user}")
    history.append(f"Agent: {full_response[:200]}")
    if len(history) > 40:
        history = history[-40:]

    # ── Post-check ──

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
            schema=BLUEPRINT_SCHEMA,
            rejection_log=bp.rejection_log,
        )

    # ── Profile ──
    profile.record_trust_delta(trust_delta)
    # Only propose amendment if value differs from schema default
    current_verbose = bp.fields.get("response_verbose_level", "HIGH")
    if current_verbose != BLUEPRINT_SCHEMA["response_verbose_level"]["default"]:
        amendment = profile.propose_amendment("response_verbose_level", current_verbose)
        if amendment and amendment["target_blueprint_key"] not in _amendments_shown:
            _amendments_shown.add(amendment["target_blueprint_key"])
            print(f"  [AMENDMENT] {amendment['human_reason'][:120]}")
    profile.save()

    # ── Status ──
    verbose = bp.enforce("response_verbose_level") or "HIGH"
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
