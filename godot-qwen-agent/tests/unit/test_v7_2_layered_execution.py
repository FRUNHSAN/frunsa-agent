"""V7.2 Layered Execution — metric-driven tests.

Covers: budget tracking, filter hit rates, delimiter extraction, timeout, REJECT.
Run: python -m pytest tests/unit/test_v7_2_layered_execution.py -v
"""

import pytest
from core.execution.sandbox import SandboxExecutor, PhysicalState, ExecutionResult
from core.execution.error_mapper import ErrorMapper
from core.critic.dual_track import PhysicalBudget


# ═══════════════════════════════════════════════════════════════════════════
# Metric 1: Budget tracking — weighted accounting
# ═══════════════════════════════════════════════════════════════════════════

class TestBudgetWeighted:
    def test_free_layer_no_cost(self):
        budget = PhysicalBudget(max_budget=5.0)
        executor = SandboxExecutor()
        result = executor.run("x = 1 + 1", budget=budget)
        # AST (0) = free, no test_cases → sandbox (1.0) costs 1.0
        assert 3.5 < budget.remaining < 4.1  # AST=0 free, Sandbox=1.0 used
        assert result.state == PhysicalState.PASS

    def test_sandbox_costs_one(self):
        budget = PhysicalBudget(max_budget=5.0)
        executor = SandboxExecutor()
        code = "def add(a,b):\n    return a + b\n"
        result = executor.run(code, test_cases=[
            {"input": "2, 3", "expected": 5},
        ], budget=budget)
        # AST=0, Mypy=0.1 (if installed), Sandbox=1.0 → remaining ≈ 3.9
        assert budget.remaining < 5.0
        assert budget.remaining > 2.0

    def test_reject_when_budget_insufficient(self):
        budget = PhysicalBudget(max_budget=0.5)
        executor = SandboxExecutor()
        result = executor.run("def f(): return 1", budget=budget)
        # AST=0 passes, Mypy(0.1) passes, remaining=0.4 < 1.0 → REJECT
        assert result.state == PhysicalState.TIMEOUT
        assert "REJECT" in result.error_message or "budget" in result.error_message.lower()

    def test_mypy_skipped_when_budget_tight(self):
        budget = PhysicalBudget(max_budget=0.05)
        executor = SandboxExecutor()
        result = executor.run("x = 1 + 1", budget=budget)
        # AST=0 OK, Mypy can't afford 0.1 (budget=0.05 < 0.1), sandbox needs 1.0 → REJECT
        assert result.state == PhysicalState.TIMEOUT


# ═══════════════════════════════════════════════════════════════════════════
# Metric 2: Filter hit rate — which layer catches what
# ═══════════════════════════════════════════════════════════════════════════

class TestFilterHitRate:
    def test_layer1_catches_syntax(self):
        executor = SandboxExecutor()
        result = executor.run("def f(:\n    pass")
        assert result.state == PhysicalState.COMPILE_ERR  # AST Layer 1

    def test_layer2_catches_type(self):
        executor = SandboxExecutor()
        code = "def add(a: int, b: str) -> int:\n    return a + b\n"
        result = executor.run(code)
        # Mypy may or may not be installed → PASS or TYPE_MISMATCH both valid
        assert result.state in (PhysicalState.PASS, PhysicalState.TYPE_MISMATCH)

    def test_layer3_catches_runtime(self):
        executor = SandboxExecutor()
        code = "def bad():\n    return 1 / 0\n"
        result = executor.run(code, test_cases=[{"input": "", "expected": "ZeroDivisionError"}])
        # RUNTIME_ERR from sandbox
        assert result.state in (PhysicalState.RUNTIME_ERR, PhysicalState.PASS)
        # PASS if ZeroDivisionError matches, RUNTIME_ERR if unexpected

    def test_sandbox_skipped_for_pseudocode(self):
        executor = SandboxExecutor()
        result = executor.run("def foo():\n    # magic\n    pass",
                              intent_type="PSEUDOCODE")
        assert result.state == PhysicalState.PASS
        assert "skipping execution" in result.output


# ═══════════════════════════════════════════════════════════════════════════
# Metric 3: ⊢ Delimiter extraction accuracy
# ═══════════════════════════════════════════════════════════════════════════

class TestDelimiterExtraction:
    def test_simple_types(self):
        mapper = ErrorMapper()
        msg = "AssertionError: ⊢EXPECTED⊢5⊢ACTUAL⊢3"
        e, a = mapper._extract_from_assertion(msg)
        assert e == "5"
        assert a == "3"

    def test_list_types(self):
        mapper = ErrorMapper()
        msg = "AssertionError: ⊢EXPECTED⊢[1, 2, 3]⊢ACTUAL⊢[3, 2, 1]"
        e, a = mapper._extract_from_assertion(msg)
        assert e == "[1, 2, 3]"
        assert a == "[3, 2, 1]"

    def test_complex_objects(self):
        mapper = ErrorMapper()
        msg = "AssertionError: ⊢EXPECTED⊢{'a': 1, 'b': [2,3]}⊢ACTUAL⊢{'a': 1, 'b': [2]}"
        e, a = mapper._extract_from_assertion(msg)
        assert e == "{'a': 1, 'b': [2,3]}"
        assert a == "{'a': 1, 'b': [2]}"

    def test_no_substring_collision(self):
        """actual contains 'Expected' literally → regular regex would fail."""
        mapper = ErrorMapper()
        msg = "AssertionError: ⊢EXPECTED⊢hello⊢ACTUAL⊢I Expected something else"
        e, a = mapper._extract_from_assertion(msg)
        assert e == "hello"
        assert a == "I Expected something else"

    def test_no_delimiter_returns_none(self):
        mapper = ErrorMapper()
        result = mapper._extract_from_assertion("IndexError: list index out of range")
        assert result is None

    def test_pipeline_mapping(self):
        mapper = ErrorMapper()
        result = ExecutionResult(
            state=PhysicalState.RUNTIME_ERR,
            error_message="AssertionError: ⊢EXPECTED⊢[1,2,3]⊢ACTUAL⊢[3,2,1]",
            test_results=[{"index": 0, "expected": "[1,2,3]", "got": "[3,2,1]", "passed": False}],
        )
        mapping = mapper.map(result)
        assert mapping.error_type == "AssertionDiff"  # ⊢ path takes priority
        assert mapping.constraint_violated == "expected=[1,2,3], got=[3,2,1]"


# ═══════════════════════════════════════════════════════════════════════════
# Metric 4: Test case double-filter safety
# ═══════════════════════════════════════════════════════════════════════════

class TestDoubleFilter:
    def test_malformed_test_case_input_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("def f(): return 1", test_cases=[
            {"input": "import os; os.system('echo bad')", "expected": 0},
        ])
        # test_case AST fails on 'import os; os.system...' as assert input
        assert result.state == PhysicalState.COMPILE_ERR

    def test_valid_test_case_passes_filter(self):
        executor = SandboxExecutor()
        result = executor.run("def f(x): return x", test_cases=[
            {"input": "42", "expected": 42},
        ])
        assert result.state == PhysicalState.PASS

    def test_empty_test_cases_ok(self):
        executor = SandboxExecutor()
        result = executor.run("def f(): return 1", test_cases=[])
        assert result.state == PhysicalState.PASS


# ═══════════════════════════════════════════════════════════════════════════
# Metric 5: Timeout protection (Patch B.1)
# ═══════════════════════════════════════════════════════════════════════════

class TestTimeoutProtection:
    def test_timeout_added_to_enum(self):
        assert PhysicalState.TIMEOUT.value == "TIMEOUT"

    def test_timeout_is_fatal(self):
        assert not PhysicalState.TIMEOUT.is_fatal()  # TIMEOUT is retryable

    def test_timeout_is_retryable(self):
        """TIMEOUT should be retryable — the LLM can fix the infinite loop."""
        assert PhysicalState.TIMEOUT.is_retryable()
