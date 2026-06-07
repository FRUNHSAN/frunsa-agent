"""Default ToolFormatAdapter implementations for Anthropic and OpenAI.

Registered into ToolFormatRegistry at import time.
Adding a new provider (Gemini, Cohere, etc.) = create a new
ToolFormatAdapter class + register it. Zero tool_adapter.py changes.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Auto-register at import time
from core.adapters.tool_format_registry import ToolFormatRegistry


class AnthropicToolFormat:
    """Anthropic tool use format: {name, description, input_schema}."""

    def format_tools(self, registry_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("parameters_schema", {}),
            }
            for tool in registry_tools
        ]

    def parse_tool_call(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tool_name": raw.get("name", ""),
            "parameters": raw.get("input", {}),
            "tool_id": raw.get("id", ""),
        }


class OpenAIToolFormat:
    """OpenAI function calling format: {type: function, function: {name, description, parameters}}."""

    def format_tools(self, registry_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters_schema", {}),
                },
            }
            for tool in registry_tools
        ]

    def parse_tool_call(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        func = raw.get("function", {})
        return {
            "tool_name": func.get("name", ""),
            "parameters": func.get("arguments", {}),
            "tool_id": raw.get("id", ""),
        }

# Register defaults at import time
ToolFormatRegistry.register("anthropic", AnthropicToolFormat)
ToolFormatRegistry.register("openai", OpenAIToolFormat)
