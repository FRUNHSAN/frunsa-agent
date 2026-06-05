"""BlueprintSchema — PLAN6.2: data-driven contract field definitions.

Every tunable contract field is defined here with type, allowed values,
and a human-readable description. This schema is consumed by:
  - DynamicBlueprint (init defaults)
  - ContractAuditor (System 2 knows what it can change)
  - SignalInterpreter (maps signals to valid targets)
  - build_contract_directive() (generates prompt from blueprint)
"""

from __future__ import annotations

BLUEPRINT_SCHEMA: dict[str, dict] = {
    # ── Core behavior ──
    "response_verbose_level": {
        "type": "enum",
        "values": ["HIGH", "MEDIUM", "LOW", "MINIMAL"],
        "default": "MEDIUM",
        "description": (
            "Response length. HIGH: detailed with examples. "
            "MEDIUM: balanced. LOW: concise 2-3 sentences. "
            "MINIMAL: one sentence, no elaboration."
        ),
    },
    # ── Conversation control (fixes "every reply has a question") ──
    "conversational_initiative": {
        "type": "enum",
        "values": ["PROACTIVE", "BALANCED", "RESPONSIVE_ONLY"],
        "default": "BALANCED",
        "description": (
            "Who drives the conversation. PROACTIVE: leads and asks questions. "
            "BALANCED: natural back-and-forth. "
            "RESPONSIVE_ONLY: never asks questions, only responds."
        ),
    },
    # ── Tone (fixes "哈哈" AI-formula openings) ──
    "tone_style": {
        "type": "enum",
        "values": ["ENTHUSIASTIC", "WARM", "CALM", "PRAGMATIC"],
        "default": "WARM",
        "description": (
            "Emotional register. ENTHUSIASTIC: excited, emoji-heavy. "
            "WARM: gentle empathy. CALM: restrained, minimal affect. "
            "PRAGMATIC: direct, factual, no filler words."
        ),
    },
    # ── Context anchoring (fixes time/weather metaphors) ──
    "contextual_anchoring": {
        "type": "enum",
        "values": ["HIGH", "LOW"],
        "default": "LOW",
        "description": (
            "Whether to reference time, weather, or environment in responses. "
            "HIGH: '凌晨三点的城市...' LOW: pure content, no external anchors."
        ),
    },
    # ── Autonomy ──
    "execution_autonomy": {
        "type": "enum",
        "values": ["FULL", "HIGH", "ASK_FIRST", "DISABLED"],
        "default": "ASK_FIRST",
        "description": (
            "How freely the Agent can act without asking. "
            "FULL: act independently. ASK_FIRST: confirm before actions. "
            "DISABLED: no autonomous actions."
        ),
    },
    # ── Suggestions ──
    "proactive_suggestions": {
        "type": "enum",
        "values": ["ENABLED", "DISABLED"],
        "default": "ENABLED",
        "description": "Whether to offer unsolicited suggestions or ideas.",
    },
    # ── Explanation style ──
    "explanation_style": {
        "type": "enum",
        "values": ["THEORETICAL", "EXAMPLE_FIRST", "CODE_FIRST", "BRIEF"],
        "default": "THEORETICAL",
        "description": "How to structure explanations.",
    },
}

# ── Fields that SignalInterpreter can auto-modify ──
SIGNAL_TARGETS = frozenset({
    "response_verbose_level",
    "conversational_initiative",
    "tone_style",
    "contextual_anchoring",
    "proactive_suggestions",
})


def blueprint_defaults() -> dict[str, str]:
    """Return a dict of {field: default_value} from the schema."""
    return {k: v["default"] for k, v in BLUEPRINT_SCHEMA.items()}
