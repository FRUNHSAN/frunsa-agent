"""V7.3 ToolPhysicalVerifier — universal physical feedback functor Phi: Tool -> Phys.

Maps ToolResult (from any tool execution, including MCP) to ExecutionResult,
making ALL side-effect-producing operations consumable by ErrorMapper + DualTrackCritic.

Mathematical: Phi is the universal functor from Tool to Phys.
  - Object mapping:   Phi(t) = set of physical states tool t can produce
  - Morphism mapping:  Phi(f: t1->t2) = state-set inclusion or restriction
  - Universal property: any physical verifier V factors through Phi

Red-Team #2 (External Circuit Breaker):
  Q decomposes into connected components. Retry can only walk within C_internal.
  Crossing into C_external (rate-limit, auth failure, quota) -> immediate trip.
  Prevents infinite retry flooding of paid APIs and IP bans.
"""

from __future__ import annotations

from core.execution.sandbox import ExecutionResult, PhysicalState


# ── V7.3: Tools with physical side effects ──────────────────────────────

PHYSICAL_TOOLS: set[str] = {
    "sandbox_python",
    "mcp__filesystem_read",
    "mcp__filesystem_write",
    "mcp__filesystem_delete",
    "mcp__database_query",
    "mcp__database_write",
    "mcp__network_fetch",
    "mcp__network_api",
}


def is_physical_tool(tool_name: str) -> bool:
    """Check if a tool has physical side effects -> needs Phi verification."""
    if not tool_name:
        return False
    return tool_name in PHYSICAL_TOOLS or tool_name.startswith("mcp__")


class ToolPhysicalVerifier:
    """Phi: Tool -> Phys — universal physical feedback functor.

    Maps ToolResult (from any tool execution) to ExecutionResult,
    making MCP tool results consumable by ErrorMapper + DualTrackCritic.

    Usage:
        verifier = ToolPhysicalVerifier()
        phys_result = verifier.verify("mcp__filesystem_write", tool_result)
        if phys_result.state != PhysicalState.PASS:
            mapping = ErrorMapper().map(phys_result)
            # Inject mapping.fix_hint into Planning retry
    """

    # ── Phi object mapping: ToolResult -> ExecutionResult ─────────────

    def verify(self, tool_name: str, result) -> ExecutionResult:
        """Phi(tool)(result) -> PhysicalState.

        Args:
            tool_name: The tool's registry key (e.g. 'mcp__filesystem_write').
            result:    ToolResult from the tool's execute() call.

        Returns:
            ExecutionResult with PhysicalState derived from ToolResult.
        """
        if result.success:
            return ExecutionResult(
                state=PhysicalState.PASS,
                output=str(result.data)[:500] if result.data else "",
            )

        error_msg = result.error or ""
        state = self._classify_error(tool_name, error_msg)
        return ExecutionResult(
            state=state,
            error_message=error_msg,
        )

    # ── Phi morphism mapping: error string -> PhysicalState ──────────

    def _classify_error(self, tool_name: str, error: str) -> PhysicalState:
        """Map tool error to physical state with external circuit breaker.

        Red-Team #2: Distinguishes internal errors (retryable) from
        external rejection (fatal). Q's connected components:
          C_internal = {PASS, RUNTIME_ERR, COMPILE_ERR, TIMEOUT}
          C_external = {FATAL_EXTERNAL, SANDBOX_VIOLATION}
        Retry = walk within C_internal. Cannot cross component boundaries.
        """
        error_lower = error.lower()

        # ── External rejection: immediate circuit breaker ──
        if any(k in error_lower for k in (
            "rate limit", "429", "too many", "quota exceeded",
            "unauthorized", "401", "forbidden", "403",
            "payment required", "402", "billing",
        )):
            return PhysicalState.FATAL_EXTERNAL

        # ── Permission denied: FAIL_FATAL (Rigid Contract #5) ──
        if any(k in error_lower for k in (
            "permission denied", "access denied", "eacces",
        )):
            return PhysicalState.SANDBOX_VIOLATION

        # ── Timeout: semantic escape (V7.2 Patch 2 isomorphism) ──
        if any(k in error_lower for k in ("timeout", "timed_out", "timed out")):
            return PhysicalState.TIMEOUT

        # ── Internal/transient error: retryable ──
        return PhysicalState.RUNTIME_ERR

    # ── Post-hoc text verification (no direct ToolResult) ────────────

    def verify_text(self, tool_name: str, result_text: str) -> PhysicalState | None:
        """Post-hoc scan of orchestrator output for tool failure indicators.

        Used when direct ToolResult is unavailable — the orchestrator only
        returns text, not structured tool results. Scans for error patterns
        and classifies them via the same _classify_error pipeline.

        Returns None if no error detected (tool likely succeeded).
        """
        import re

        # Common error patterns in LLM-generated tool output
        error_patterns = [
            r'(?:error|Error|ERROR)[:\s]+(.+?)(?:\n|$)',
            r'(?:failed|Failed|FAILED)[:\s]+(.+?)(?:\n|$)',
            r'(?:refused|denied|rejected|forbidden)[:\s]*(.+?)(?:\n|$)',
            r'(?:timeout|timed.out|timed_out)[:\s]*(.+?)(?:\n|$)',
            r'(?:rate.limit|429|too.many.requests)[:\s]*(.+?)(?:\n|$)',
            r'(?:unauthorized|401|403)[:\s]*(.+?)(?:\n|$)',
            r'\[TOOL_ERROR[:\]]\s*(.+?)(?:\n|\]|$)',
            r'\[PHYSICAL\s+(?:FAIL|FATAL)[:\]]\s*(.+?)(?:\n|\]|$)',
        ]

        for pattern in error_patterns:
            match = re.search(pattern, result_text, re.IGNORECASE)
            if match:
                error_msg = match.group(1).strip()[:200] if match.lastindex else match.group(0).strip()[:200]
                return self._classify_error(tool_name, error_msg)

        return None  # No error detected
