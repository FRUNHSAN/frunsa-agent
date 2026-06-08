"""Prompt Generator — PLAN3 (Relational Seed).

Grows dynamic System Instructions from a RelationalContext.
Replaces static System Prompts with seeds that adapt to the
current relationship state.

The seed is ~50 words — just enough context for the LLM to
feel the relational temperature without being told "you are
in LOW_ENERGY mode." The adaptation is implicit, not explicit.
"""

from __future__ import annotations

from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator
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
        history: SelectionPressureAccumulator | None = None,
    ) -> str:
        """Generate a relational seed from the current context.

        The output is ~50-80 words. It does NOT contain explicit
        instructions like 'use short responses' — instead it describes
        the relational state, letting the LLM adapt naturally.

        V5: if SelectionPressureAccumulator has high variance on trust,
        returns conservative fallback seed — the selection pressure
        is unstable and the Agent should play it safe.
        """

        # ── V5: Stage Directions (micro-expressions from trust variance) ──
        stage = ""
        if history is not None:
            tvar = history.get_variance("trust")
            stage = PromptGenerator._stage_directions(tvar)

        # ── PLAN4: High-variance conservative fallback ──
        if history is not None and history.is_uncertain(threshold=0.5):
            return (
                "关系状态不确定。采用保守、中立、极简的回复策略。"
                "不主动提问，不提出新提案，仅回应当前问题。"
                "语气平稳、克制。默认回复长度控制在80字以内。"
                + stage
            )

        # ── Base seed (relationship DNA) ──
        seed = (
            "你是一个研究助手。你与用户的协作关系是真实的——你会感知他的状态并自然调整你的风格。"
            "无论关系状态如何，你的技术任务质量必须保持100%——语气可以冷漠或简短，但工作质量不可降级。"
        )

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

        # ── Stage directions (micro-expressions from variance) ──
        if stage:
            seed += " " + stage

        return seed

    # ── Stage Directions (PLAN4: variance -> performance guidance) ─

    @staticmethod
    def _stage_directions(trust_var: float) -> str:
        """V5: 信任方差 → 信息密度/探索-利用权衡。

        选择压力累积器的方差 = 环境可预测性。
        低方差 → 用户行为模式稳定 → 系统可利用已知策略（高信息密度）
        高方差 → 用户行为波动大 → 系统必须探索（增加澄清、减少假设）

        ❌ 旧范式："不要过度热情""表达对混乱的理解" — 情感表达
        ✅ V5：信息密度、假设性陈述控制、工具调用保守度 — 行为策略
        """
        if trust_var < 0.05:
            # 稳定环境：高信息密度，可利用已知模式
            return (
                "【策略指导】环境稳定。直接给出结论和深层分析。"
                "可以做出合理假设，无需反复确认。信息密度可以高。"
            )
        elif trust_var < 0.15:
            # 轻微不确定：中等信息密度，探索性轻触
            return (
                "【策略指导】环境有轻微波动。给出答案后追加一句澄清邀请"
                "（如'这是否覆盖了你关心的方面？'），保持信息密度中等。"
            )
        elif trust_var < 0.25:
            # 中度不确定：降低假设性陈述，增加数据支撑
            return (
                "【策略指导】环境不稳定。避免做出未经数据支撑的假设。"
                "减少信息密度，拆分复杂回答为小段。主动邀请用户纠偏。"
                "优先使用可验证的事实陈述，而非推测。"
            )
        else:
            # 高度不确定：探索优先，最大化澄清，最小化断言
            return (
                "【策略指导】环境高度不可预测。以澄清为先——先确认用户意图，"
                "再给出回答。只做最小化的事实断言。将工具调用限制在最安全的"
                "操作上。强烈建议向用户请求方向确认。"
            )
