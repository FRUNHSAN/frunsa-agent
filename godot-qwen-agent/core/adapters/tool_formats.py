"""Concrete ToolFormatAdapter implementations — Phase 25.

Each adapter handles ONE LLM provider's tool format.
New providers: write a new adapter, register it, done.
"""

from __future__ import annotations

import json
from typing import Any

from core.contracts.tool_format import ToolFormatAdapter


# ── Shared sanitizer ────────────────────────────────────────────────

def _sanitize_schema(schema: dict) -> dict:
    """Strip advanced JSON Schema features that LLMs don't support."""
    clean: dict = {"type": schema.get("type", "object")}
    if "description" in schema:
        clean["description"] = schema["description"]
    if "required" in schema:
        clean["required"] = schema["required"]
    if "properties" in schema:
        clean["properties"] = {}
        for prop_name, prop_schema in schema["properties"].items():
            clean_prop = {"type": prop_schema.get("type", "string")}
            if "description" in prop_schema:
                clean_prop["description"] = prop_schema["description"]
            clean["properties"][prop_name] = clean_prop
    return clean


# ── Anthropic ───────────────────────────────────────────────────────

class AnthropicToolFormat(ToolFormatAdapter):
    """Anthropic Messages API tool format.

    Outbound: {"name": ..., "description": ..., "input_schema": {...}}
    Inbound:  ToolUseBlock -> {"name": ..., "arguments": {...}}
    """

    def format_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": _sanitize_schema(
                    t.get("parameters_schema", {})
                ),
            }
            for t in tools
        ]

    def parse_response(self, llm_response: Any) -> list[dict]:
        results = []
        for block in getattr(llm_response, "content", []):
            if getattr(block, "type", "") == "tool_use":
                results.append({
                    "name": getattr(block, "name", ""),
                    "arguments": dict(getattr(block, "input", {})),
                })
        return results


# ── OpenAI / Qwen ───────────────────────────────────────────────────

class OpenAIToolFormat(ToolFormatAdapter):
    """OpenAI / Qwen (DashScope compatible) tool format.

    Outbound: {"type": "function", "function": {"name": ..., "parameters": {...}}}
    Inbound:  ChatCompletionMessage -> {"name": ..., "arguments": {...}}
    """

    def format_tools(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _sanitize_schema(
                        t.get("parameters_schema", {})
                    ),
                },
            }
            for t in tools
        ]

    def parse_response(self, llm_response: Any) -> list[dict]:
        results = []
        try:
            message = llm_response.choices[0].message
        except (AttributeError, IndexError):
            return results

        for tc in getattr(message, "tool_calls", []) or []:
            func = tc.function
            try:
                arguments = json.loads(func.arguments)
            except (json.JSONDecodeError, TypeError, AttributeError):
                arguments = {}
            results.append({
                "name": getattr(func, "name", ""),
                "arguments": arguments,
            })
        return results
