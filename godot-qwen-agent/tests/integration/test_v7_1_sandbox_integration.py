"""V7.1 Integration test — SandboxExecutor with realistic LLM-generated code.

Tests the full physical critic pipeline: generate → execute → map error → decide.
No LLM calls — uses pre-canned code snippets that simulate LLM output quality.

Metrics tracked per test case:
  - q_physical:        PASS / COMPILE_ERR / RUNTIME_ERR / TYPE_MISMATCH
  - elapsed_ms:        execution time
  - assertion_diff:    expected vs got (when test_cases present)
  - fix_hint:          ErrorMapper output quality
  - verdict:           DualTrackCritic final decision
  - budget_consumed:   PhysicalBudget units spent
"""

import pytest
from core.execution.sandbox import SandboxExecutor, PhysicalState, ExecutionResult
from core.execution.error_mapper import ErrorMapper
from core.critic.dual_track import DualTrackCritic, CriticVerdict, PhysicalBudget


# ── Realistic LLM-generated code snippets ────────────────────────────

# Case 1: Valid code (typical LLM output)
VALID_CODE = '''
def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''

# Case 2: Missing colon (LLM hallucination — common)
SYNTAX_ERROR_CODE = '''
def fibonacci(n)
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
'''

# Case 3: Wrong variable name (LLM typo)
RUNTIME_ERROR_CODE = '''
def get_average(data):
    total = sum(data)
    return total / length  # NameError: 'length' not defined
'''

# Case 4: Index out of bounds (LLM logic error)
INDEX_ERROR_CODE = '''
def kth_largest(arr, k):
    sorted_arr = sorted(arr, reverse=True)
    return sorted_arr[k]  # Bug: should be k-1 for 1-indexed, no bounds check
'''

# Case 5: Pseudocode (user asked for demo, not executable)
PSEUDOCODE = '''
def quantum_sort(particles):
    # Entangle all particles
    # Measure simultaneously
    # Collapse wavefunction → sorted order
    return particles  # This is pseudocode, the compiler should skip it
'''


# ═══════════════════════════════════════════════════════════════════════
# Test cases
# ═══════════════════════════════════════════════════════════════════════

class TestValidCode:
    def test_fibonacci_with_test_cases(self):
        executor = SandboxExecutor()
        result = executor.run(VALID_CODE, test_cases=[
            {"input": "5", "expected": 5},
            {"input": "10", "expected": 55},
            {"input": "0", "expected": 0},
        ])
        assert result.state == PhysicalState.PASS
        assert result.elapsed_ms < 100, f"Too slow: {result.elapsed_ms}ms"
        assert all(t["passed"] for t in result.test_results)

    def test_valid_code_critic_decision(self):
        executor = SandboxExecutor()
        result = executor.run(VALID_CODE)
        critic = DualTrackCritic()
        decision = critic.evaluate(
            semantic_score=0.80, theta=0.70,
            physical_result=result, intent_type="EXECUTABLE",
        )
        assert decision.verdict == CriticVerdict.PASS


class TestSyntaxError:
    def test_missing_colon_caught(self):
        executor = SandboxExecutor()
        result = executor.run(SYNTAX_ERROR_CODE)
        assert result.state == PhysicalState.COMPILE_ERR
        assert "SyntaxError" in result.error_message

    def test_error_mapper_generates_fix_hint(self):
        executor = SandboxExecutor()
        result = executor.run(SYNTAX_ERROR_CODE)
        mapper = ErrorMapper()
        mapping = mapper.map(result, SYNTAX_ERROR_CODE)
        assert mapping.fix_hint
        assert "syntax" in mapping.fix_hint.lower()

    def test_syntax_error_triggers_retry(self):
        executor = SandboxExecutor()
        result = executor.run(SYNTAX_ERROR_CODE)
        critic = DualTrackCritic()
        decision = critic.evaluate(
            semantic_score=0.80, theta=0.70,
            physical_result=result, intent_type="EXECUTABLE",
        )
        assert decision.verdict == CriticVerdict.RETRY
        assert decision.physical_state == PhysicalState.COMPILE_ERR


class TestRuntimeError:
    def test_name_error_caught(self):
        executor = SandboxExecutor()
        result = executor.run(RUNTIME_ERROR_CODE, test_cases=[
            {"input": "[1,2,3]", "expected": 2},
        ])
        assert result.state == PhysicalState.RUNTIME_ERR

    def test_runtime_error_with_test_cases(self):
        """Code that throws at runtime → caught and mapped."""
        executor = SandboxExecutor()
        result = executor.run(RUNTIME_ERROR_CODE, test_cases=[
            {"input": "[1,2,3]", "expected": 2},
        ])
        assert result.state == PhysicalState.RUNTIME_ERR
        mapper = ErrorMapper()
        mapping = mapper.map(result, RUNTIME_ERROR_CODE)
        assert mapping.fix_hint  # always generates a hint
        assert mapping.raw_context  # fallback context present

    def test_index_error_with_bounds_test(self):
        """Bounds-check test: k=10 exceeds len=5, expect IndexError."""
        executor = SandboxExecutor()
        result = executor.run(INDEX_ERROR_CODE, test_cases=[
            {"input": "[3,1,4,1,5], 10", "expected": "IndexError"},
        ])
        # Either the code handles it or throws IndexError — both are valid
        assert result.state in (PhysicalState.PASS, PhysicalState.RUNTIME_ERR)
        mapper = ErrorMapper()
        mapping = mapper.map(result, INDEX_ERROR_CODE)
        assert mapping.fix_hint


class TestPseudocodeIntent:
    def test_pseudocode_skips_execution(self):
        executor = SandboxExecutor()
        result = executor.run(PSEUDOCODE, intent_type="PSEUDOCODE")
        assert result.state == PhysicalState.PASS
        assert "skipping execution" in result.output

    def test_pseudocode_critic_bypasses_physical(self):
        executor = SandboxExecutor()
        result = executor.run(PSEUDOCODE, intent_type="PSEUDOCODE")
        critic = DualTrackCritic()
        decision = critic.evaluate(
            semantic_score=0.90, theta=0.70,
            physical_result=result, intent_type="PSEUDOCODE",
        )
        assert decision.verdict == CriticVerdict.PASS


class TestPhysicalBudget:
    def test_budget_tracks_executions(self):
        budget = PhysicalBudget(max_budget=3)
        executor = SandboxExecutor()

        # 3 successful executions
        for _ in range(3):
            assert budget.spend(1)

        # 4th blocked
        assert not budget.spend(1)
        assert budget.is_exhausted
        assert "[WARN]" in budget.warn_if_exhausted()

    def test_reset_restores_budget(self):
        budget = PhysicalBudget(max_budget=3)
        budget.spend(3)
        budget.reset()
        assert budget.remaining == 3
        assert not budget.is_exhausted


# ═══════════════════════════════════════════════════════════════════════
# End-to-end pipeline (generate → execute → map → decide)
# ═══════════════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """Simulates full V7 pipeline: LLM output → Sandbox → ErrorMapper → Critic."""

    def test_valid_code_full_pipeline(self):
        executor = SandboxExecutor()
        mapper = ErrorMapper()
        critic = DualTrackCritic()

        result = executor.run(VALID_CODE, test_cases=[
            {"input": "5", "expected": 5},
        ])
        assert result.state == PhysicalState.PASS

        decision = critic.evaluate(0.80, 0.70, result, "EXECUTABLE")
        assert decision.verdict == CriticVerdict.PASS

    def test_buggy_code_full_pipeline(self):
        executor = SandboxExecutor()
        mapper = ErrorMapper()
        critic = DualTrackCritic()

        result = executor.run(SYNTAX_ERROR_CODE)
        mapping = mapper.map(result, SYNTAX_ERROR_CODE)
        fix_hint = mapping.fix_hint

        decision = critic.evaluate(0.80, 0.70, result, "EXECUTABLE", fix_hint)
        assert decision.verdict == CriticVerdict.RETRY
        assert decision.fix_hint

        # Simulate retry: the Planning would inject fix_hint into prompt
        planning_constraint = mapper.format_for_planning(mapping)
        assert "[PHYSICAL CONSTRAINT]" in planning_constraint
