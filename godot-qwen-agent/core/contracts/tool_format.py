"""Tool Format Adapter — Phase 25 anti-corruption layer.

Bidirectional converter between internal ToolProtocol definitions
and LLM-specific tool call formats. Eliminates the if/elif switch
on provider name in tool_adapter.py.

New LLM providers register their format adapter here.
Zero changes to ToolAdapter or its consumers.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolFormatAdapter(Protocol):
    """Bidirectional converter for a specific LLM provider's tool format.

    Implementations: AnthropicToolFormat, OpenAIToolFormat, QwenToolFormat.
    """

    def format_tools(self, tools: list[dict]) -> list[dict]:
        """Outbound: internal tool definitions -> LLM-specific JSON.

        Args:
            tools: List of {"name": str, "description": str,
                   "parameters_schema": dict}

        Returns:
            LLM-native tool format list (Anthropic input_schema,
            OpenAI function.parameters, etc.)
        """
        ...

    def parse_response(self, llm_response: Any) -> list[dict]:
        """Inbound: LLM raw response -> internal tool call dicts.

        Args:
            llm_response: Provider-specific response object
                         (Anthropic Message, OpenAI ChatCompletion, etc.)

        Returns:
            List of {"name": str, "arguments": dict} — compatible
            with ToolAdapter.parse_function_call()
        """
        ...


class ToolFormatRegistry:
    """Registry of ToolFormatAdapters by provider name.

    Usage:
        registry = ToolFormatRegistry()
        registry.register("anthropic", AnthropicToolFormat())
        registry.register("openai", OpenAIToolFormat())
        adapter = registry.get("openai")
        tools = adapter.format_tools(internal_tools)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ToolFormatAdapter] = {}

    def register(self, provider: str, adapter: ToolFormatAdapter) -> None:
        """Register a format adapter for a provider."""
        self._adapters[provider] = adapter

    def get(self, provider: str) -> ToolFormatAdapter:
        """Get the format adapter for a provider."""
        if provider not in self._adapters:
            raise KeyError(
                f"No ToolFormatAdapter registered for provider '{provider}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        return self._adapters[provider]

    def list_providers(self) -> list[str]:
        """List registered providers."""
        return list(self._adapters.keys())
