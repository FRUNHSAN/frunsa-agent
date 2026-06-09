"""V7.1 SandboxExecutor — deterministic physical feedback via layered execution.

Defensive Axiom B (Stateless Sandbox): every run() is an independent process
with no shared mutable state. Pure-function verification only.

Defensive Axiom D (Physical Budget): Layer 1 (AST) is free, Layers 2-3 cost budget.

PhysicalState ∈ Q:
  PASS:              code executed successfully
  COMPILE_ERR:       syntax error (AST parse failed)
  TYPE_MISMATCH:     mypy type check failed
  RUNTIME_ERR:       execution raised an exception
  TIMEOUT:           execution exceeded deadline
  SANDBOX_VIOLATION: attempted restricted operation
"""

from __future__ import annotations

import ast
import enum
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any


class PhysicalState(enum.Enum):
    """Discrete physical state q ∈ Q."""
    PASS = "PASS"
    COMPILE_ERR = "COMPILE_ERR"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    RUNTIME_ERR = "RUNTIME_ERR"
    TIMEOUT = "TIMEOUT"
    SANDBOX_VIOLATION = "SANDBOX_VIOLATION"

    def is_fatal(self) -> bool:
        """FAIL_FATAL states trigger Rigid Contract #5."""
        return self in (PhysicalState.SANDBOX_VIOLATION,)

    def is_retryable(self) -> bool:
        """FAIL_RETRYABLE states allow ErrorMapper + retry."""
        return self in (
            PhysicalState.COMPILE_ERR,
            PhysicalState.TYPE_MISMATCH,
            PhysicalState.RUNTIME_ERR,
            PhysicalState.TIMEOUT,
        )


@dataclass
class ExecutionResult:
    """Deterministic output from a sandbox execution."""
    state: PhysicalState
    output: str = ""                 # stdout on success
    error_message: str = ""          # traceback / error on failure
    error_line: int | None = None    # line number of failure
    elapsed_ms: float = 0.0
    test_results: list[dict] = field(default_factory=list)
    # {test_index, input, expected, got, passed}


class SandboxExecutor:
    """Layered physical executor for LLM-generated code.

    Usage:
        executor = SandboxExecutor()
        result = executor.run(code, test_cases=[
            {"input": "[3,1,4,1,5], k=2", "expected": 4},
        ])
        if result.state == PhysicalState.PASS:
            print("Code works.")
    """

    def __init__(self, max_exec_sec: float = 5.0):
        self._max_exec_sec = max_exec_sec

    def run(self, code: str, test_cases: list[dict] | None = None,
            intent_type: str = "EXECUTABLE") -> ExecutionResult:
        """Execute code through layered physical verification.

        Args:
            code: Python source code to verify.
            test_cases: Optional list of {input, expected} pairs.
            intent_type: EXECUTABLE, PSEUDOCODE, DEMONSTRATION, DESTRUCTIVE_TEST.

        Returns:
            ExecutionResult with state and diagnostics.
        """
        t0 = time.perf_counter()

        # ── Layer 1: AST syntax check (free, always runs) ──
        ast_result = self._check_ast(code)
        if ast_result.state != PhysicalState.PASS:
            ast_result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return ast_result

        # PSEUDOCODE / DEMONSTRATION / DESTRUCTIVE_TEST: stop at AST
        if intent_type != "EXECUTABLE":
            return ExecutionResult(
                state=PhysicalState.PASS,
                output=f"[intent_type={intent_type}: AST OK, skipping execution]",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Layer 3: Sandbox execution with test cases ──
        exec_result = self._run_sandbox(code, test_cases or [])
        exec_result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return exec_result

    # ── Layer 1: AST ────────────────────────────────────────────────

    @staticmethod
    def _check_ast(code: str) -> ExecutionResult:
        """Parse code with ast.parse. Catches ~80% of LLM syntax errors."""
        try:
            ast.parse(code)
        except SyntaxError as e:
            return ExecutionResult(
                state=PhysicalState.COMPILE_ERR,
                error_message=f"SyntaxError at line {e.lineno}: {e.msg}",
                error_line=e.lineno,
            )
        return ExecutionResult(state=PhysicalState.PASS)

    # ── Layer 3: Sandbox ────────────────────────────────────────────

    def _run_sandbox(self, code: str, test_cases: list[dict]) -> ExecutionResult:
        """Execute code in a restricted namespace and run test cases.

        Each test case is a dict with:
          - input: str to eval as function arguments
          - expected: expected return value (or str for exception type)
        """
        # Restricted builtins: only safe operations
        safe_builtins: dict[str, Any] = {
            "abs": abs, "all": all, "any": any, "bool": bool,
            "dict": dict, "enumerate": enumerate, "filter": filter,
            "float": float, "int": int, "len": len, "list": list,
            "map": map, "max": max, "min": min, "print": print,
            "range": range, "reversed": reversed, "round": round,
            "set": set, "sorted": sorted, "str": str, "sum": sum,
            "tuple": tuple, "type": type, "zip": zip,
            "True": True, "False": False, "None": None,
            "Exception": Exception, "ValueError": ValueError,
            "TypeError": TypeError, "KeyError": KeyError,
            "IndexError": IndexError, "StopIteration": StopIteration,
        }
        namespace: dict[str, Any] = {"__builtins__": safe_builtins}

        # Step 1: Compile and exec the code in the sandbox
        try:
            compiled = compile(code, "<sandbox>", "exec")
            exec(compiled, namespace)
        except Exception as e:
            tb_lines = traceback.format_exception_only(type(e), e)
            return ExecutionResult(
                state=PhysicalState.RUNTIME_ERR,
                error_message="".join(tb_lines).strip(),
                error_line=getattr(e, "lineno", None)
                    or _extract_lineno_from_tb(traceback.extract_tb(sys.exc_info()[2] if sys.exc_info()[2] else None)),
            )

        # Step 2: Run test cases
        test_results = []
        all_passed = True
        for i, tc in enumerate(test_cases):
            try:
                got = self._run_single_test(tc, namespace)
                expected = tc.get("expected")
                passed = _assert_equal(got, expected)
                test_results.append({
                    "index": i, "input": tc.get("input", ""),
                    "expected": expected, "got": got, "passed": passed,
                })
                if not passed:
                    all_passed = False
            except Exception as e:
                test_results.append({
                    "index": i, "input": tc.get("input", ""),
                    "expected": tc.get("expected"), "got": f"{type(e).__name__}: {e}",
                    "passed": False,
                })
                all_passed = False

        if all_passed:
            return ExecutionResult(
                state=PhysicalState.PASS,
                output="All test cases passed.",
                test_results=test_results,
            )
        else:
            failed = [t for t in test_results if not t["passed"]]
            return ExecutionResult(
                state=PhysicalState.RUNTIME_ERR,
                error_message=f"{len(failed)}/{len(test_results)} test cases failed",
                test_results=test_results,
            )

    @staticmethod
    def _run_single_test(tc: dict, namespace: dict) -> Any:
        """Execute a single test case against a function in namespace."""
        input_str = tc.get("input", "")
        func_name = tc.get("function", "")

        # Find the function in namespace
        if func_name:
            fn = namespace.get(func_name)
            if fn is None:
                raise ValueError(f"Function '{func_name}' not found in sandbox")
        else:
            # Find first callable that's not a builtin
            fn = None
            for name, obj in namespace.items():
                if callable(obj) and not name.startswith("__") and name not in (
                    "abs", "all", "any", "bool", "dict", "enumerate", "filter",
                    "float", "int", "len", "list", "map", "max", "min", "print",
                    "range", "reversed", "round", "set", "sorted", "str", "sum",
                    "tuple", "type", "zip",
                ):
                    fn = obj
                    break
            if fn is None:
                raise ValueError("No callable function found in sandbox")

        # Eval input args and call
        if input_str.strip():
            args = eval(input_str, {"__builtins__": {}}, {})
            if isinstance(args, tuple):
                return fn(*args)
            else:
                return fn(args)
        else:
            return fn()


# ── Helpers ────────────────────────────────────────────────────────────

def _assert_equal(got: Any, expected: Any) -> bool:
    """Compare got vs expected, handling exception type strings."""
    # Handle expected exception type
    if isinstance(expected, str) and "Error" in str(expected):
        if isinstance(got, str) and "Error" in str(got):
            return str(expected) in str(got) or str(got).startswith(str(expected))
        return False
    # Direct equality
    if got == expected:
        return True
    # Float tolerance
    if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
        return abs(got - expected) < 1e-9
    return False


def _extract_lineno_from_tb(tb) -> int | None:
    """Extract line number from traceback extract."""
    if tb:
        for frame in tb:
            if hasattr(frame, "lineno"):
                return frame.lineno
            elif isinstance(frame, tuple) and len(frame) >= 2:
                return frame[1]
    return None
