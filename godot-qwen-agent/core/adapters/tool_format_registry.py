"""ToolFormatRegistry — USB model for LLM provider tool schemas (V4.3).

Eliminates the if/elif provider branching in tool_adapter.py (Invariant #37).
Each LLM provider registers a bidirectional adapter:
  format_tools(schemas) → provider-native tool definitions
  parse_response(response) → standardized ToolCall

Usage:
  ToolFormatRegistry.register("anthropic", AnthropicToolFormat)
  ToolFormatRegistry.register("openai", OpenAIToolFormat)

  converter = ToolFormatRegistry.get("anthropic")
  tools = converter.format_tools(registry_tool_schemas)
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol


class ToolFormatAdapter(Protocol):
    """Bidirectional: tool schema → provider format, provider response → ToolCall."""

    def format_tools(self, registry_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert registry tool schemas to provider-native tool definitions."""
        ...

    def parse_tool_call(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Parse provider-specific tool call response into standardized dict.
        Returns {'tool_name': str, 'parameters': dict, 'tool_id': str}.
        """
        ...


class ToolFormatRegistry:
    """USB registry: LLM provider → ToolFormatAdapter.

    Adding a new provider = register one adapter. Zero tool_adapter.py changes.
    """

    _adapters: Dict[str, type] = {}

    @classmethod
    def register(cls, provider: str, adapter_cls: type) -> None:
        cls._adapters[provider] = adapter_cls

    @classmethod
    def get(cls, provider: str) -> type:
        if provider not in cls._adapters:
            from core.adapters.tool_format_defaults import OpenAIToolFormat
            cls._adapters[provider] = OpenAIToolFormat
        return cls._adapters[provider]

    @classmethod
    def format(cls, provider: str, registry_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        adapter = cls.get(provider)()
        return adapter.format_tools(registry_tools)
