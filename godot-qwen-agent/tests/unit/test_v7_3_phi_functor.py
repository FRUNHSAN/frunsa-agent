"""V7.3 Phase 1 — Phi functor: ToolPhysicalVerifier tests.

Tests the universal physical feedback functor Phi: Tool -> Phys.
Covers: object mapping, morphism mapping, external circuit breaker,
connected component decomposition, PHYSICAL_TOOLS registry, and
post-hoc text verification.
"""

import pytest
from core.execution.sandbox import PhysicalState, ExecutionResult
from core.execution.tool_verifier import (
    ToolPhysicalVerifier,
    PHYSICAL_TOOLS,
    is_physical_tool,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def verifier():
    return ToolPhysicalVerifier()


class FakeToolResult:
    """Minimal ToolResult stub for testing without importing contracts."""
    def __init__(self, success=True, error=None, data=None):
        self.success = success
        self.error = error
        self.data = data


# ── PHYSICAL_TOOLS registry ────────────────────────────────────────────

class TestPhysicalToolsRegistry:
    def test_sandbox_python_is_physical(self):
        assert is_physical_tool("sandbox_python")

    def test_mcp_filesystem_is_physical(self):
        assert is_physical_tool("mcp__filesystem_write")
        assert is_physical_tool("mcp__filesystem_read")
        assert is_physical_tool("mcp__filesystem_delete")

    def test_mcp_database_is_physical(self):
        assert is_physical_tool("mcp__database_query")
        assert is_physical_tool("mcp__database_write")

    def test_mcp_network_is_physical(self):
        assert is_physical_tool("mcp__network_fetch")
        assert is_physical_tool("mcp__network_api")

    def test_empty_tool_is_not_physical(self):
        assert not is_physical_tool("")

    def test_unknown_mcp_prefix_is_physical(self):
        """Any mcp__* tool should be treated as physical."""
        assert is_physical_tool("mcp__unknown_tool")

    def test_plain_text_tool_is_not_physical(self):
        assert not is_physical_tool("search_web")
        assert not is_physical_tool("rag_search")

    def test_phys_tools_set_is_nonempty(self):
        assert len(PHYSICAL_TOOLS) >= 8


# ── Phi object mapping: ToolResult -> ExecutionResult ──────────────────

class TestObjectMapping:
    def test_success_maps_to_pass(self, verifier):
        result = FakeToolResult(success=True, data="file written")
        phys = verifier.verify("mcp__filesystem_write", result)
        assert phys.state == PhysicalState.PASS
        assert "file written" in phys.output

    def test_success_no_data_maps_to_pass(self, verifier):
        result = FakeToolResult(success=True)
        phys = verifier.verify("mcp__filesystem_read", result)
        assert phys.state == PhysicalState.PASS

    def test_failure_preserves_error_message(self, verifier):
        result = FakeToolResult(success=False, error="Connection timed out")
        phys = verifier.verify("mcp__network_api", result)
        assert phys.state == PhysicalState.TIMEOUT
        assert phys.error_message == "Connection timed out"


# ── Phi morphism mapping: error string -> PhysicalState ────────────────

class TestMorphismMapping:
    # ── External rejection -> FATAL_EXTERNAL (circuit breaker) ──

    @pytest.mark.parametrize("error_msg,expected", [
        ("HTTP 429 Too Many Requests", PhysicalState.FATAL_EXTERNAL),
        ("Rate limit exceeded for API key", PhysicalState.FATAL_EXTERNAL),
        ("Quota exceeded for this billing period", PhysicalState.FATAL_EXTERNAL),
        ("401 Unauthorized — invalid API key", PhysicalState.FATAL_EXTERNAL),
        ("403 Forbidden — insufficient permissions", PhysicalState.FATAL_EXTERNAL),
        ("Payment Required: 402 billing error", PhysicalState.FATAL_EXTERNAL),
        ("Too many connections from your IP", PhysicalState.FATAL_EXTERNAL),
    ])
    def test_external_rejection_is_fatal_external(self, verifier, error_msg, expected):
        assert verifier._classify_error("mcp__network_api", error_msg) == expected

    # ── Permission denied -> SANDBOX_VIOLATION (Rigid Contract #5) ──

    @pytest.mark.parametrize("error_msg", [
        "Permission denied: /etc/passwd",
        "Access denied to /root/.ssh",
        "EACCES: permission denied",
    ])
    def test_permission_denied_is_sandbox_violation(self, verifier, error_msg):
        assert verifier._classify_error("mcp__filesystem_read", error_msg) == PhysicalState.SANDBOX_VIOLATION

    # ── Timeout -> TIMEOUT (semantic escape) ──

    @pytest.mark.parametrize("error_msg", [
        "Connection timed out after 30s",
        "Request timed out",
        "operation timed_out",
    ])
    def test_timeout_is_timeout(self, verifier, error_msg):
        assert verifier._classify_error("mcp__database_query", error_msg) == PhysicalState.TIMEOUT

    # ── Transient errors -> RUNTIME_ERR (retryable) ──

    @pytest.mark.parametrize("error_msg", [
        "Connection reset by peer",
        "Temporary network error",
        "Internal server error",
        "Something went wrong",
        "Unknown failure",
    ])
    def test_transient_is_runtime_err(self, verifier, error_msg):
        assert verifier._classify_error("mcp__network_api", error_msg) == PhysicalState.RUNTIME_ERR


# ── Post-hoc text verification (verify_text) ───────────────────────────

class TestTextVerification:
    def test_detects_error_in_text(self, verifier):
        text = "Tool execution failed: Connection timed out after 10s"
        state = verifier.verify_text("mcp__network_api", text)
        assert state == PhysicalState.TIMEOUT

    def test_detects_rate_limit_in_text(self, verifier):
        text = "API returned 429 Too Many Requests. Please wait."
        state = verifier.verify_text("mcp__network_fetch", text)
        assert state == PhysicalState.FATAL_EXTERNAL

    def test_detects_permission_denied_in_text(self, verifier):
        text = "Error: Permission denied accessing /data/config.yaml"
        state = verifier.verify_text("mcp__filesystem_read", text)
        assert state == PhysicalState.SANDBOX_VIOLATION

    def test_clean_text_returns_none(self, verifier):
        text = "File written successfully. 42 lines processed."
        state = verifier.verify_text("mcp__filesystem_write", text)
        assert state is None

    def test_empty_text_returns_none(self, verifier):
        assert verifier.verify_text("mcp__network_api", "") is None

    def test_non_error_text_returns_none(self, verifier):
        text = "The request completed with status 200 OK"
        state = verifier.verify_text("mcp__network_fetch", text)
        assert state is None

    def test_detects_tool_error_tag(self, verifier):
        text = "[TOOL_ERROR] Connection refused to database host"
        state = verifier.verify_text("mcp__database_query", text)
        assert state is not None

    def test_detects_physical_fail_tag(self, verifier):
        text = "[PHYSICAL FAIL] Runtime error in sandbox execution"
        state = verifier.verify_text("sandbox_python", text)
        assert state == PhysicalState.RUNTIME_ERR


# ── Connected component decomposition ──────────────────────────────────

class TestConnectedComponents:
    def test_fatal_external_is_not_retryable(self):
        assert not PhysicalState.FATAL_EXTERNAL.is_retryable()

    def test_fatal_external_is_fatal(self):
        assert PhysicalState.FATAL_EXTERNAL.is_fatal()

    def test_sandbox_violation_is_fatal(self):
        assert PhysicalState.SANDBOX_VIOLATION.is_fatal()

    def test_runtime_err_is_retryable(self):
        assert PhysicalState.RUNTIME_ERR.is_retryable()

    def test_timeout_is_retryable(self):
        assert PhysicalState.TIMEOUT.is_retryable()

    def test_pass_is_neither_fatal_nor_retryable(self):
        assert not PhysicalState.PASS.is_fatal()
        assert not PhysicalState.PASS.is_retryable()

    def test_docker_unavailable_is_not_fatal(self):
        assert not PhysicalState.DOCKER_UNAVAILABLE.is_fatal()

    def test_docker_unavailable_is_not_retryable(self):
        """DOCKER_UNAVAILABLE -> fallback to S3, not a retry scenario."""
        assert not PhysicalState.DOCKER_UNAVAILABLE.is_retryable()

    # ── C_internal vs C_external separation ──

    def test_internal_errors_all_retryable(self):
        """All errors in C_internal should be retryable (except PASS)."""
        internal = {PhysicalState.COMPILE_ERR, PhysicalState.TYPE_MISMATCH,
                     PhysicalState.RUNTIME_ERR, PhysicalState.TIMEOUT}
        for state in internal:
            assert state.is_retryable(), f"{state} should be retryable"

    def test_external_errors_all_fatal(self):
        """All errors in C_external should be non-retryable and fatal."""
        external = {PhysicalState.SANDBOX_VIOLATION, PhysicalState.FATAL_EXTERNAL}
        for state in external:
            assert state.is_fatal(), f"{state} should be fatal"
            assert not state.is_retryable(), f"{state} should NOT be retryable"


# ── verify with real-like ToolResult ───────────────────────────────────

class TestVerifyIntegration:
    def test_mcp_write_success_flow(self, verifier):
        result = FakeToolResult(success=True, data={"bytes_written": 1024})
        phys = verifier.verify("mcp__filesystem_write", result)
        assert phys.state == PhysicalState.PASS

    def test_mcp_network_429_flow(self, verifier):
        result = FakeToolResult(success=False, error="429 Too Many Requests")
        phys = verifier.verify("mcp__network_api", result)
        assert phys.state == PhysicalState.FATAL_EXTERNAL
        assert phys.state.is_fatal()

    def test_mcp_database_timeout_flow(self, verifier):
        result = FakeToolResult(success=False, error="Query timed out")
        phys = verifier.verify("mcp__database_query", result)
        assert phys.state == PhysicalState.TIMEOUT
        assert phys.state.is_retryable()

    def test_mcp_filesystem_permission_flow(self, verifier):
        result = FakeToolResult(success=False, error="EACCES: permission denied")
        phys = verifier.verify("mcp__filesystem_delete", result)
        assert phys.state == PhysicalState.SANDBOX_VIOLATION
        assert phys.state.is_fatal()
