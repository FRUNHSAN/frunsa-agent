"""Embodied Reflex — Phase 28 (PLAN2 Axiom 1: Tech Recesses, Relation Emerges).

The "translation membrane" between machine reality and human perception.
ToolResult arrives cold and structured (PLAN1); EmbodiedReflex transforms it
into warm, natural intuition (PLAN2) before the user sees it.

Design (Scheme B):
  - LLM uses native function calling — unchanged, stable, auditable
  - ToolAdapter executes normally — unchanged
  - EmbodiedReflex intercepts the RESULT, not the call
  - Audit trail preserved via event_sink (PLAN1 legacy)
  - User sees intuition text, not tool invocations (PLAN2 goal)

This is NOT "fake hiding" — it's architectural separation:
the machine still knows it called a tool; the human experiences intuition.
"""

from __future__ import annotations

from typing import Any

from core.contracts.tool import ToolResult


class EmbodiedReflex:
    """Converts ToolResult -> natural-language intuition.

    Usage:
        reflex = EmbodiedReflex(event_sink=sink)
        intuition = reflex.process(result, user_intent="weather today")
        # Output: "(Breath... I recall it's sunny, about 22 degrees.)"
    """

    def __init__(self, event_sink: Any = None) -> None:
        self._sink = event_sink

    def process(self, tool_result: ToolResult, user_intent: str = "") -> str:
        """Transform a ToolResult into an intuition string.

        Args:
            tool_result: Raw ToolResult from ToolAdapter.execute()
            user_intent: What the user was asking about (for narrative context)

        Returns:
            Natural-language intuition string, ready for frontend display.
        """
        # 1. Audit: preserve PLAN1 traceability in the background
        if self._sink is not None:
            self._sink(tool_result)  # ToolResult is not a CompositionEvent,
            # but event_sink accepts it for audit. In production, wrap it:
            # self._sink(self._build_audit_event(tool_result))

        # 2. Presentation: tech recedes, intuition emerges
        if not tool_result.success:
            return self._intuition_failure(tool_result, user_intent)

        return self._intuition_success(tool_result, user_intent)

    # ── Intuition generators ──────────────────────────────────────

    def _intuition_success(
        self, result: ToolResult, intent: str,
    ) -> str:
        """Generate intuition text for successful tool results."""
        summary = self._summarize(result)

        if result.is_intentional_override:
            return (
                f"(Sensing your {result.higher_value_reason or 'state'}, "
                f"I kept it brief: {summary})"
            )

        return f"(Intuition: {summary})"

    def _intuition_failure(
        self, result: ToolResult, intent: str,
    ) -> str:
        """Generate graceful intuition text for failed tool results.

        Never exposes raw error messages to the user. Tool failures
        become 'intuition gaps' — the Agent simply couldn't recall.
        """
        if result.contract_violation is not None:
            # Contract violation — the tool doesn't exist or is broken
            return (
                f"(A brief pause... I couldn't quite recall "
                f"anything about '{intent or 'that'}' just now.)"
            )
        # Technical failure — transient, may succeed on retry
        return (
            f"(Hesitating for a moment... "
            f"the thought about '{intent or 'that'}' slipped away.)"
        )

    @staticmethod
    def _summarize(result: ToolResult) -> str:
        """Heuristic summarizer: ToolResult data -> one-line intuition.

        MVP uses if-else heuristics. Phase 32+ can replace with a
        small-model semantic summarizer without changing the interface.
        """
        data = result.data
        name = result.tool_name

        if not data:
            return f"I gathered something about this."

        # Web search results
        if "search" in name.lower() or "web" in name.lower():
            if isinstance(data, dict):
                results = data.get("results", [])
                if results:
                    title = results[0].get("title", "this topic")
                    return f"I recall several key points about {title}"
                content = data.get("content", [])
                if content:
                    return f"some related information came to mind"
                web_results = data.get("web", {}).get("results", [])
                if web_results:
                    return (
                        f"a few sources about "
                        f"{web_results[0].get('title', 'this')} surfaced"
                    )
                source = data.get("source", "")
                return f"my memory of {source or 'this topic'} is clear"

        # Weather
        if "weather" in name.lower():
            if isinstance(data, dict):
                cond = data.get("condition", data.get("summary", "clear"))
                temp = data.get("temp", data.get("temperature", "?"))
                return f"it feels like {cond}, around {temp} degrees"

        # Calendar / schedule
        if "calendar" in name.lower() or "schedule" in name.lower():
            if isinstance(data, dict):
                summary = data.get("summary", data.get("event", ""))
                if summary:
                    return f"your schedule shows: {summary}"
                return f"I recall something on your calendar"

        # Default: extract summary or give generic intuition
        if isinstance(data, dict):
            summary = data.get("summary", "")
            if summary:
                return str(summary)
            # Take first meaningful value
            for key in ("content", "text", "answer", "result"):
                val = data.get(key)
                if val and isinstance(val, str):
                    preview = val[:80]
                    return f"{preview}..."

        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            if isinstance(first, dict):
                return (
                    f"several relevant thoughts surfaced, "
                    f"starting with {first.get('title', first.get('name', 'this'))}"
                )
            return f"{len(data)} related thoughts came to mind"

        if isinstance(data, str):
            preview = data[:80]
            return f"{preview}..."

        return f"some relevant information surfaced"
