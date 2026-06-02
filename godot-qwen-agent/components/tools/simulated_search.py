"""Simulated Battle Tools — Phase 22 Pre-Battle Prep.

Two mock search tools that let us verify the full self-repair loop
WITHOUT LLM randomness. web_search can be configured to fail after N calls
(simulating rate limits, transient errors), and brave_search is the
replacement with slightly different behavior (slower, different format).

Both implement ToolProtocol and register via USB model — they are
indistinguishable from real tools as far as ToolAdapter and
SelfRepairEngine are concerned.
"""

from __future__ import annotations

from typing import ClassVar

from core.contracts import COMPONENT_REGISTRY, SemVer, register_component
from core.contracts.tool import ToolResult


@register_component("tool", "web_search")
class SimulatedWebSearch:
    """Simulated web search tool with configurable failure injection.

    Usage:
        tool = SimulatedWebSearch(fail_on_call=3)  # fails on 3rd+ call
        result = tool.execute(query="quantum computing")
    """

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    name: str = "web_search"
    description: str = "Search the web for information. Returns text results."
    parameters_schema: dict = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 5,
            },
        },
    }

    # Class-level counter — survives instance recreation by ToolAdapter
    _global_call_count: ClassVar[int] = 0
    _global_fail_on_call: ClassVar[int | None] = 3  # fails on 3rd+ call

    def __init__(self) -> None:
        pass

    def execute(self, **params) -> ToolResult:
        SimulatedWebSearch._global_call_count += 1
        call_count = SimulatedWebSearch._global_call_count
        fail_on = SimulatedWebSearch._global_fail_on_call
        query = params.get("query", "")
        call_id = f"web_search_{call_count}"

        if fail_on is not None and call_count >= fail_on:
            return ToolResult(
                call_id=call_id,
                tool_name="web_search",
                success=False,
                error="rate_limit_exceeded: too many requests",
                contract_violation=None,  # technical failure, not contractual
                data=None,
            )

        return ToolResult(
            call_id=call_id,
            tool_name="web_search",
            success=True,
            data={
                "query": query,
                "results": [
                    {"title": f"Result 1 for: {query}", "snippet": "..."},
                    {"title": f"Result 2 for: {query}", "snippet": "..."},
                ],
                "source": "web_search",
            },
        )


@register_component("tool", "brave_search")
class SimulatedBraveSearch:
    """Replacement search tool — slightly different behavior.

    This is the tool that SelfRepairEngine finds when web_search fails.
    It has a different parameters_schema (supports 'country' param) and
    returns results in a different format — proving it's a genuinely
    independent component, not a renamed clone.

    Usage:
        tool = SimulatedBraveSearch()
        result = tool.execute(query="topological qubits")
    """

    VERSION: ClassVar[SemVer] = SemVer(2, 1, 0)
    name: str = "brave_search"
    description: str = (
        "Search the web via Brave Search API. "
        "Privacy-focused, returns web results with snippets."
    )
    parameters_schema: dict = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "country": {
                "type": "string",
                "description": "Country code for regional results",
                "default": "US",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results",
                "default": 10,
            },
        },
    }

    def execute(self, **params) -> ToolResult:
        query = params.get("query", "")
        country = params.get("country", "US")
        call_id = f"brave_search_{query[:20]}"

        return ToolResult(
            call_id=call_id,
            tool_name="brave_search",
            success=True,
            data={
                "web": {
                    "results": [
                        {
                            "title": f"Brave: {query}",
                            "description": f"Detailed description for {query}",
                            "url": f"https://search.brave.com/search?q={query}",
                        },
                    ],
                },
                "source": "brave_search",
                "country": country,
            },
        )
