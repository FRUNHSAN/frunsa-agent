"""ActionPipeline — PLAN8: contract-enforced tool execution gate.

Before ANY tool executes, this pipeline checks:
  1. Constitution: is this tool category permanently banned?
  2. Tool contract: does current trust meet the tool's min_trust?
  3. Blueprint autonomy: does the contract allow autonomous action?

Returns (allowed: bool, reason: str, requires_hitl: bool).
The Agent MUST respect the verdict — no bypass possible.
"""

from __future__ import annotations

from core.contracts.tool_contract import (
    RiskLevel, ToolContract, TOOLS, CONSTITUTIONAL_BAN,
)


class ActionPipeline:
    """Gatekeeper for tool execution. Contract-driven, code-enforced."""

    def __init__(self, bp: object, trust: float = 0.0) -> None:
        self._bp = bp
        self._trust = trust
        self._failure_counts: dict[str, int] = {}  # Backlash tracking

    def check(self, tool_name: str) -> dict:
        """Check if a tool can execute.

        Returns:
          {"allowed": bool, "reason": str, "requires_hitl": bool}
        """
        tc = self._get_contract(tool_name)
        if tc is None:
            return {"allowed": False, "reason": f"Unknown tool: '{tool_name}'", "requires_hitl": False}

        # ── 1. Constitution check ──
        ok, reason = tc.check_constitution(CONSTITUTIONAL_BAN)
        if not ok:
            return {"allowed": False, "reason": reason, "requires_hitl": False}

        # ── 2. Tool contract trust check ──
        ok, reason = tc.check_trust(self._trust)
        if not ok:
            # requires_hitl = the tool has require_hitl=True
            return {"allowed": False, "reason": reason, "requires_hitl": tc.require_hitl}

        # ── 3. Blueprint autonomy check ──
        autonomy = self._bp.enforce("execution_autonomy") or "ASK_FIRST"
        if autonomy == "DISABLED":
            return {"allowed": False, "reason": "Blueprint: autonomy DISABLED.", "requires_hitl": True}
        if autonomy == "ASK_FIRST" and tc.risk_level in (RiskLevel.WRITE, RiskLevel.DESTRUCTIVE):
            return {"allowed": False, "reason": "Blueprint: ASK_FIRST for write/destructive.", "requires_hitl": True}

        # ── 4. Backlash: recent failures reduce confidence ──
        recent_failures = self._failure_counts.get(tool_name, 0)
        if recent_failures >= 3:
            return {"allowed": False, "reason": f"Backlash: '{tool_name}' failed {recent_failures}x recently.", "requires_hitl": False}

        return {"allowed": True, "reason": "OK", "requires_hitl": tc.require_hitl}

    def guard_post_retrieval(self, tool_name: str, results: list[dict]) -> list[dict]:
        """Post-retrieval guardrail: filter/replace results that violate contract.

        For knowledge_search: checks whitelist paths and blocked keywords.
        Replaces violating content with '<SYSTEM>不可访问</SYSTEM>' — the LLM
        never sees the original data.
        """
        if tool_name != "knowledge_search":
            return results

        tc = self._get_contract(tool_name)
        if tc is None:
            return []

        # Read guard metadata from TOOLS dict (not ToolContract dataclass)
        raw = TOOLS.get(tool_name, {})
        whitelist: list[str] = raw.get("whitelist", [])
        blocked: list[str] = raw.get("blocked_keywords", [])
        max_results: int = raw.get("max_results", 3)
        filtered: list[dict] = []
        blocked_count = 0

        for r in results[:max_results]:
            path = r.get("file", "") or r.get("source", "")
            content = r.get("content", "") or r.get("snippet", "")

            # Check whitelist
            if whitelist and not any(path.startswith(w) for w in whitelist):
                r["content"] = "<SYSTEM>此知识源在当前契约下不可访问。</SYSTEM>"
                blocked_count += 1

            # Check blocked keywords in content
            elif any(kw in content for kw in blocked):
                r["content"] = "<SYSTEM>此内容包含受限信息，已被拦截。</SYSTEM>"
                blocked_count += 1

            # Check blocked keywords in query/request
            elif any(kw in r.get("query", "") for kw in blocked):
                r["content"] = "<SYSTEM>查询包含受限关键词，已被拦截。</SYSTEM>"
                blocked_count += 1

            filtered.append(r)

        if blocked_count > 0:
            self.record_result(tool_name, success=False)
        return filtered

    def record_result(self, tool_name: str, success: bool) -> None:
        """Record tool execution result for Backlash loop."""
        if success:
            self._failure_counts.pop(tool_name, None)
        else:
            self._failure_counts[tool_name] = self._failure_counts.get(tool_name, 0) + 1

    @property
    def trust(self) -> float:
        return self._trust

    @trust.setter
    def trust(self, value: float) -> None:
        self._trust = max(0.0, min(1.0, value))

    @staticmethod
    def _get_contract(tool_name: str) -> ToolContract | None:
        data = TOOLS.get(tool_name)
        if data is None:
            return None
        return ToolContract(**{k: v for k, v in data.items() if k in ToolContract.__dataclass_fields__})
