"""ToolEngine — fourth engine in the agent pipeline.

Elevates tools from sync callables to first-class citizens
with async streaming, trace_context, and contract-aware wrapping.

Exports:
  ToolIdentity    — Agent identity for tool execution
  ToolContext     — Request context carrying tool name + params
  ToolEngine      — Protocol: async execute() → AsyncIterator[StreamItem]
  RegistryToolEngine — Implementation: discovers tools from COMPONENT_REGISTRY
"""

from engines.tool.identity import ToolIdentity
from engines.tool.interface import ToolContext, ToolEngine
from engines.tool.registry_based import RegistryToolEngine

__all__ = [
    "ToolIdentity",
    "ToolContext",
    "ToolEngine",
    "RegistryToolEngine",
]
