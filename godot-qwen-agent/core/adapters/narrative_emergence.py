"""NarrativeEmergence — V3.1: CBO patterns → living user profile.

When PatternRepository accumulates enough high-confidence patterns,
this module calls the LLM (once, offline) to generate a 100-word
"user personality narrative" from the raw SQL data.

The narrative is stored and injected as subconscious context
into the system prompt — the Agent develops a felt sense of who
the user is, not just what rules to follow.
"""

from __future__ import annotations

from core.contracts.v3_protocols import PatternRepository


NARRATIVE_PROMPT = """你是一个用户画像分析师。以下是用户在多次对话中积累的行为模式数据。

每条记录包含:
  - 上下文 (什么时间/情境)
  - 行为 (用户做了什么)
  - 动作 (系统做了什么调整)
  - 置信度 (这个模式有多可靠)

请根据这些数据, 用 80-100 字的中文, 写一段"用户性格叙事"。
不要列清单。不要提具体数字。像描述一个朋友一样, 用自然语言概括:
  - 用户在什么情况下容易疲惫
  - 用户偏好什么样的沟通节奏
  - 用户对 AI 的态度和期望
  - 有什么值得注意的互动习惯

只输出叙事段落, 不要加任何前缀或后缀。"""


class NarrativeEmergence:
    """Generate living user profiles from relational patterns.

    Usage:
        ne = NarrativeEmergence(repo, llm_client)
        narrative = ne.generate("frunhsan")
        if narrative:
            print(narrative)  # Inject into system prompt
    """

    def __init__(self, repo: PatternRepository, llm_client) -> None:
        self._repo = repo
        self._llm = llm_client
        self._cache: dict[str, str] = {}  # user_id → narrative

    def generate(self, user_id: str) -> str | None:
        """Generate or return cached narrative for this user.

        Returns None if not enough patterns to generate a meaningful narrative.
        """
        if user_id in self._cache:
            return self._cache[user_id]

        patterns = self._repo.query_active(user_id, min_occurrence=2, min_confidence=0.6)
        if len(patterns) < 2:
            return None

        # Build pattern summary for the LLM
        pattern_text = ""
        for i, p in enumerate(patterns, 1):
            pattern_text += (
                f"{i}. 情境: {p.get('context', '未知')}, "
                f"行为: {p.get('behavior', '未知')}, "
                f"调整: {p.get('action', '未知')}, "
                f"置信度: {p.get('confidence', 0):.0%}\n"
            )

        prompt = f"{NARRATIVE_PROMPT}\n\n[行为模式数据]\n{pattern_text}"

        try:
            narrative = self._llm.generate(prompt).strip()
            narrative = narrative.replace("用户性格叙事:", "").replace("叙事:", "").strip()
            if 30 < len(narrative) < 300:
                self._cache[user_id] = narrative
                return narrative
        except Exception:
            pass

        return None

    def inject(self, user_id: str) -> str:
        """Return narrative as system prompt injection, or empty string."""
        narrative = self.generate(user_id)
        if narrative:
            return f"[用户画像 — 长期观察形成的理解]\n{narrative}\n[/用户画像]"
        return ""

    @property
    def cached(self) -> dict[str, str]:
        return dict(self._cache)
