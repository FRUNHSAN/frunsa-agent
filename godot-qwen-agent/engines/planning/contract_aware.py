"""Contract-Aware Planning Engine — Phase 23b.

Wraps any PlanningEngine with contract-adaptive protection.
The underlying planner keeps doing its job — generating Plans.
The wrapper adds: event recording, health evaluation, and self-repair.

This is the "decorator pattern" for contract awareness.
Zero changes to the underlying engine. Zero changes to the kernel.
"""

from __future__ import annotations

import time
from typing import AsyncIterator

from core.contracts.composition import (
    CompositionEvent,
    ContractViolation,
)
from core.contracts.kernel_service import KernelService
from core.contracts.streaming_protocol import PaceConfig
from engines.planning.interface import PlanningContext, PlanningEngine


class ContractAwarePlanningEngine:
    """PlanningEngine wrapper with contract-adaptive immune system.

    Drop-in replacement for any PlanningEngine — implements the same
    plan() signature. The underlying planner never knows it's being watched.

    Usage:
        kernel = KernelServiceImpl(sink, evaluator, repair, blueprint)
        raw_planner = LLMPlanningEngine(client)
        planner = ContractAwarePlanningEngine(raw_planner, kernel)

        async for item in planner.plan(context, deadline, pace_config):
            # items are identical to raw_planner output
            ...
    """

    def __init__(
        self,
        planner: PlanningEngine,
        kernel: KernelService,
    ) -> None:
        self._planner = planner
        self._kernel = kernel

    async def plan(
        self,
        context: PlanningContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator:
        """Execute plan() with contract-aware protection.

        On success: emits planning_completed event.
        On failure: emits planning_failed event → evaluates health →
        decides repair → if critical, escalates.
        """
        correlation_id = f"planning_{context.agent_identity.id}_{int(time.time())}"
        start_time = time.time()

        try:
            async for item in self._planner.plan(context, deadline, pace_config):
                yield item

        except Exception as exc:
            # Record the failure in the contract system
            self._kernel.event_sink(CompositionEvent(
                event_type="document_failed",
                correlation_id=correlation_id,
                timestamp=time.time(),
                context={
                    "engine": "planning",
                    "goal": context.goal[:200],
                    "agent_id": context.agent_identity.id,
                    "error_type": "execution",
                    "error_message": f"{type(exc).__name__}: {exc}",
                    "contract_violation": ContractViolation.OUTPUT_CONTRACT_VIOLATION,
                },
            ))

            # Evaluate current health
            report = self._kernel.evaluate_health()

            # Decide repair actions
            actions = self._kernel.decide_repair(report)

            if actions:
                self._kernel.execute_repairs(actions)

            # If the planner failed, the caller should handle the exception
            raise

        # Success path
        elapsed = time.time() - start_time
        self._kernel.event_sink(CompositionEvent(
            event_type="assembly_complete",
            correlation_id=correlation_id,
            timestamp=time.time(),
            context={
                "engine": "planning",
                "goal": context.goal[:200],
                "agent_id": context.agent_identity.id,
                "duration_ms": int(elapsed * 1000),
                "status": "success",
            },
        ))

    # ── Delegate read-only properties ─────────────────────────────

    @property
    def planner(self) -> PlanningEngine:
        return self._planner

    @property
    def kernel(self) -> KernelService:
        return self._kernel
