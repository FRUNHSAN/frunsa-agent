"""SignalInterpreter — PLAN6.2: translate trust signals into Proposals.

This is the reflex arc. Embedding gives us "fatigue=0.84". This module
translates that into concrete Blueprint modification proposals that the
ContractEvolutionEngine can accept or reject.

Design: deterministic rules (no LLM). Fast, predictable, auditable.
Replaces the Signal→Constraint prompt hack with Signal→Proposal→Blueprint pipeline.
"""

from __future__ import annotations

from core.contracts.blueprint_schema import SIGNAL_TARGETS

# ── Complexity detection: heuristic keywords ──
COMPLEXITY_MARKERS = [
    "怎么", "如何", "为什么", "你觉得", "怎么看", "分析",
    "比较", "区别", "优缺点", "建议", "方案", "思路",
    "怎么准备", "怎么平衡", "怎么说服", "演示", "答辩",
    "展示", "面试", "转正", "怎么办", "能不能胜任",
]


def interpret(
    dim: str | None,
    score: float,
    trust: float,
    current_bp: dict[str, str],
    user_text: str = "",
    thresholds: dict[str, float] | None = None,
) -> list[dict]:
    """Translate a trust signal into 0-N contract proposals.

    Args:
        thresholds: Per-user learned thresholds. Falls back to defaults.

    Returns list of proposal dicts, each with:
      {target_blueprint_key, new_value, trigger_condition, human_reason}
    """
    proposals: list[dict] = []
    t = thresholds or {}  # Personalized thresholds

    # ── Complexity: user asks a big question → temporary verbosity lift ──
    verbose = current_bp.get("response_verbose_level", "HIGH")
    complexity_threshold = t.get("curiosity", 0.40)
    if verbose in ("LOW", "MINIMAL", "VERY_LOW"):
        if dim not in ("fatigue", "frustration") or score < t.get("fatigue", 0.55):
            if any(m in user_text for m in COMPLEXITY_MARKERS):
                proposals.append({
                    "target_blueprint_key": "response_verbose_level",
                    "new_value": "MEDIUM",
                    "trigger_condition": "complex_question",
                    "human_reason": (
                        "User asked a complex question. Lifting to MEDIUM "
                        "to give adequate help."
                    ),
                })

    if not dim or score < t.get("fatigue", 0.40) if not dim else score < complexity_threshold:
        return proposals

    # ── Fatigue: stop pushing, stop performing ──
    if dim == "fatigue" and score > t.get("fatigue", 0.55):
        if current_bp.get("conversational_initiative") != "RESPONSIVE_ONLY":
            proposals.append({
                "target_blueprint_key": "conversational_initiative",
                "new_value": "RESPONSIVE_ONLY",
                "trigger_condition": f"fatigue_{score:.2f}",
                "human_reason": f"User fatigued (score={score:.2f}). Stop asking questions.",
            })
        if current_bp.get("response_verbose_level") not in ("LOW", "MINIMAL"):
            proposals.append({
                "target_blueprint_key": "response_verbose_level",
                "new_value": "LOW",
                "trigger_condition": f"fatigue_{score:.2f}",
                "human_reason": f"User fatigued (score={score:.2f}). Reduce verbosity.",
            })
        if current_bp.get("tone_style") not in ("CALM", "PRAGMATIC"):
            proposals.append({
                "target_blueprint_key": "tone_style",
                "new_value": "CALM",
                "trigger_condition": f"fatigue_{score:.2f}",
                "human_reason": f"User fatigued (score={score:.2f}). Calm tone, no enthusiasm.",
            })

    # ── Frustration: drop the act, be direct ──
    if dim == "frustration" and score > t.get("frustration", 0.55):
        # First: reduce verbosity — the #1 frustration driver
        if current_bp.get("response_verbose_level") not in ("LOW", "MINIMAL"):
            proposals.append({
                "target_blueprint_key": "response_verbose_level",
                "new_value": "LOW",
                "trigger_condition": f"frustration_{score:.2f}",
                "human_reason": f"User frustrated. Reduce verbosity FIRST.",
            })
        if current_bp.get("tone_style") != "PRAGMATIC":
            proposals.append({
                "target_blueprint_key": "tone_style",
                "new_value": "PRAGMATIC",
                "trigger_condition": f"frustration_{score:.2f}",
                "human_reason": f"User frustrated (score={score:.2f}). Direct, no fluff.",
            })
        if current_bp.get("contextual_anchoring") != "LOW":
            proposals.append({
                "target_blueprint_key": "contextual_anchoring",
                "new_value": "LOW",
                "trigger_condition": f"frustration_{score:.2f}",
                "human_reason": f"User frustrated. Drop time/weather metaphors.",
            })
        if current_bp.get("conversational_initiative") != "RESPONSIVE_ONLY":
            proposals.append({
                "target_blueprint_key": "conversational_initiative",
                "new_value": "RESPONSIVE_ONLY",
                "trigger_condition": f"frustration_{score:.2f}",
                "human_reason": f"User frustrated. Stop asking. Just respond.",
            })

    # ── Trust crisis: emergency minimal mode ──
    if trust < 0.05:
        if current_bp.get("response_verbose_level") != "MINIMAL":
            proposals.append({
                "target_blueprint_key": "response_verbose_level",
                "new_value": "MINIMAL",
                "trigger_condition": "trust_crisis",
                "human_reason": "CRITICAL: trust < 0.05. Entering minimal safe mode.",
            })
        if current_bp.get("proactive_suggestions") != "DISABLED":
            proposals.append({
                "target_blueprint_key": "proactive_suggestions",
                "new_value": "DISABLED",
                "trigger_condition": "trust_crisis",
                "human_reason": "CRITICAL: trust < 0.05. Disabling all suggestions.",
            })

    # Filter: only proposals targeting valid fields with actual changes
    valid = []
    for p in proposals:
        key = p["target_blueprint_key"]
        if key in SIGNAL_TARGETS and current_bp.get(key) != p["new_value"]:
            valid.append(p)

    return valid
