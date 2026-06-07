"""KernelService Protocol — the kernel's only public interface to upper layers.

Phase 23 (Invariant #32): Application layers (engines/, future agents/)
MUST consume the kernel through this Protocol, never through direct imports
of concrete adapters or pipeline classes.

This file fills the architectural gap identified in V4.3 audit —
the Protocol was referenced by 3 contract_aware.py files but never defined.

Note: KernelServiceImpl is a Phase 25+ concern. Today we define the
interface shape so contract_aware wrappers have a valid import target.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable

from core.contracts.composition import CompositionEvent


@runtime_checkable
class KernelService(Protocol):
    """Shared kernel capabilities exposed to application (engine/agent) layers.

    All engine code talks to this Protocol — never to concrete adapters.
    This keeps engines testable (mock the Protocol) and the kernel replaceable.
    """

    @property
    def event_sink(self) -> Any:  # Callable[[CompositionEvent], None] in practice
        """Emit an observability event into the kernel's event bus.

        Shape: Callable[[CompositionEvent], None].
        Engine wrappers use this to record contract compliance events.
        """
        ...

    def evaluate_health(self) -> Dict[str, Any]:
        """Run the HealthEvaluator against the current contract state.

        Returns dict with keys: overall_status, compliance_rate, violations, ...
        Contract-aware engine wrappers call this after each plan/orch/critic cycle.
        """
        ...

    def decide_repair(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Given a health report, decide what repairs (if any) to execute.

        Returns list of action dicts, each with 'action' and 'target' keys.
        """
        ...

    def execute_repairs(self, actions: List[Dict[str, Any]]) -> None:
        """Execute repair actions decided by decide_repair().

        Idempotent — executing the same repair twice has no additional effect.
        """
        ...
