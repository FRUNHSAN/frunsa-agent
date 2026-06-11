"""V8.4: Real PowerShell tool — first non-simulated tool for closed-loop testing.

Implements ToolProtocol. Registered as 'run_powershell' via USB model.
Executes a PowerShell command via subprocess and returns stdout/stderr.
"""

from __future__ import annotations

import subprocess
import time
from typing import ClassVar

from core.contracts import COMPONENT_REGISTRY, SemVer, register_component
from core.contracts.tool import ToolResult


@register_component("tool", "run_powershell")
class RunPowershell:
    """Execute a PowerShell command on the local machine.

    Usage:
        tool = RunPowershell()
        result = tool.execute(command="ls", timeout=15)
    """

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)

    def execute(self, command: str, timeout: int = 15) -> ToolResult:
        """Run a PowerShell command. Returns ToolResult with stdout/stderr."""
        t0 = time.perf_counter()
        call_id = f"ps_{int(t0 * 1000)}"

        try:
            proc = subprocess.run(
                ["powershell", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            success = proc.returncode == 0

            if success:
                output = stdout[:2000] if stdout else "(no output)"
            else:
                output = f"exit={proc.returncode}\n{stderr[:500]}" if stderr else f"exit={proc.returncode}"

            return ToolResult(
                call_id=call_id,
                tool_name="run_powershell",
                success=success,
                data=output,
                error=stderr if not success else None,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                call_id=call_id,
                tool_name="run_powershell",
                success=False,
                data="",
                error=f"Command timed out after {timeout}s",
            )
        except FileNotFoundError:
            return ToolResult(
                call_id=call_id,
                tool_name="run_powershell",
                success=False,
                data="",
                error="PowerShell not found on this system",
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                tool_name="run_powershell",
                success=False,
                data="",
                error=f"Unexpected error: {exc}",
            )
