"""V8.4: Real filesystem tools — write_file, read_file.

Implements ToolProtocol. Registered via USB model.
Uses actual filesystem operations via Python builtins.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import ClassVar

from core.contracts import COMPONENT_REGISTRY, SemVer, register_component
from core.contracts.tool import ToolResult

# ═══════════════════════════════════════════════════════════════
# V9.2c: 沙盒防御 — 防目录穿越攻击
# ═══════════════════════════════════════════════════════════════

SAFE_SANDBOX = Path(os.getenv("AGENT_SANDBOX", "./workspace")).resolve()


def _validate_sandbox_path(requested_path: str) -> Path:
    """防弹级路径校验 — 免疫前缀欺骗与符号链接穿越。

    使用 Path.relative_to 替代 str.startswith，
    彻底杜绝 /workspace_evil 绕过 /workspace 的经典攻击。
    """
    SAFE_SANDBOX.mkdir(parents=True, exist_ok=True)

    target = Path(requested_path).resolve()

    try:
        target.relative_to(SAFE_SANDBOX)
        is_safe = True
    except ValueError:
        is_safe = False

    if not is_safe:
        # 越权路径 → 剥夺目录结构，强制收拢到沙盒根
        safe_name = target.name if target.name else "unnamed_file"
        target = SAFE_SANDBOX / safe_name

    return target


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
            safe_path = _validate_sandbox_path(path)
            safe_path.write_text(content, encoding="utf-8")
            size = safe_path.stat().st_size
            return ToolResult(
                call_id=call_id,
                tool_name="write_file",
                success=True,
                data=f"写入成功: {safe_path} ({size} bytes)",
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
            safe_path = _validate_sandbox_path(path)
            if not safe_path.exists():
                return ToolResult(
                    call_id=call_id, tool_name="read_file",
                    success=False, data="", error=f"文件不存在: {safe_path}",
                )
            content = safe_path.read_text(encoding="utf-8")[:max_chars]
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
