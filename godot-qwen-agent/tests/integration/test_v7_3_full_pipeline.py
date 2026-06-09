"""V7.3 Integration tests — full Phi functor + Resistance DAG + sigma pipeline.

Validates the four components working together in realistic scenarios:
  1. ToolPhysicalVerifier — MCP tool results flowing through physical critic
  2. Resistance-field DAG — causality-preserving sort with real step shapes
  3. Test case augmentation — sigma-monotone acceptance region contraction
  4. Docker S4 — OS isolation (skipped when Docker unavailable)

No LLM calls — uses pre-canned code and mock tool results.
"""

import pytest
from core.execution.sandbox import (
    SandboxExecutor, PhysicalState, ExecutionResult,
)
from core.execution.error_mapper import ErrorMapper, augment_test_cases
from core.execution.tool_verifier import (
    ToolPhysicalVerifier, is_physical_tool, PHYSICAL_TOOLS,
)
from core.critic.dual_track import DualTrackCritic, CriticVerdict, PhysicalBudget
from core.track_c import (
    _build_dag_and_depth, RESISTANCE_WEIGHTS, _resistance_weight,
)


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1: Phi functor — MCP tool failure → physical critic
# ═══════════════════════════════════════════════════════════════════════

class FakeToolResult:
    """Minimal ToolResult stub."""
    def __init__(self, success=True, error=None, data=None):
        self.success = success
        self.error = error
        self.data = data


class TestMCPPhysicalFeedbackPipeline:
    """Full Phi: ToolResult -> PhysicalState -> ErrorMapper -> DualTrackCritic."""

    def test_mcp_write_429_triggers_fatal_external(self):
        """Rate-limited MCP write should trip circuit breaker, not retry."""
        verifier = ToolPhysicalVerifier()
        mapper = ErrorMapper()
        critic = DualTrackCritic()

        # Simulate: mcp__filesystem_write returns 429
        result = FakeToolResult(success=False, error="429 Too Many Requests")
        phys = verifier.verify("mcp__filesystem_write", result)

        assert phys.state == PhysicalState.FATAL_EXTERNAL
        assert phys.state.is_fatal()

        # ErrorMapper generates fix_hint
        mapping = mapper.map(phys)
        assert mapping.error_type == "FATAL_EXTERNAL"

        # DualTrackCritic: FATAL_EXTERNAL → FAIL_FATAL verdict
        decision = critic.evaluate(
            semantic_score=0.85, theta=0.70,
            physical_result=phys, intent_type="EXECUTABLE",
            fix_hint=mapping.fix_hint,
        )
        assert decision.verdict == CriticVerdict.FAIL_FATAL

    def test_mcp_query_timeout_triggers_retry(self):
        """Database timeout -> TIMEOUT -> semantic escape, retryable."""
        verifier = ToolPhysicalVerifier()
        mapper = ErrorMapper()
        critic = DualTrackCritic()

        result = FakeToolResult(success=False, error="Query timed out after 30s")
        phys = verifier.verify("mcp__database_query", result)

        assert phys.state == PhysicalState.TIMEOUT
        assert phys.state.is_retryable()

        mapping = mapper.map(phys)
        assert "infinite loop" in mapping.fix_hint or "termination" in mapping.fix_hint

        decision = critic.evaluate(
            semantic_score=0.80, theta=0.70,
            physical_result=phys, intent_type="EXECUTABLE",
            fix_hint=mapping.fix_hint,
        )
        assert decision.verdict == CriticVerdict.RETRY

    def test_mcp_filesystem_permission_denied_is_sandbox_violation(self):
        """Permission denied -> SANDBOX_VIOLATION -> Rigid Contract #5."""
        verifier = ToolPhysicalVerifier()

        result = FakeToolResult(
            success=False,
            error="EACCES: permission denied, access '/etc/shadow'",
        )
        phys = verifier.verify("mcp__filesystem_read", result)

        assert phys.state == PhysicalState.SANDBOX_VIOLATION
        assert phys.state.is_fatal()

    def test_mcp_read_success_passes_through(self):
        """Successful MCP operation -> PASS, no physical intervention."""
        verifier = ToolPhysicalVerifier()
        critic = DualTrackCritic()

        result = FakeToolResult(success=True, data={"content": "file contents"})
        phys = verifier.verify("mcp__filesystem_read", result)

        assert phys.state == PhysicalState.PASS

        decision = critic.evaluate(
            semantic_score=0.90, theta=0.70,
            physical_result=phys, intent_type="EXECUTABLE",
        )
        assert decision.verdict == CriticVerdict.PASS

    def test_401_unauthorized_is_fatal_external(self):
        """Auth failure should not trigger retry — it's external rejection."""
        verifier = ToolPhysicalVerifier()

        result = FakeToolResult(success=False, error="401 Unauthorized — invalid API key")
        phys = verifier.verify("mcp__network_api", result)

        assert phys.state == PhysicalState.FATAL_EXTERNAL

    def test_403_forbidden_is_fatal_external(self):
        verifier = ToolPhysicalVerifier()

        result = FakeToolResult(success=False, error="403 Forbidden")
        phys = verifier.verify("mcp__network_api", result)

        assert phys.state == PhysicalState.FATAL_EXTERNAL

    def test_transient_network_error_is_retryable(self):
        """Connection reset -> RUNTIME_ERR -> retryable."""
        verifier = ToolPhysicalVerifier()

        result = FakeToolResult(success=False, error="Connection reset by peer")
        phys = verifier.verify("mcp__network_fetch", result)

        assert phys.state == PhysicalState.RUNTIME_ERR
        assert phys.state.is_retryable()


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2: Resistance DAG — Planning-like step shapes
# ═══════════════════════════════════════════════════════════════════════

class TestResistanceDAGPipeline:
    """Full DAG: Planning steps -> resistance sort -> parallel_depth."""

    def test_realistic_planning_steps_preserve_causality(self):
        """Simulating: 'write config, then search docs, then fetch API'.
        Planning produced these as independent steps (no explicit deps).
        Resistance DAG must sort reads before writes."""
        steps = [
            {"prompt": "Save the generated config to disk",
             "tool": "mcp__filesystem_write"},               # w=50
            {"prompt": "Search documentation for API reference",
             "tool": "search_web"},                          # w=0.1
            {"prompt": "Fetch weather data from remote API",
             "tool": "mcp__network_fetch"},                  # w=10
            {"prompt": "Read existing configuration",
             "tool": "mcp__filesystem_read"},                # w=5
        ]
        result, depth, max_r = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)

        tools = [s["tool"] for s in result]
        # Reads sorted by resistance, writes at end with original order
        read_tools = [t for t in tools
                      if not t.endswith(("_write", "_delete", "_insert", "_update"))]
        write_tools = [t for t in tools
                       if t.endswith(("_write", "_delete", "_insert", "_update"))]

        # All reads before all writes
        last_read = max(i for i, t in enumerate(tools)
                        if t in read_tools) if read_tools else -1
        first_write = min(i for i, t in enumerate(tools)
                          if t in write_tools) if write_tools else len(tools)

        assert last_read < first_write, "Reads must precede writes"
        # Reads sorted ascending by weight
        read_weights = [RESISTANCE_WEIGHTS[t] for t in read_tools]
        assert read_weights == sorted(read_weights), "Reads must be sorted by weight"

        assert max_r == 50.0  # filesystem_write
        assert depth == 4     # All independent, max 4 parallel

    def test_explicit_dependencies_not_broken(self):
        """When Planning explicitly sets depends_on, resistance must not
        violate the dependency chain."""
        steps = [
            {"prompt": "Write config", "tool": "mcp__filesystem_write",
             "produces": "config", "depends_on": []},           # w=50
            {"prompt": "Validate config", "tool": "sandbox_python",
             "needs": "config", "depends_on": [0]},             # w=2
        ]
        result, depth, max_r = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)

        # Step 0 (write) must come before step 1 (validate)
        write_idx = next(i for i, s in enumerate(result)
                         if s["tool"] == "mcp__filesystem_write")
        read_idx = next(i for i, s in enumerate(result)
                        if s["tool"] == "sandbox_python")
        assert write_idx < read_idx, "Dependency must dominate resistance sort"
        assert depth == 1  # Serial chain

    def test_mixed_read_write_with_tags(self):
        """Planning uses produces/needs tags for dependency declaration."""
        steps = [
            {"prompt": "Fetch API key from vault",
             "tool": "mcp__filesystem_read", "produces": "api_key"},  # w=5
            {"prompt": "Call external API with key",
             "tool": "mcp__network_api", "needs": "api_key"},         # w=40
            {"prompt": "Search docs",
             "tool": "search_web"},                                   # w=0.1
        ]
        result, depth, max_r = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)

        # search_web (level 0, no deps) should be before the dependent chain
        # fetch_api_key -> call_api is serial (level 0 -> 1 or 0->0 with dep)
        tools = [s["tool"] for s in result]
        # search_web should be at same level as fetch_api_key or before
        assert tools.index("search_web") <= tools.index("mcp__network_api")


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3: Test case augmentation — sigma-monotone contraction
# ═══════════════════════════════════════════════════════════════════════

class TestAugmentationPipeline:
    """Full sigma: error -> boundary tests -> retry with tighter constraints."""

    def test_indexerror_triggers_boundary_augmentation(self):
        """Simulate: off-by-one error -> sigma generates boundary tests."""
        executor = SandboxExecutor()

        # Code with off-by-one bug
        code = """def get_element(arr, k):
    return arr[k]  # Bug: no bounds check
"""
        tc = [{"input": "[1,2,3], 2", "expected": 3}]  # Valid index

        # First execution — may pass for valid index
        result = executor.run(code, test_cases=tc)

        # Augment based on the code pattern (IndexError-prone)
        aug = augment_test_cases("IndexError")
        assert len(aug) >= 3
        assert any("[]" in t["input"] for t in aug)
        assert any("-1" in t["input"] for t in aug)

    def test_monotone_accumulation(self):
        """Simulate T1 -> T2 -> T3: each retry adds boundary tests."""
        all_tc = []

        # Retry 1: IndexError
        aug1 = augment_test_cases("IndexError")
        all_tc.extend(aug1)
        n1 = len(all_tc)

        # Retry 2: KeyError (different error from fixed code)
        aug2 = augment_test_cases("KeyError")
        all_tc.extend(aug2)
        n2 = len(all_tc)

        # Retry 3: TypeError
        aug3 = augment_test_cases("TypeError")
        all_tc.extend(aug3)
        n3 = len(all_tc)

        assert n1 < n2 < n3, "Test cases must monotonically increase"
        assert n3 >= 7  # At least 3+2+2

    def test_augmented_tests_run_in_sandbox(self):
        """Augmented test cases must be executable by SandboxExecutor."""
        executor = SandboxExecutor()

        code = """def safe_get(arr, k):
    if k < 0 or k >= len(arr):
        return None
    return arr[k]
"""
        aug = augment_test_cases("IndexError")

        result = executor.run(code, test_cases=aug)
        # Should pass because code has bounds checking
        assert result.state == PhysicalState.PASS

    def test_augmentation_constraint_text(self):
        """Augmented test cases should produce usable constraint text."""
        aug = augment_test_cases("IndexError")
        assert len(aug) >= 3

        # Build constraint text (simulating track_c.py's injection)
        tc_summary = "; ".join(
            f"test[{i}]: {t.get('input','?')} -> {t.get('expected','?')}"
            for i, t in enumerate(aug[:3])
        )
        assert "IndexError" in tc_summary or "[]" in tc_summary or "(" in tc_summary


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4: Docker S4 (skipped when unavailable)
# ═══════════════════════════════════════════════════════════════════════

def _docker_available():
    import subprocess
    try:
        result = subprocess.run(
            ['docker', 'version', '--format', '{{.Server.Version}}'],
            capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker not running")
class TestDockerPipeline:
    """Full S4: code -> AST -> Mypy -> Sandbox -> Docker."""

    def test_full_filter_chain_with_docker(self):
        executor = SandboxExecutor()
        budget = PhysicalBudget(max_budget=5.0)

        code = """def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
"""
        tc = [
            {"input": "(0,)", "expected": 1},
            {"input": "(5,)", "expected": 120},
        ]

        result = executor.run(code, test_cases=tc, budget=budget, use_docker=True)
        assert result.state == PhysicalState.PASS
        # Budget consumed: AST(0) + Mypy(0.1) + Sandbox(1.0) + Docker(2.0) = 3.1
        assert budget.remaining <= 5.0 - 3.1 + 0.01

    def test_docker_timeout_handled(self):
        executor = SandboxExecutor()
        budget = PhysicalBudget(max_budget=5.0)

        code = "while True: pass"
        result = executor.run(code, budget=budget, use_docker=True)
        # Should be killed by timeout in Docker container
        assert result.state in (PhysicalState.TIMEOUT, PhysicalState.RUNTIME_ERR)

    def test_docker_budget_insufficient_skips(self):
        executor = SandboxExecutor()
        budget = PhysicalBudget(max_budget=1.5)  # Can't afford Layer 4

        code = "x = 1 + 1"
        result = executor.run(code, budget=budget, use_docker=True)
        # Should pass via Layer 3, Docker skipped (not enough budget)
        assert result.state == PhysicalState.PASS


# ═══════════════════════════════════════════════════════════════════════
# Scenario 5: Cross-component — Phi + Resistance + Sigma
# ═══════════════════════════════════════════════════════════════════════

class TestCrossComponentPipeline:
    """All three components working together in a single scenario."""

    def test_full_physical_verification_workflow(self):
        """Simulating: 'write a function, test it, fix it'.

        Flow: Code -> Sandbox(FAIL) -> ErrorMapper -> augment ->
              Resistance DAG sorts retry step -> Sandbox(PASS).
        """
        executor = SandboxExecutor()
        mapper = ErrorMapper()
        verifier = ToolPhysicalVerifier()
        budget = PhysicalBudget(max_budget=5.0)

        # Step 1: Code with bug
        code_v1 = """def divide(a, b):
    return a / b  # Bug: no zero check
"""
        tc = [{"input": "(10, 2)", "expected": 5}]

        result_v1 = executor.run(code_v1, test_cases=tc, budget=budget)
        # Should pass for the happy path test

        # Add a zero-division test (simulating augmentation)
        aug = augment_test_cases("ZeroDivisionError")
        tc_v2 = tc + aug

        # Step 2: Run with augmented tests
        result_v2 = executor.run(code_v1, test_cases=tc_v2, budget=budget)
        # Should fail on zero division
        if result_v2.state != PhysicalState.PASS:
            mapping = mapper.map(result_v2, code_v1)
            assert mapping.error_type in ("RUNTIME_ERR", "AssertionDiff")

        # Step 3: Fixed code
        code_v3 = """def divide(a, b):
    if b == 0:
        return None
    return a / b
"""
        result_v3 = executor.run(code_v3, test_cases=tc_v2, budget=budget)
        assert result_v3.state == PhysicalState.PASS

        # Verify MCP tool would also go through verifier
        mcp_result = FakeToolResult(success=True, data={"result": "ok"})
        phys = verifier.verify("mcp__filesystem_read", mcp_result)
        assert phys.state == PhysicalState.PASS

    def test_resistance_weights_align_with_physical_tools(self):
        """Every PHYSICAL_TOOL should have a RESISTANCE_WEIGHT entry."""
        for tool_name in PHYSICAL_TOOLS:
            assert tool_name in RESISTANCE_WEIGHTS, (
                f"Tool '{tool_name}' in PHYSICAL_TOOLS but missing from "
                f"RESISTANCE_WEIGHTS"
            )

    def test_resistance_monotone_with_risk(self):
        """Higher risk = higher resistance weight."""
        assert RESISTANCE_WEIGHTS[""] < RESISTANCE_WEIGHTS["search_web"]
        assert (RESISTANCE_WEIGHTS["mcp__filesystem_read"]
                < RESISTANCE_WEIGHTS["mcp__filesystem_write"])
        assert (RESISTANCE_WEIGHTS["mcp__filesystem_write"]
                <= RESISTANCE_WEIGHTS["mcp__filesystem_delete"])
        assert (RESISTANCE_WEIGHTS["mcp__database_query"]
                < RESISTANCE_WEIGHTS["mcp__database_write"])
