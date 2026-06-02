"""KernelService Protocol — Phase 23a.

The standard interface through which upper layers (engines, agents, business
logic) consume the contract-adaptive kernel. This is the "standard plug"
described in the 同心圆架构 — Application Layer never imports core/adapters/
directly; it only depends on this Protocol.

Design invariant:
  - Zero implementation — pure Protocol
  - Exposes only what upper layers NEED, not what the kernel HAS
  - Each method is an "atomic capability" of the contract-adaptive OS
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol

from .composition import (
    CompositionBlueprint,
    ContractHealthReport,
    ContractViolation,
)


class KernelService(Protocol):
    """The contract-adaptive kernel as seen by Application Layer.

    Upper layers (PlanningEngine, OrchestrationEngine, CriticEngine)
    consume this Protocol — never import from core/adapters/ directly.
    This keeps the kernel replaceable and the application layer testable.

    Usage:
        # Application Layer
        class ContractAwarePlanningEngine:
            def __init__(self, kernel: KernelService, planner: PlanningEngine):
                self._kernel = kernel
                self._planner = planner

            async def plan(self, context: PlanningContext, ...):
                try:
                    async for item in self._planner.plan(context, ...):
                        yield item
                except Exception as e:
                    self._kernel.event_sink(planning_failed_event)
                    report = self._kernel.evaluate_health()
                    if report.severity in ("degraded", "critical"):
                        actions = self._kernel.decide_repair(report)
                        # ...
    """

    # ── Event Sink (Phase 19.5) ──────────────────────────────────

    @property
    def event_sink(self) -> Callable[[Any], None]:
        """The kernel's event sink — drop-in for any event_sink parameter.

        Upper layers emit CompositionEvent objects into this sink.
        The kernel's HealthEvaluator and SelfRepairEngine consume them.
        """
        ...

    # ── Health Evaluation (Phase 20) ──────────────────────────────

    def evaluate_health(
        self, previous: ContractHealthReport | None = None
    ) -> ContractHealthReport:
        """Evaluate the current contract compliance state.

        Args:
            previous: Optional previous report for trend calculation.

        Returns:
            ContractHealthReport with severity, compliance_rate, trend, etc.
        """
        ...

    # ── Self-Repair (Phase 22b) ──────────────────────────────────

    def decide_repair(
        self, report: ContractHealthReport
    ) -> List[Any]:
        """Decide repair actions based on a health report.

        Args:
            report: Health assessment from evaluate_health()

        Returns:
            List of RepairAction decisions (empty if healthy).
        """
        ...

    def execute_repairs(self, actions: List[Any]) -> List[Dict[str, Any]]:
        """Execute a list of repair actions.

        Args:
            actions: RepairAction list from decide_repair()

        Returns:
            List of result dicts describing what happened.
        """
        ...

    # ── Blueprint (Phase 19) ─────────────────────────────────────

    @property
    def blueprint(self) -> CompositionBlueprint:
        """The currently active contract blueprint."""
        ...

    @property
    def blueprint_fingerprint(self) -> str:
        """Deterministic fingerprint of the current blueprint."""
        ...

    # ── Audit (Phase 19) ─────────────────────────────────────────

    @property
    def audit_manifest(self) -> Dict[str, Any]:
        """Runtime identity snapshot for audit trails."""
        ...
