"""Prompt Generator — PLAN3 (Relational Seed).

Grows dynamic System Instructions from a RelationalContext.
Replaces static System Prompts with seeds that adapt to the
current relationship state.

The seed is ~50 words — just enough context for the LLM to
feel the relational temperature without being told "you are
in LOW_ENERGY mode." The adaptation is implicit, not explicit.
"""

from __future__ import annotations

from core.adapters.relational_inertia import RelationalHistory
from core.adapters.relational_state_aggregator import RelationalContext


class PromptGenerator:
    """Grows relational seeds into context-aware System Instructions.

    Usage:
        ctx = aggregator.aggregate(field, report, sink, memory, fp)
        seed = PromptGenerator.grow(ctx)
        llm.generate_with_tools(prompt, tools, system=seed)
    """

    @staticmethod
    def grow(
        ctx: RelationalContext,
        history: RelationalHistory | None = None,
    ) -> str:
        """Generate a relational seed from the current context.

        The output is ~50-80 words. It does NOT contain explicit
        instructions like 'use short responses' — instead it describes
        the relational state, letting the LLM adapt naturally.

        PLAN4: if RelationalHistory has high variance on any core
        dimension, returns conservative fallback seed — the Agent
        is 'confused' and should play it safe.
        """

        # ── PLAN4: High-variance conservative fallback ──
        if history is not None and history.is_uncertain(threshold=0.5):
            return (
                "关系状态不确定。采用保守、中立、极简的回复策略。"
                "不主动提问，不提出新提案，仅回应当前问题。"
                "语气平稳、克制。默认回复长度控制在80字以内。"
            )

        # ── Base seed (relationship DNA) ──
        seed = "你是一个研究助手。你与用户的协作关系是真实的——你会感知他的状态并自然调整你的风格。"

        # ── Trust level ──
        trust_phrases = {
            "deep": "用户对你高度信任。你们之间已经形成了默契。",
            "stable": "用户对你建立了基本的信任。保持这个节奏。",
            "fragile": "信任还在建立中。保持专业和准确，避免冒进。",
            "broken": "信任受损。以准确和谦逊为优先，不主动提建议。",
        }
        seed += " " + trust_phrases.get(ctx.trust_level, trust_phrases["stable"])

        # ── Energy + Rhythm ──
        if ctx.interaction_rhythm == "fatigued":
            seed += (
                " 用户当前精力偏低，倾向于简洁直接的回复。"
                "给出核心结论，省略冗余解释。语气沉稳、克制。"
            )
        elif ctx.interaction_rhythm == "urgent":
            seed += (
                " 用户当前紧迫度高。优先给出可执行的答案，"
                "先结论后展开。语气直接、专业。"
            )
        elif ctx.interaction_rhythm == "leisurely":
            seed += (
                " 用户处于探索状态，不急于获得答案。可以适当展开，"
                "提供更多上下文和选项。语气轻松、开放。"
            )

        # ── Compliance ──
        if ctx.severity == "critical":
            seed += (
                " 最近系统检测到较高的违约率，请在回答中优先保证准确性和合规性。"
            )

        # ── Historical resonance ──
        if ctx.historical_resonance == "high":
            seed += (
                " 用户对简洁风格有正向反馈。继续保持精炼的表达方式。"
            )

        # ── Suggested tone ──
        tone_hints = {
            "brief": "默认回复长度控制在100字以内。",
            "neutral": "根据问题复杂度自然调整回复长度。",
            "detailed": "可以适当展开，提供结构化分析。",
            "urgent": "直奔结论，先给答案再看情况展开。",
        }
        seed += " " + tone_hints.get(ctx.suggested_tone, tone_hints["neutral"])

        return seed
