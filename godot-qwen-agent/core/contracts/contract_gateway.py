"""ContractGateway — PLAN8: frozen public API for contract-bound agents.

This Protocol is the STABLE interface. Signatures here do NOT change
across minor versions. Implementation details (ActionPipeline, ToolContract,
EvolutionEngine) can be rewritten 10 times — as long as they satisfy this
protocol, external code never breaks.

Design principle (ADR-001):
  "Freeze the interface. Hide the implementation."
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ContractGateway(Protocol):
    """Frozen API for contract-bound agent integration.

    Stable across minor versions. Implementation hidden behind this interface.
    """

    def authorize_action(self, tool_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """Check if a tool can execute under current contract.

        Args:
            tool_name: Registered tool name.
            context: Arbitrary context dict (trust, user_id, session_id, etc.)

        Returns:
            {"allowed": bool, "reason": str, "requires_hitl": bool}
        """
        ...

    def report_result(self, tool_name: str, success: bool) -> None:
        """Report tool execution result for Backlash tracking.

        Args:
            tool_name: Registered tool name.
            success: True if tool executed successfully, False if failed.
        """
        ...

    def get_contract_state(self) -> dict[str, Any]:
        """Return current Blueprint state for external inspection.

        Returns:
            Snapshot of current contract fields (verbose, tone, autonomy, etc.)
        """
        ...

    def update_trust(self, delta: float) -> float:
        """Adjust trust level and return new value.

        Args:
            delta: Positive to increase trust, negative to decrease.

        Returns:
            New trust value in [0.0, 1.0].
        """
        ...
