"""V7.1 Sandbox tool — registered in COMPONENT_REGISTRY as 'sandbox_python'.

USB pattern: zero ToolEngine changes. Just register and dispatch.
"""

from __future__ import annotations

from typing import Any

from core.contracts.registry import COMPONENT_REGISTRY
from core.contracts.tool import ToolResult, ToolProtocol


@COMPONENT_REGISTRY.register("tool", "sandbox_python")
class SandboxPythonTool(ToolProtocol):
    """Tool implementation: execute Python code in sandbox and return result.

    Registered as: COMPONENT_REGISTRY.register("tool", "sandbox_python", SandboxPythonTool)
    """

    name = "sandbox_python"
    description = "Execute Python code in an isolated sandbox with AST verification and optional test cases."
    parameters_schema = {
        "code": {"type": "string", "required": True, "description": "Python source code"},
        "test_cases": {"type": "list", "required": False, "description": "List of {input, expected} test cases"},
        "intent_type": {"type": "string", "required": False, "description": "EXECUTABLE|PSEUDOCODE|DEMONSTRATION|DESTRUCTIVE_TEST"},
    }

    def execute(self, code: str = "", test_cases: list | None = None,
                intent_type: str = "EXECUTABLE", **kwargs) -> ToolResult:
        """Execute code in sandbox and return structured result."""
        from core.execution.sandbox import SandboxExecutor, PhysicalState

        executor = SandboxExecutor()
        result = executor.run(
            code=code,
            test_cases=test_cases or [],
            intent_type=intent_type,
        )

        if result.state == PhysicalState.PASS:
            return ToolResult(
                call_id="",
                tool_name="sandbox_python",
                success=True,
                data={
                    "output": result.output,
                    "test_results": result.test_results,
                    "elapsed_ms": result.elapsed_ms,
                },
            )
        else:
            return ToolResult(
                call_id="",
                tool_name="sandbox_python",
                success=False,
                error=result.error_message,
                data={
                    "physical_state": result.state.value,
                    "error_line": result.error_line,
                    "test_results": result.test_results,
                    "elapsed_ms": result.elapsed_ms,
                },
            )
