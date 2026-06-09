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
    """Discrete physical state q in Q.

    V7.3: Q decomposes into connected components:
      C_internal = {PASS, COMPILE_ERR, TYPE_MISMATCH, RUNTIME_ERR, TIMEOUT}
        Retry can walk within this component.
      C_external = {FATAL_EXTERNAL, SANDBOX_VIOLATION}
        No path from C_internal — retry forbidden, circuit breaker trips.
      DOCKER_UNAVAILABLE is isolated — triggers S3 fallback, not retry.
    """
    PASS = "PASS"
    COMPILE_ERR = "COMPILE_ERR"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    RUNTIME_ERR = "RUNTIME_ERR"
    TIMEOUT = "TIMEOUT"
    SANDBOX_VIOLATION = "SANDBOX_VIOLATION"
    DOCKER_UNAVAILABLE = "DOCKER_UNAVAILABLE"  # V7.3 Layer 4 fallback
    FATAL_EXTERNAL = "FATAL_EXTERNAL"          # V7.3 external circuit breaker

    def is_fatal(self) -> bool:
        """FAIL_FATAL states trigger Rigid Contract #5.
        V7.3: FATAL_EXTERNAL is also fatal — no retry across connected components."""
        return self in (PhysicalState.SANDBOX_VIOLATION, PhysicalState.FATAL_EXTERNAL)

    def is_retryable(self) -> bool:
        """FAIL_RETRYABLE states allow ErrorMapper + retry.
        V7.3: FATAL_EXTERNAL is NOT retryable — external rejection must be escalated."""
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
            intent_type: str = "EXECUTABLE",
            budget=None,
            use_docker: bool = False) -> ExecutionResult:
        """V7.3: Layered physical verification with optional OS isolation.

        Layer 1 (AST, cost=0): always runs, catches ~80% syntax errors.
        Layer 2 (Mypy, cost=0.1): static type check, skipped if budget < 0.1.
        Layer 3 (Sandbox, cost=1.0): restricted execution with timeout.
        Layer 4 (Docker, cost=2.0, optional): OS-level container isolation.
            Red-Team #1: stdin pipe — cross-platform compatible.
            Graceful fallback to Layer 3 if Docker unavailable.
        Fail-Safe: budget < 1.0 -> REJECT.

        Args:
            code: Python source code to verify.
            test_cases: Optional list of {input, expected} pairs.
            intent_type: EXECUTABLE, PSEUDOCODE, DEMONSTRATION, DESTRUCTIVE_TEST.
            budget: Optional PhysicalBudget for layered accounting.
            use_docker: If True, attempt Layer 4 Docker isolation after Layer 3.
        """
        t0 = time.perf_counter()
        tc = test_cases or []

        # ── Layer 1: AST syntax check (free, always runs) ──
        ast_result = self._check_ast(code)
        if ast_result.state != PhysicalState.PASS:
            ast_result.elapsed_ms = (time.perf_counter() - t0) * 1000
            return ast_result

        # ── Double-filter test_cases through AST (Patch B) ──
        for tc_item in tc:
            tc_code = tc_item.get("input", "")
            if tc_code and isinstance(tc_code, str) and len(tc_code) > 3:
                tc_ast = self._check_ast(f"assert {tc_code}")
                if tc_ast.state != PhysicalState.PASS:
                    return ExecutionResult(
                        state=PhysicalState.COMPILE_ERR,
                        error_message=f"test_case AST failed: {tc_ast.error_message}",
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                    )

        # PSEUDOCODE / DEMONSTRATION / DESTRUCTIVE_TEST: stop at AST
        if intent_type != "EXECUTABLE":
            return ExecutionResult(
                state=PhysicalState.PASS,
                output=f"[intent_type={intent_type}: AST OK, skipping execution]",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Layer 2: Mypy type check (cost=0.1) ──
        if budget is None or budget.spend(0.1):
            mypy_result = self._check_mypy(code)
            if mypy_result.state != PhysicalState.PASS:
                mypy_result.elapsed_ms = (time.perf_counter() - t0) * 1000
                return mypy_result

        # ── Fail-Safe: ensure budget for at least one sandbox execution (Patch C) ──
        if budget is not None and budget.remaining < 1.0:
            return ExecutionResult(
                state=PhysicalState.TIMEOUT,
                error_message="PhysicalBudget exhausted before sandbox execution. Safety first — REJECT.",
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        # ── Layer 3: Sandbox execution (cost=1.0) ──
        if budget is None or budget.spend(1.0):
            exec_result = self._run_restricted(code, tc)
            exec_result.elapsed_ms = (time.perf_counter() - t0) * 1000

            # If Layer 3 failed or Docker not requested, return immediately
            if exec_result.state != PhysicalState.PASS or not use_docker:
                return exec_result

            # ── Layer 4: Docker OS isolation (V7.3, cost=2.0, optional) ──
            # S4 filter — catches kernel escapes, filesystem violations.
            # Only attempted when Layer 3 passes AND budget allows.
            if budget is not None and budget.remaining < 2.0:
                # Budget can't afford Docker — return Layer 3 result as-is
                exec_result.output += " [Docker skipped: insufficient budget]"
                return exec_result

            if budget is None or budget.spend(2.0):
                docker_result = self._run_docker(code, tc)

                if docker_result.state == PhysicalState.DOCKER_UNAVAILABLE:
                    # Graceful fallback to Layer 3 result
                    return exec_result

                docker_result.elapsed_ms = (time.perf_counter() - t0) * 1000
                return docker_result

            return exec_result

        return ExecutionResult(
            state=PhysicalState.TIMEOUT,
            error_message="PhysicalBudget exhausted — REJECT.",
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    def _run_restricted(self, code: str, test_cases: list[dict]) -> ExecutionResult:
        """V7.2 Layer 3: multiprocessing.Process with timeout=3s.

        Patch B.1: prevents OOM/DoS from LLM-generated test cases with
        resource-exhausting expressions (e.g. range(10**8)).
        Falls back gracefully to in-process execution on platforms where
        spawn/pickle fails (e.g. some Windows configurations).
        """
        import multiprocessing

        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
        try:
            proc = multiprocessing.Process(
                target=_sandbox_worker_fn,
                args=(child_conn, code, test_cases),
            )
            proc.start()
            proc.join(timeout=3.0)

            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=1.0)
                return ExecutionResult(
                    state=PhysicalState.TIMEOUT,
                    error_message="Sandbox execution exceeded 3s limit.",
                )

            if parent_conn.poll():
                return parent_conn.recv()
        except Exception:
            # Fallback: in-process execution on pickle/spawn failure
            return self._run_sandbox(code, test_cases)

        return ExecutionResult(
            state=PhysicalState.RUNTIME_ERR,
            error_message="Sandbox process exited without result.",
        )

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

    # ── Layer 2: Mypy ────────────────────────────────────────────────

    @staticmethod
    def _check_mypy(code: str) -> ExecutionResult:
        """V7.2 Layer 2: mypy.api.run() in-process type check.

        Uses mypy's internal API to avoid subprocess fork + typeshed reload.
        First call ~300ms (typeshed load), subsequent ~50ms (cached).
        Graceful degradation: returns PASS if mypy not installed.
        """
        try:
            from mypy import api as mypy_api
        except ImportError:
            return ExecutionResult(state=PhysicalState.PASS)  # Skip — mypy unavailable

        try:
            stdout, stderr, exit_code = mypy_api.run([
                '--ignore-missing-imports',
                '--no-error-summary',
                '-c', code,
            ])
            if exit_code != 0:
                return ExecutionResult(
                    state=PhysicalState.TYPE_MISMATCH,
                    error_message=stdout[:500] or stderr[:500] or f"mypy exit code {exit_code}",
                )
        except Exception as e:
            return ExecutionResult(
                state=PhysicalState.TYPE_MISMATCH,
                error_message=f"mypy error: {e}",
            )
        return ExecutionResult(state=PhysicalState.PASS)

    # ── Layer 2b: dmypy daemon (V7.3) ────────────────────────────────

    # Module-level state for dmypy daemon lifecycle
    _dmypy_started: bool = False
    _dmypy_lock = None  # threading.Lock, lazily initialized

    @classmethod
    def _check_mypy_daemon(cls, code: str) -> ExecutionResult:
        """V7.3 Layer 2b: dmypy daemon — persistent typeshed (~10ms vs 300ms).

        First call starts dmypy daemon. Subsequent calls use dmypy check
        for cached type-check. Falls back to _check_mypy() if dmypy is
        unavailable or crashes.

        Mathematical: path-connected state space — dmypy keeps typeshed
        loaded across checks, avoiding the disconnected subprocess hops.
        """
        import threading
        if cls._dmypy_lock is None:
            cls._dmypy_lock = threading.Lock()

        try:
            from mypy import api as mypy_api
        except ImportError:
            return cls._check_mypy(code)  # Fallback to regular mypy

        with cls._dmypy_lock:
            try:
                # First call: start daemon if not running
                if not cls._dmypy_started:
                    try:
                        mypy_api.run_dmypy([
                            'start', '--', '--ignore-missing-imports',
                        ])
                        cls._dmypy_started = True
                    except Exception:
                        # dmypy not available -> fall back to regular mypy
                        return cls._check_mypy(code)

                # Use dmypy for fast type check
                stdout, stderr, exit_code = mypy_api.run_dmypy([
                    'check', '-c', code,
                ])
                if exit_code != 0:
                    error_text = stdout[:500] or stderr[:500] or f"dmypy exit {exit_code}"
                    return ExecutionResult(
                        state=PhysicalState.TYPE_MISMATCH,
                        error_message=error_text,
                    )
            except Exception:
                # dmypy crashed or disconnected — fall back
                cls._dmypy_started = False
                return cls._check_mypy(code)

        return ExecutionResult(state=PhysicalState.PASS)

    # ── Layer 4: Docker OS isolation (V7.3) ───────────────────────────

    def _build_full_script(self, code: str,
                           test_cases: list[dict]) -> str:
        """Pack code + test_cases into a self-contained Python script.

        The script:
          1. Defines safe builtins
          2. Executes the user code
          3. Runs each test case
          4. Prints a structured JSON result line
        """
        import json
        lines = [
            "import sys, json, traceback",
            "",
            "# Restricted builtins",
            "_safe_builtins = {",
            "    'abs': abs, 'all': all, 'any': any, 'bool': bool,",
            "    'dict': dict, 'enumerate': enumerate, 'filter': filter,",
            "    'float': float, 'int': int, 'len': len, 'list': list,",
            "    'map': map, 'max': max, 'min': min, 'print': print,",
            "    'range': range, 'reversed': reversed, 'round': round,",
            "    'set': set, 'sorted': sorted, 'str': str, 'sum': sum,",
            "    'tuple': tuple, 'type': type, 'zip': zip,",
            "    'True': True, 'False': False, 'None': None,",
            "    'Exception': Exception, 'ValueError': ValueError,",
            "    'TypeError': TypeError, 'KeyError': KeyError,",
            "    'IndexError': IndexError, 'StopIteration': StopIteration,",
            "}",
            "_ns = {'__builtins__': _safe_builtins}",
            "",
            "# User code",
            "try:",
        ]
        for line in code.split("\n"):
            lines.append(f"    {line}")

        lines.append("    exec(compile(__code__, '<docker_sandbox>', 'exec'), _ns)")
        lines.append("except Exception as e:")
        lines.append("    print(json.dumps({'state': 'RUNTIME_ERR', 'error': str(e)}))")
        lines.append("    sys.exit(1)")
        lines.append("")

        # Test cases
        if test_cases:
            lines.append("# Test cases")
            lines.append("_results = []")
            lines.append(f"_tc = {json.dumps(test_cases)}")
            lines.append("for _i, _t in enumerate(_tc):")
            lines.append("    try:")
            lines.append("        _fn = None")
            lines.append("        for _k, _v in _ns.items():")
            lines.append("            if callable(_v) and not _k.startswith('_'):")
            lines.append("                _fn = _v; break")
            lines.append("        if _fn is None:")
            lines.append("            _results.append({'index': _i, 'error': 'no callable found'})")
            lines.append("            continue")
            lines.append("        _args = eval(_t['input'], {'__builtins__': {}}, {})")
            lines.append("        _got = _fn(*_args) if isinstance(_args, tuple) else _fn(_args)")
            lines.append("        _expected = _t.get('expected')")
            lines.append("        _passed = _got == _expected")
            lines.append("        _results.append({'index': _i, 'got': repr(_got),")
            lines.append("                         'expected': _expected, 'passed': _passed})")
            lines.append("    except Exception as _e:")
            lines.append("        _results.append({'index': _i, 'got': f'{type(_e).__name__}: {_e}',")
            lines.append("                         'expected': _t.get('expected'), 'passed': False})")
            lines.append("print(json.dumps({'state': 'PASS', 'test_results': _results}))")
        else:
            lines.append("print(json.dumps({'state': 'PASS'}))")

        return "\n".join(lines)

    def _run_docker(self, code: str,
                    test_cases: list[dict]) -> ExecutionResult:
        """V7.3 Layer 4: Docker container OS isolation.

        Red-Team #1: stdin pipe instead of volume mount — direct morphism
        avoids cross-OS pullback failure on Windows/WSL2.

        Mathematical: S4 filter in the code filtration tower.
        Topological: C \\ S4 = open set of "code that violates OS isolation."
        Docker shrinks this open set to near measure-zero.

        Graceful degradation:
          - Docker not installed -> DOCKER_UNAVAILABLE (fallback S3)
          - Container timeout -> TIMEOUT (semantic escape)
          - Container crash -> RUNTIME_ERR (retryable)
        """
        import subprocess

        full_script = self._build_full_script(code, test_cases)

        try:
            result = subprocess.run([
                'docker', 'run', '--rm', '-i',
                '--network=none',
                '--memory=256m',
                '--cpus=0.5',
                '--read-only',
                '--tmpfs=/tmp:rw,noexec',
                'python:3.11-slim',
                'timeout', '5', 'python', '-c',
                'import sys; exec(sys.stdin.read())',
            ], input=full_script, capture_output=True, text=True, timeout=10)

        except FileNotFoundError:
            return ExecutionResult(
                state=PhysicalState.DOCKER_UNAVAILABLE,
                error_message="Docker is not installed or not in PATH.",
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                state=PhysicalState.TIMEOUT,
                error_message="Docker container exceeded 10s deadline.",
            )

        if result.returncode != 0:
            stderr = result.stderr[:500] or "unknown docker error"
            # Parse the JSON error if possible
            try:
                import json
                data = json.loads(stderr.split('\n')[-2] if '\n' in stderr else stderr)
                return ExecutionResult(
                    state=PhysicalState.RUNTIME_ERR,
                    error_message=data.get('error', stderr),
                )
            except Exception:
                pass
            return ExecutionResult(
                state=PhysicalState.RUNTIME_ERR,
                error_message=stderr,
            )

        # Parse JSON result from stdout
        try:
            import json
            # Last non-empty line should be the JSON result
            output_lines = [l for l in result.stdout.split('\n') if l.strip()]
            if output_lines:
                data = json.loads(output_lines[-1])
                state_str = data.get('state', 'PASS')
                if state_str == 'PASS':
                    test_results = data.get('test_results', [])
                    all_passed = all(t.get('passed', False) for t in test_results)
                    if test_results and not all_passed:
                        failed_count = sum(1 for t in test_results if not t.get('passed', False))
                        return ExecutionResult(
                            state=PhysicalState.RUNTIME_ERR,
                            error_message=f"{failed_count}/{len(test_results)} test cases failed",
                            test_results=test_results,
                        )
                    return ExecutionResult(
                        state=PhysicalState.PASS,
                        output=result.stdout[:500],
                        test_results=test_results,
                    )
                else:
                    return ExecutionResult(
                        state=PhysicalState.RUNTIME_ERR,
                        error_message=data.get('error', 'Docker sandbox failed'),
                    )
        except Exception:
            pass

        return ExecutionResult(
            state=PhysicalState.PASS,
            output=result.stdout[:500],
        )

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


def _sandbox_worker_fn(conn, code_str: str, tc_list: list) -> None:
    """Module-level worker for multiprocessing.Process (Patch B.1).

    Must be at module level because Windows spawn requires picklable targets.
    Creates a fresh SandboxExecutor in the child process.
    """
    try:
        executor = SandboxExecutor()
        result = executor._run_sandbox(code_str, tc_list)
        conn.send(result)
    except Exception as e:
        conn.send(ExecutionResult(
            state=PhysicalState.RUNTIME_ERR,
            error_message=f"Sandbox worker crashed: {e}",
        ))
    finally:
        conn.close()


def _extract_lineno_from_tb(tb) -> int | None:
    """Extract line number from traceback extract."""
    if tb:
        for frame in tb:
            if hasattr(frame, "lineno"):
                return frame.lineno
            elif isinstance(frame, tuple) and len(frame) >= 2:
                return frame[1]
    return None
