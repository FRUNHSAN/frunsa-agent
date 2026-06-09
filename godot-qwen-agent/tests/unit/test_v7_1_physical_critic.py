"""V7.1 Physical Critic — unit tests for SandboxExecutor, ErrorMapper, DualTrackCritic.

Pure tests: no LLM, no I/O. Validates:
  - AST check catches syntax errors (Layer 1)
  - Sandbox execution with test cases (Layer 3)
  - ErrorMapper assertion diff + traceback fallback
  - DualTrackCritic multiplicative gating (θ AND q)
  - Intent-driven override (PSEUDOCODE skips physical)
  - PhysicalBudget exhaustion + reset
"""

import pytest
from core.execution.sandbox import SandboxExecutor, PhysicalState, ExecutionResult
from core.execution.error_mapper import ErrorMapper, ErrorMapping
from core.critic.dual_track import (
    DualTrackCritic, CriticDecision, CriticVerdict, PhysicalBudget,
)


# ═══════════════════════════════════════════════════════════════════════════
# SandboxExecutor — Layer 1 (AST)
# ═══════════════════════════════════════════════════════════════════════════

class TestASTCheck:
    def test_valid_code_passes(self):
        executor = SandboxExecutor()
        result = executor.run("x = 1 + 1")
        assert result.state == PhysicalState.PASS

    def test_syntax_error_caught(self):
        executor = SandboxExecutor()
        result = executor.run("def foo(:\n    pass")  # invalid syntax
        assert result.state == PhysicalState.COMPILE_ERR
        assert "SyntaxError" in result.error_message

    def test_missing_colon(self):
        executor = SandboxExecutor()
        result = executor.run("def foo()\n    return 1")
        assert result.state == PhysicalState.COMPILE_ERR

    def test_runtime_error_has_correct_state(self):
        executor = SandboxExecutor()
        result = executor.run("1 / 0")  # runtime error
        assert result.state == PhysicalState.RUNTIME_ERR

    def test_pseudocode_skips_execution(self):
        executor = SandboxExecutor()
        result = executor.run(
            "def connect_to_mars():\n    # TODO: implement\n    pass",
            intent_type="PSEUDOCODE",
        )
        assert result.state == PhysicalState.PASS
        assert "skipping execution" in result.output


# ═══════════════════════════════════════════════════════════════════════════
# SandboxExecutor — Layer 3 (Test Cases)
# ═══════════════════════════════════════════════════════════════════════════

VALID_QUICKSORT = """
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[0]
    left = [x for x in arr[1:] if x <= pivot]
    right = [x for x in arr[1:] if x > pivot]
    return quicksort(left) + [pivot] + quicksort(right)
"""


class TestSandboxExecution:
    def test_all_tests_pass(self):
        executor = SandboxExecutor()
        result = executor.run(VALID_QUICKSORT, test_cases=[
            {"input": "[3,1,4,1,5]", "expected": [1,1,3,4,5]},
            {"input": "[1]", "expected": [1]},
        ])
        assert result.state == PhysicalState.PASS
        assert all(t["passed"] for t in result.test_results)

    def test_test_case_failure_caught(self):
        executor = SandboxExecutor()
        result = executor.run(VALID_QUICKSORT, test_cases=[
            {"input": "[3,1,4,1,5]", "expected": [3,1,4,1,5]},  # wrong expected
        ])
        assert result.state == PhysicalState.RUNTIME_ERR
        assert not result.test_results[0]["passed"]

    def test_runtime_error_in_code(self):
        executor = SandboxExecutor()
        result = executor.run("""
def bad(arr):
    return arr[10]  # IndexError
""", test_cases=[
            {"input": "[1,2,3]", "expected": "IndexError"},
        ])
        assert result.state == PhysicalState.RUNTIME_ERR

    def test_no_test_cases_runs_code(self):
        executor = SandboxExecutor()
        result = executor.run(VALID_QUICKSORT)
        assert result.state == PhysicalState.PASS


# ═══════════════════════════════════════════════════════════════════════════
# ErrorMapper
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorMapper:
    def test_assertion_diff_path(self):
        mapper = ErrorMapper()
        result = ExecutionResult(
            state=PhysicalState.RUNTIME_ERR,
            test_results=[
                {"index": 0, "input": "[3,1,4]", "expected": 4, "got": 1, "passed": False},
                {"index": 1, "input": "[1]", "expected": 1, "got": 1, "passed": True},
            ],
        )
        mapping = mapper.map(result)
        assert mapping.error_type == "AssertionDiff"
        assert "test_case[0]" in mapping.location
        assert "expected=4" in mapping.constraint_violated
        assert mapping.fix_hint

    def test_traceback_fallback(self):
        mapper = ErrorMapper()
        result = ExecutionResult(
            state=PhysicalState.COMPILE_ERR,
            error_message="SyntaxError: invalid syntax\n  at line 3",
            error_line=3,
        )
        mapping = mapper.map(result, original_code="def foo(:\n    pass")
        assert mapping.error_type == "COMPILE_ERR"
        assert "line 3" in mapping.location
        assert mapping.raw_context

    def test_planning_format(self):
        mapper = ErrorMapper()
        mapping = ErrorMapping(
            error_type="AssertionDiff",
            location="test_case[0]",
            constraint_violated="expected=[1,2,3], got=[3,2,1]",
            fix_hint="Check sort order.",
        )
        formatted = mapper.format_for_planning(mapping)
        assert "[PHYSICAL CONSTRAINT]" in formatted
        assert "AssertionDiff" in formatted
        assert "Check sort order." in formatted


# ═══════════════════════════════════════════════════════════════════════════
# DualTrackCritic
# ═══════════════════════════════════════════════════════════════════════════

class TestDualTrackCritic:
    def setup_method(self):
        self.critic = DualTrackCritic()

    def test_semantic_pass_no_physical(self):
        d = self.critic.evaluate(semantic_score=0.80, theta=0.70)
        assert d.verdict == CriticVerdict.PASS

    def test_semantic_fail_no_physical(self):
        d = self.critic.evaluate(semantic_score=0.50, theta=0.70)
        assert d.verdict == CriticVerdict.RETRY

    def test_physical_pass_semantic_pass(self):
        d = self.critic.evaluate(
            semantic_score=0.80, theta=0.70,
            physical_result=ExecutionResult(state=PhysicalState.PASS),
        )
        assert d.verdict == CriticVerdict.PASS

    def test_compile_err_retryable(self):
        d = self.critic.evaluate(
            semantic_score=0.80, theta=0.70,
            physical_result=ExecutionResult(
                state=PhysicalState.COMPILE_ERR,
                error_message="SyntaxError: invalid syntax",
            ),
            fix_hint="Fix syntax",
        )
        assert d.verdict == CriticVerdict.RETRY
        assert d.fix_hint == "Fix syntax"

    def test_sandbox_violation_fatal(self):
        d = self.critic.evaluate(
            semantic_score=0.99, theta=0.70,
            physical_result=ExecutionResult(state=PhysicalState.SANDBOX_VIOLATION),
        )
        assert d.verdict == CriticVerdict.FAIL_FATAL

    def test_pseudocode_overrides_compile_err(self):
        """Defensive Axiom C: PSEUDOCODE skips physical, passes on semantic."""
        d = self.critic.evaluate(
            semantic_score=0.90, theta=0.70,
            physical_result=ExecutionResult(state=PhysicalState.COMPILE_ERR),
            intent_type="PSEUDOCODE",
        )
        assert d.verdict == CriticVerdict.PASS

    def test_demonstration_overrides_physical_fail(self):
        d = self.critic.evaluate(
            semantic_score=0.85, theta=0.70,
            physical_result=ExecutionResult(state=PhysicalState.RUNTIME_ERR),
            intent_type="DEMONSTRATION",
        )
        assert d.verdict == CriticVerdict.PASS


# ═══════════════════════════════════════════════════════════════════════════
# PhysicalBudget
# ═══════════════════════════════════════════════════════════════════════════

class TestPhysicalBudget:
    def test_initial_budget(self):
        b = PhysicalBudget(max_budget=5)
        assert b.remaining == 5
        assert not b.is_exhausted

    def test_spend_reduces_budget(self):
        b = PhysicalBudget(max_budget=3)
        assert b.spend(1)
        assert b.remaining == 2
        assert b.spend(2)
        assert b.remaining == 0
        assert b.is_exhausted

    def test_exhausted_blocks_spend(self):
        b = PhysicalBudget(max_budget=1)
        b.spend(1)
        assert not b.spend(1)
        assert b.is_exhausted

    def test_reset(self):
        b = PhysicalBudget(max_budget=3)
        b.spend(2)
        b.reset()
        assert b.remaining == 3

    def test_warn_message(self):
        b = PhysicalBudget(max_budget=1)
        b.spend(1)
        assert "[WARN]" in b.warn_if_exhausted()
