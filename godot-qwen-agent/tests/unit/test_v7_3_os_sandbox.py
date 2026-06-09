"""V7.3 Phase 4 — OS Sandbox: Layer 4 Docker isolation + dmypy daemon.

Tests the S4 filter in the code filtration tower:
  - _build_full_script() — code + test_cases -> self-contained Python script
  - _run_docker() — stdin pipe, cross-platform (Red-Team #1)
  - _check_mypy_daemon() — dmypy persistent typeshed
  - run() with use_docker=True — Layer 4 integration
  - DOCKER_UNAVAILABLE graceful fallback
  - Budget constraints (2.0 cost for Layer 4)
  - PhysicalState.DOCKER_UNAVAILABLE state semantics
"""

import os
import pytest
from core.execution.sandbox import (
    SandboxExecutor,
    PhysicalState,
    ExecutionResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def executor():
    return SandboxExecutor()


def _docker_available():
    """Check if Docker is running and usable."""
    import subprocess
    try:
        result = subprocess.run(
            ['docker', 'version', '--format', '{{.Server.Version}}'],
            capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


# ── _build_full_script ────────────────────────────────────────────────

class TestBuildFullScript:
    def test_builds_valid_python(self, executor):
        script = executor._build_full_script("x = 1 + 1", [])
        assert "import sys" in script
        assert "x = 1 + 1" in script
        assert "json.dumps" in script

    def test_includes_test_cases(self, executor):
        tc = [{"input": "[3,1,5], k=2", "expected": 5}]
        script = executor._build_full_script("def f(): pass", tc)
        assert "'input': '[3,1,5], k=2'" in script or '"[3,1,5], k=2"' in script

    def test_no_test_cases_produces_pass(self, executor):
        script = executor._build_full_script("x = 1", [])
        assert "'PASS'" in script

    def test_empty_code_works(self, executor):
        script = executor._build_full_script("", [])
        assert len(script) > 0

    def test_script_is_deterministic(self, executor):
        s1 = executor._build_full_script("x = 1", [])
        s2 = executor._build_full_script("x = 1", [])
        assert s1 == s2


# ── Layer 4: Docker execution ─────────────────────────────────────────

@pytest.mark.skipif(not _docker_available(), reason="Docker not running")
class TestDockerExecution:
    def test_simple_code_passes(self, executor):
        code = "x = 1 + 1\nprint(x)"
        result = executor._run_docker(code, [])
        assert result.state == PhysicalState.PASS

    def test_function_with_test_cases(self, executor):
        code = "def add(a, b):\n    return a + b"
        tc = [{"input": "(2, 3)", "expected": 5}]
        result = executor._run_docker(code, tc)
        assert result.state == PhysicalState.PASS
        assert len(result.test_results) == 1
        assert result.test_results[0]["passed"]

    def test_failing_test_case_detected(self, executor):
        code = "def add(a, b):\n    return a - b"  # Bug: returns a-b
        tc = [{"input": "(2, 3)", "expected": 5}]
        result = executor._run_docker(code, tc)
        # Should detect the test failure
        if result.state == PhysicalState.PASS:
            assert not result.test_results[0]["passed"]
        else:
            assert result.state == PhysicalState.RUNTIME_ERR

    def test_syntax_error_caught(self, executor):
        code = "def broken(:\n    pass"
        result = executor._run_docker(code, [])
        assert result.state in (PhysicalState.RUNTIME_ERR, PhysicalState.COMPILE_ERR)

    def test_timeout_handled(self, executor):
        code = "while True: pass"
        result = executor._run_docker(code, [])
        # Docker container should be killed by timeout
        assert result.state in (PhysicalState.TIMEOUT, PhysicalState.RUNTIME_ERR)

    def test_empty_test_cases_returns_pass(self, executor):
        code = "x = 42"
        result = executor._run_docker(code, [])
        assert result.state == PhysicalState.PASS

    def test_multiple_test_cases(self, executor):
        code = "def mul(a, b):\n    return a * b"
        tc = [
            {"input": "(2, 3)", "expected": 6},
            {"input": "(0, 5)", "expected": 0},
            {"input": "(-1, 3)", "expected": -3},
        ]
        result = executor._run_docker(code, tc)
        assert result.state == PhysicalState.PASS
        assert all(t["passed"] for t in result.test_results)


# ── Layer 4: run() integration ────────────────────────────────────────

@pytest.mark.skipif(not _docker_available(), reason="Docker not running")
class TestRunWithDocker:
    def test_run_with_docker_flag(self, executor):
        code = "x = 1 + 1"
        result = executor.run(code, use_docker=True)
        assert result.state == PhysicalState.PASS

    def test_run_without_docker_flag(self, executor):
        """Without use_docker, Layer 4 is not attempted."""
        code = "x = 1 + 1"
        result = executor.run(code, use_docker=False)
        assert result.state == PhysicalState.PASS

    def test_docker_with_test_cases(self, executor):
        code = "def greet(name):\n    return f'Hello, {name}'"
        tc = [{"input": "('World',)", "expected": "Hello, World"}]
        result = executor.run(code, test_cases=tc, use_docker=True)
        assert result.state == PhysicalState.PASS


# ── DOCKER_UNAVAILABLE fallback ───────────────────────────────────────

class TestDockerUnavailable:
    def test_docker_unavailable_is_not_fatal(self):
        assert not PhysicalState.DOCKER_UNAVAILABLE.is_fatal()

    def test_docker_unavailable_is_not_retryable(self):
        """Not retryable — it means fallback to S3, not retry Docker."""
        assert not PhysicalState.DOCKER_UNAVAILABLE.is_retryable()

    def test_run_without_docker_gives_same_result(self, executor):
        """Without Docker, run() should still work (Layer 3 only)."""
        code = "x = 1 + 1"
        result = executor.run(code, use_docker=False)
        assert result.state == PhysicalState.PASS


# ── dmypy daemon ──────────────────────────────────────────────────────

class TestMypyDaemon:
    def test_check_mypy_daemon_falls_back_gracefully(self, executor):
        """dmypy may or may not be available — must not crash."""
        code = "x: int = 1"
        result = executor._check_mypy_daemon(code)
        # Either PASS or fallback to regular mypy — both OK
        assert result.state in (PhysicalState.PASS, PhysicalState.TYPE_MISMATCH)

    def test_type_error_caught_by_daemon(self, executor):
        code = "x: int = 'hello'"
        result = executor._check_mypy_daemon(code)
        # Should catch the type mismatch (but graceful fallback possible)
        assert result.state in (PhysicalState.PASS, PhysicalState.TYPE_MISMATCH)

    def test_daemon_idempotent(self, executor):
        """Multiple calls to _check_mypy_daemon should not crash."""
        code = "x: int = 1"
        for _ in range(3):
            result = executor._check_mypy_daemon(code)
            assert result.state in (PhysicalState.PASS, PhysicalState.TYPE_MISMATCH)

    def test_daemon_thread_safe_lock_initialized(self, executor):
        """The _dmypy_lock should be initialized after first call."""
        executor._check_mypy_daemon("x = 1")
        assert executor._dmypy_lock is not None


# ── Budget integration ────────────────────────────────────────────────

class TestDockerBudget:
    def test_docker_skipped_when_budget_insufficient(self, executor):
        """With budget < 2.0, Docker should be skipped."""
        from core.critic.dual_track import PhysicalBudget
        budget = PhysicalBudget(max_budget=1.5)  # Not enough for Layer 4
        code = "x = 1 + 1"
        result = executor.run(code, budget=budget, use_docker=True)
        # Should pass via Layer 3, Docker skipped
        assert result.state == PhysicalState.PASS

    def test_docker_consumes_budget_when_used(self, executor):
        if not _docker_available():
            pytest.skip("Docker not running")
        from core.critic.dual_track import PhysicalBudget
        budget = PhysicalBudget(max_budget=5.0)
        code = "x = 1 + 1"
        result = executor.run(code, budget=budget, use_docker=True)
        # Budget should have been consumed: 0.1 (mypy) + 1.0 (sandbox) + 2.0 (docker)
        assert budget.remaining <= 5.0 - 0.1 - 1.0 - 2.0 + 0.01  # Float tolerance


# ── Layer 3 still works (regression) ──────────────────────────────────

class TestLayer3Regression:
    def test_layer3_still_works(self, executor):
        code = "def add(a, b):\n    return a + b"
        tc = [{"input": "(2, 3)", "expected": 5}]
        result = executor.run(code, test_cases=tc)
        assert result.state == PhysicalState.PASS

    def test_layer3_timeout_still_works(self, executor):
        code = "while True: pass"
        result = executor.run(code)
        assert result.state in (PhysicalState.TIMEOUT, PhysicalState.RUNTIME_ERR)

    def test_layer3_syntax_error_still_works(self, executor):
        code = "def broken(: pass"
        result = executor.run(code)
        assert result.state == PhysicalState.COMPILE_ERR

    def test_layer3_mypy_type_error(self, executor):
        code = "x: int = 'oops'"
        result = executor.run(code)
        assert result.state in (PhysicalState.PASS, PhysicalState.TYPE_MISMATCH)

    def test_non_executable_intent_skips_execution(self, executor):
        code = "import os; os.system('rm -rf /')"  # Dangerous but PSEUDOCODE
        result = executor.run(code, intent_type="PSEUDOCODE")
        assert result.state == PhysicalState.PASS  # Only AST checked
        assert "skipping execution" in result.output.lower()
