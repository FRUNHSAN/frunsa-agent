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

from typing import Any, AsyncIterator, Dict, List, Protocol, runtime_checkable

from core.contracts.composition import CompositionEvent


@runtime_checkable
class KernelService(Protocol):
    """Shared kernel capabilities exposed to application (engine/agent) layers.

    All engine code talks to this Protocol — never to concrete adapters.
    This keeps engines testable (mock the Protocol) and the kernel replaceable.

    V4.3 Phase 5: extended with engine-facing methods (generate, enforce, check_tool).
    Container duck-types this Protocol — no explicit inheritance needed.
    """

    # ── Phase 23a (V4.3 original) ──

    @property
    def event_sink(self) -> Any:
        """Emit an observability event into the kernel's event bus."""
        ...

    def evaluate_health(self) -> Dict[str, Any]:
        """Run the HealthEvaluator against the current contract state."""
        ...

    def decide_repair(self, report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Given a health report, decide what repairs to execute."""
        ...

    def execute_repairs(self, actions: List[Dict[str, Any]]) -> None:
        """Execute repair actions. Idempotent."""
        ...

    # ── Phase 5 (engine decoupling) ──

    async def generate(
        self, prompt: str, context: Any = None, **params: Any
    ) -> Any:  # Returns GenerationResult in practice
        """Async LLM generation. Replaces direct GenerationAdapter import.

        Engines call this instead of importing GenerationAdapter from adapters.
        Container delegates to cloud_llm.generate() wrapped in async executor.
        """
        ...

    def enforce(self, key: str) -> Any | None:
        """Hard-read a contract field from the DynamicBlueprint.

        Replaces engine direct import of DynamicBlueprint.
        Engines query: "what does the contract require of me?"
        """
        ...

    def check_tool(self, tool_name: str) -> Dict[str, Any]:
        """Run the ActionPipeline gate check on a tool.

        Returns {"allowed": bool, "reason": str, "requires_hitl": bool}.
        Replaces REPL manually calling action_pipeline.check().
        """
        ...
