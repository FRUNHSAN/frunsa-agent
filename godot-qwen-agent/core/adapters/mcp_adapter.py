"""MCP Adapter — Phase 22d.

Bridges Model Context Protocol (MCP) servers into the USB Registry.
Tools discovered from MCP servers are automatically registered as
@register_component("tool", name), making them indistinguishable
from built-in tools to ToolAdapter and SelfRepairEngine.

Design:
  - MCPToolWrapper: ToolProtocol-compatible class using class-level
    config (matches Registry's cls() instantiation pattern)
  - MCPToolDiscovery: async discovery of tools from MCP servers
  - register_mcp_tools(): one-shot discovery + registration
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, ClassVar

from core.contracts import COMPONENT_REGISTRY, SemVer
from core.contracts.tool import ToolResult


class MCPToolWrapper:
    """ToolProtocol-compatible wrapper for MCP tools.

    Uses class-level attributes for configuration because
    COMPONENT_REGISTRY.get() returns the class and ToolAdapter
    instantiates via cls() with no constructor arguments.

    Set class attrs before registering, then cls() works.
    """

    VERSION: ClassVar[SemVer] = SemVer(0, 1, 0)

    # Class-level config — set by register_mcp_tool() before Registry.register()
    _mcp_command: ClassVar[list[str]] = []
    _mcp_env: ClassVar[dict[str, str]] = {}
    _mcp_tool_name: ClassVar[str] = ""
    _mcp_description: ClassVar[str] = ""
    _mcp_schema: ClassVar[dict] = {}

    # ToolProtocol interface — read from class vars
    @property
    def name(self) -> str:
        return self._mcp_tool_name

    @property
    def description(self) -> str:
        return self._mcp_description

    @property
    def parameters_schema(self) -> dict:
        return self._mcp_schema

    def execute(self, **params: Any) -> ToolResult:
        """Execute via MCP protocol — fresh session per call."""
        try:
            return asyncio.run(self._execute_async(params))
        except Exception as exc:
            return ToolResult(
                call_id="",
                tool_name=self._mcp_tool_name,
                success=False,
                error=f"MCP: {type(exc).__name__}: {exc}",
            )

    async def _execute_async(self, params: dict) -> ToolResult:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=self._mcp_command[0],
            args=self._mcp_command[1:] if len(self._mcp_command) > 1 else [],
            env={**os.environ, **self._mcp_env} if self._mcp_env else None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool(
                    self._mcp_tool_name, arguments=params,
                )
                content_parts = [
                    block.text for block in response.content
                    if hasattr(block, "text")
                ]
                return ToolResult(
                    call_id="",
                    tool_name=self._mcp_tool_name,
                    success=True,
                    data={
                        "content": content_parts,
                        "source": f"mcp:{self._mcp_tool_name}",
                    },
                )


class MCPToolDiscovery:
    """Discover tools from an MCP server via stdio."""

    @staticmethod
    async def list_tools(
        server_command: list[str],
        server_env: dict[str, str] | None = None,
    ) -> list[dict]:
        """Connect to an MCP server and list available tools."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:] if len(server_command) > 1 else [],
            env={**os.environ, **(server_env or {})} if server_env else None,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": getattr(t, "description", ""),
                        "inputSchema": getattr(t, "inputSchema", {}),
                    }
                    for t in response.tools
                ]


def register_mcp_tool(
    tool_def: dict,
    server_command: list[str],
    server_env: dict[str, str] | None = None,
) -> str:
    """Register a single MCP tool in the USB Registry.

    Creates a dynamic subclass of MCPToolWrapper with class-level
    config specific to this tool. This ensures multiple MCP tools
    from the same server don't overwrite each other's config.

    Returns the tool name (registry key).
    """
    tool_name = tool_def["name"]

    # Dynamic subclass — one per MCP tool, no config collision
    subcls = type(
        f"MCP_{tool_name}",
        (MCPToolWrapper,),
        {
            "_mcp_command": server_command,
            "_mcp_env": server_env or {},
            "_mcp_tool_name": tool_name,
            "_mcp_description": tool_def.get("description", ""),
            "_mcp_schema": tool_def.get("inputSchema", {}),
        },
    )

    COMPONENT_REGISTRY.register("tool", tool_name, subcls)
    return tool_name


def register_mcp_server(
    server_command: list[str],
    server_env: dict[str, str] | None = None,
) -> list[str]:
    """Discover and register all tools from an MCP server.

    One-shot: connects, lists tools, registers each one.
    Returns list of registered tool names.
    """
    tools = asyncio.run(
        MCPToolDiscovery.list_tools(server_command, server_env)
    )
    registered = []
    for tool_def in tools:
        name = register_mcp_tool(tool_def, server_command, server_env)
        registered.append(name)
    return registered
