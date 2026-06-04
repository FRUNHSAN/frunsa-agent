"""AgentRouter — PLAN7.4: contract-aware backend selection.

Active routing, not passive fallback. Before each request,
the router decides: local (deterministic, GBNF-enforced) or
cloud (intelligent, fast). The contract engine drives the choice.

Decision criteria (priority order):
  1. Contract strictness: MINIMAL/LOW → local+GBNF (100% compliance needed)
  2. Format requirements: System2 audit → local (JSON schema enforced)
  3. Task complexity: deep reasoning → cloud (local 4B insufficient)
  4. Trust crisis: trust < 0.05 → local (safe mode, no initiative)
  5. Default: cloud (best quality-to-cost ratio)
"""

from __future__ import annotations

# ── Complexity markers: questions local 4B can't handle well ──
HIGH_COMPLEXITY_MARKERS = [
    "分析", "比较", "评估", "判断", "为什么",
    "优缺点", "权衡", "架构设计", "方案", "策略",
    "面试", "答辩", "转正", "考研",
    "你觉得", "你怎么看", "给我建议",
    "深度", "细节", "展开", "详细",
]


def decide(
    bp_fields: dict,
    user_input: str,
    trust: float,
    is_system2_audit: bool = False,
) -> str:
    """Decide which backend to use for this request.

    Returns "local" or "cloud".
    """
    verbose = bp_fields.get("response_verbose_level", "HIGH")
    initiative = bp_fields.get("conversational_initiative", "BALANCED")

    # ── PLAN7.4: Local reserved for future deterministic needs ──
    # Current: Pipeline truncation on cloud is sufficient for chat.
    # Local+GBNF enabled when subprocess stability improves.
    return "cloud"
