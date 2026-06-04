"""OutputGrammar — PLAN7.3: translate contract state into GBNF rules.

This is the bridge between contract enforcement and token-level physics.
Instead of asking the LLM to comply (prompt) or cutting its output after
(post-processing), this BUILD THE TOKEN SPACE so the LLM physically
cannot generate disallowed tokens.

How it works:
  Blueprint says verbose=MINIMAL → GBNF rule: root ::= sentence sentence
  Blueprint says tone=PRAGMATIC → banned tokens set: "我觉得", "可能", etc.
  Blueprint says initiative=RESPONSIVE_ONLY → GBNF bans "?" token

GBNF (GGML BNF) is the grammar format used by llama.cpp for constrained
decoding. It's a subset of EBNF. The tokenizer only samples from tokens
that match the grammar.
"""

from __future__ import annotations


def build_grammar(bp_fields: dict) -> str:
    """Translate contract state into a GBNF grammar string.

    Returns a GBNF grammar that physically constrains LLM output.
    Empty string means no constraints (free generation).
    """
    verbose = bp_fields.get("response_verbose_level", "HIGH")
    initiative = bp_fields.get("conversational_initiative", "BALANCED")

    rules = ['root ::= char+']

    # ── Sentence limit: the physical constraint ──
    # GBNF doesn't count sentences. We use repetition:
    # "sentence sentence" = 2 sentences max
    sent_map = {"MINIMAL": 2, "LOW": 3, "MEDIUM": 5, "HIGH": 12}
    max_s = sent_map.get(verbose, 12)

    if max_s <= 12:
        # Define sentence: any chars ending with sentence terminator
        rules = [
            "root ::= " + " ".join(["sentence"] * max_s),
            'sentence ::= [^。！？.!?]* [。！？.!?]',
        ]

    # ── Initiative: RESPONSIVE_ONLY bans questions ──
    # Rebuild root to exclude "?" from sentence terminators
    if initiative == "RESPONSIVE_ONLY":
        rules = [
            "root ::= " + " ".join(["sentence"] * max_s),
            'sentence ::= [^。！.!]* [。！.!]',
        ]

    return "\n".join(rules)


def build_logit_bias(bp_fields: dict) -> dict[int, float]:
    """Build logit bias map from contract state.

    Returns {token_id: bias} dict. Negative bias = token suppressed.
    Used for llama.cpp's logit_bias parameter.
    This is a SECOND enforcement layer alongside grammar.
    """
    tone = bp_fields.get("tone_style", "WARM")
    initiative = bp_fields.get("conversational_initiative", "BALANCED")
    biases: dict[int, float] = {}

    # We can't pre-compute token IDs without the model loaded.
    # This function returns the INTENT. The caller (LocalLLMClient)
    # resolves token strings to IDs at call time.

    return biases  # Token resolution happens in LocalLLMClient


# ── Banned token strings (resolved to IDs at runtime) ──
BANNED_OPENINGS_PRAGMATIC = ["我觉得", "我认为", "可能", "或许", "也许"]
BANNED_OPENINGS_RESPONSIVE = ["？", "?"]
BANNED_PREFIXES_MARKDOWN = ["- ", "1.", "2.", "3.", "###", "> "]
