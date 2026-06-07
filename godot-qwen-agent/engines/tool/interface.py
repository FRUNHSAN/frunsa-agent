"""ToolEngine Protocol — fourth engine in the agent pipeline.

Symmetric with PlanningEngine / OrchestrationEngine / CriticEngine:
  - async generator: execute(context, deadline, pace_config) → AsyncIterator[StreamItem]
  - trace_context keys: tool.name, tool.call_id, tool.success, tool.error
  - deadline enforcement + PaceConfig QoS
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Protocol

from core.contracts.streaming_protocol import PaceConfig
from core.contracts.generation import StreamItem
from engines.tool.identity import ToolIdentity


@dataclass(frozen=True)
class ToolContext:
    """Request context for tool execution.

    Fields:
        tool_name: COMPONENT_REGISTRY key of the tool to execute.
        parameters: Keyword arguments forwarded to ToolProtocol.execute().
        agent_identity: Identity of the tool executor agent.
        metadata: Opaque passthrough for engine-level context.
    """

    tool_name: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    agent_identity: ToolIdentity = field(
        default_factory=lambda: ToolIdentity(
            id="tool-executor-v1", role="tool_executor", version="1.0.0",
        )
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ToolEngine(Protocol):
    """Execute tools with full engine infrastructure.

    Signature identical to PlanningEngine / OrchestrationEngine / CriticEngine:
      async def execute(context, deadline, pace_config) -> AsyncIterator[StreamItem]

    Each yielded StreamItem carries tool.* trace_context keys:
      tool.name, tool.call_id, tool.success, tool.error, tool.data_preview
    """

    async def execute(
        self,
        context: ToolContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute a single tool. Yields one or more StreamItems.

        - Single-result tools: yield one StreamItem (is_terminal=True)
        - Streaming tools: yield multiple deltas, last one is_terminal
        - Error: yield one StreamItem with error detail
        """
        ...
        yield  # type: ignore[unreachable]
