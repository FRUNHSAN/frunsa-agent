"""V8.4: Real filesystem tools — write_file, read_file.

Implements ToolProtocol. Registered via USB model.
Uses actual filesystem operations via Python builtins.
"""

from __future__ import annotations

import os
import time
from typing import ClassVar

from core.contracts import COMPONENT_REGISTRY, SemVer, register_component
from core.contracts.tool import ToolResult


@register_component("tool", "write_file")
class WriteFile:
    """Write content to a file on disk.

    Usage:
        tool = WriteFile()
        result = tool.execute(path="output.txt", content="Hello world")
    """

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    _base_dir: str = "."

    # V9.2b: 规则引擎匹配指纹
    match_patterns: ClassVar[tuple[str, ...]] = (
        "写", "保存", "创建文件", "写入", "输出到", "write", "save",
    )

    @staticmethod
    def extract_params(user_text: str) -> dict:
        return {"path": "/tmp/output.txt", "content": user_text}

    def execute(self, path: str, content: str) -> ToolResult:
        t0 = time.perf_counter()
        call_id = f"wf_{int(t0 * 1000)}"

        try:
            full_path = os.path.join(self._base_dir, path)
            os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            size = os.path.getsize(full_path)
            return ToolResult(
                call_id=call_id,
                tool_name="write_file",
                success=True,
                data=f"写入成功: {full_path} ({size} bytes)",
            )
        except PermissionError as e:
            return ToolResult(
                call_id=call_id, tool_name="write_file",
                success=False, data="", error=f"权限不足: {e}",
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id, tool_name="write_file",
                success=False, data="", error=str(e),
            )


@register_component("tool", "read_file")
class ReadFile:
    """Read content from a file on disk.

    Usage:
        tool = ReadFile()
        result = tool.execute(path="output.txt")
    """

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    _base_dir: str = "."

    # V9.2b: 规则引擎匹配指纹
    match_patterns: ClassVar[tuple[str, ...]] = (
        "读", "查看文件", "打开文件", "读取", "read",
    )

    @staticmethod
    def extract_params(user_text: str) -> dict:
        import re
        m = re.search(r"([A-Za-z]:[\\/\w.\-]+|/[\w/.\-]+)", user_text)
        return {"path": m.group(1) if m else "unknown.txt"}

    def execute(self, path: str, max_chars: int = 3000) -> ToolResult:
        t0 = time.perf_counter()
        call_id = f"rf_{int(t0 * 1000)}"

        try:
            full_path = os.path.join(self._base_dir, path)
            if not os.path.exists(full_path):
                return ToolResult(
                    call_id=call_id, tool_name="read_file",
                    success=False, data="", error=f"文件不存在: {full_path}",
                )
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read(max_chars)
            return ToolResult(
                call_id=call_id,
                tool_name="read_file",
                success=True,
                data=content,
            )
        except PermissionError as e:
            return ToolResult(
                call_id=call_id, tool_name="read_file",
                success=False, data="", error=f"权限不足: {e}",
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id, tool_name="read_file",
                success=False, data="", error=str(e),
            )
