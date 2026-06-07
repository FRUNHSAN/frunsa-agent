"""Mock MCP tools — in-process tools that demonstrate the MCP execution path.

These are registered into COMPONENT_REGISTRY just like real MCP tools,
but execute locally without requiring an external MCP server process.
Used for testing the ToolAdapter → ActionPipeline → execute flow.
"""

from __future__ import annotations

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, ClassVar

from core.contracts import SemVer
from core.contracts.tool import ToolProtocol, ToolResult


def _make_call_id() -> str:
    return str(uuid.uuid4())[:8]


class MockReadFileTool:
    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path"}},
        "required": ["path"],
    }
    """Read a local file. Simulates mcp__filesystem_read."""

    name = "mcp__read_file"
    description = "Read the contents of a file on the local filesystem"
    parameters_schema: dict = {}

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path", "")
        try:
            content = Path(path).read_text(encoding="utf-8")
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=True,
                data={"text": content[:2000], "size": len(content)},
            )
        except Exception as e:
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=False,
                error=str(e),
            )


class MockListDirTool:
    """List a directory. Simulates mcp__filesystem_list_dir."""

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    name = "mcp__list_dir"
    description = "List files and directories in a given path"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path"}},
        "required": ["path"],
    }

    def execute(self, **params: Any) -> ToolResult:
        path = params.get("path", ".")
        try:
            entries = [p.name for p in Path(path).iterdir()]
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=True,
                data={"text": "\n".join(entries[:50]), "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=False,
                error=str(e),
            )


class MockSearchTool:
    """Search text in files. Simulates mcp__grep."""

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    name = "mcp__search"
    description = "Search for a pattern in project files"
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Directory to search"},
        },
        "required": ["pattern"],
    }

    def execute(self, **params: Any) -> ToolResult:
        pattern = params.get("pattern", "")
        search_path = params.get("path", ".")
        results = []
        try:
            for f in Path(search_path).rglob("*.py"):
                if f.stat().st_size > 100_000:
                    continue
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    if pattern in content:
                        results.append(str(f))
                except Exception:
                    pass
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=True,
                data={"text": f"Found in {len(results)} files:\n" + "\n".join(results[:20])},
            )
        except Exception as e:
            return ToolResult(
                call_id=_make_call_id(),
                tool_name=self.name,
                success=False,
                error=str(e),
            )


def register_mock_mcp_tools() -> list[str]:
    """Register mock MCP tools into COMPONENT_REGISTRY. Returns tool names."""
    from core.contracts.registry import COMPONENT_REGISTRY

    tools = [MockReadFileTool(), MockListDirTool(), MockSearchTool()]
    registered = []
    for tool in tools:
        cls = type(tool)
        COMPONENT_REGISTRY.register("tool", tool.name, cls)
        registered.append(tool.name)
    return registered
