"""RegistryToolEngine — discovers tools from COMPONENT_REGISTRY, dispatches async.

- Sync ToolProtocol.execute() wrapped via asyncio.to_thread() (Tech Lead: async adapt)
- ToolResult → StreamItem converter with tool.* trace_context keys
- Error handling: exceptions → error StreamItem, never crash the pipeline
- Deadline enforcement before dispatch
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

from core.contracts import StreamItem
from core.contracts.registry import COMPONENT_REGISTRY
from core.contracts.streaming_protocol import PaceConfig
from core.contracts.tool import ToolResult, ToolCall
from engines.tool.identity import ToolIdentity
from engines.tool.interface import ToolContext


class RegistryToolEngine:
    """Implementation: discovers + dispatches tools from COMPONENT_REGISTRY.

    Sync tools are wrapped in asyncio.to_thread() to prevent event loop blocking.
    Results are converted to StreamItems with full trace_context for X-Ray/Critic.
    """

    identity = ToolIdentity(
        id="tool-executor-v1", role="tool_executor", version="1.0.0",
        capabilities=("registry_discovery", "sync_to_async_bridge"),
    )

    async def execute(
        self,
        context: ToolContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        start = time.perf_counter()
        tool_name = context.tool_name
        identity_value = context.agent_identity.to_trace_value()

        # ── Deadline check ──
        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(f"Tool {tool_name}: deadline exceeded before dispatch")

        try:
            # ── Discover tool from USB registry ──
            try:
                tool_cls = COMPONENT_REGISTRY.get("tool", tool_name)
            except (KeyError, Exception):
                yield StreamItem(
                    delta="",
                    index=0,
                    model="tool/registry",
                    finish_reason="error",
                    is_terminal=True,
                    error=f"Tool not found: {tool_name}",
                    trace_context={
                        "tool.name": tool_name,
                        "tool.success": False,
                        "tool.error": f"Tool not found: {tool_name}",
                        "agent.identity": identity_value,
                    },
                )
                return

            # ── Instantiate + execute (sync→async bridge) ──
            def _sync_execute() -> ToolResult:
                tool = tool_cls()
                params = dict(context.parameters)
                return tool.execute(**params)

            try:
                result = await asyncio.to_thread(_sync_execute)
            except asyncio.TimeoutError:
                raise
            except Exception as exc:
                result = ToolResult(
                    call_id="",
                    tool_name=tool_name,
                    success=False,
                    error=str(exc),
                )

            # ── ToolResult → StreamItem ──
            elapsed = time.perf_counter() - start
            delta = _result_to_text(result)
            yield StreamItem(
                delta=delta,
                index=0,
                model=f"tool/{tool_name}",
                finish_reason="stop" if result.success else "error",
                is_terminal=True,
                error=result.error if not result.success else None,
                trace_context={
                    "tool.name": tool_name,
                    "tool.call_id": result.call_id,
                    "tool.success": result.success,
                    "tool.error": result.error,
                    "tool.data_preview": delta[:200],
                    "tool.elapsed_ms": elapsed * 1000,
                    "agent.identity": identity_value,
                },
            )

        except asyncio.TimeoutError:
            yield StreamItem(
                delta="",
                index=0,
                model="tool/registry",
                finish_reason="error",
                is_terminal=True,
                error=f"Tool {tool_name}: deadline exceeded",
                trace_context={
                    "tool.name": tool_name,
                    "tool.success": False,
                    "tool.error": "deadline_exceeded",
                    "agent.identity": identity_value,
                },
            )


def _result_to_text(result: ToolResult) -> str:
    """Convert ToolResult data to a text delta for StreamItem."""
    data = result.data
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # MCP tools return {'content': [...]}
        if "content" in data:
            content = data["content"]
            if isinstance(content, list):
                return "\n".join(str(c) for c in content)
            return str(content)
        if "text" in data:
            return str(data["text"])
        return str(data)
    if hasattr(data, "text"):
        return str(data.text)
    return str(data)[:2000]
