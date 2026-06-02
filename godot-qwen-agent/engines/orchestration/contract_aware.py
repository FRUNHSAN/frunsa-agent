"""Contract-Aware Orchestration Engine — Phase 23c.

Wraps any OrchestrationEngine with contract-adaptive protection.
Same decorator pattern as ContractAwarePlanningEngine.
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
from engines.orchestration.interface import OrchestrationContext, OrchestrationEngine


class ContractAwareOrchestrationEngine:
    """OrchestrationEngine wrapper with contract-adaptive immune system.

    Drop-in replacement for any OrchestrationEngine — same orchestrate()
    signature. The underlying orchestrator never knows it's being watched.
    """

    def __init__(
        self,
        orchestrator: OrchestrationEngine,
        kernel: KernelService,
    ) -> None:
        self._orchestrator = orchestrator
        self._kernel = kernel

    async def orchestrate(
        self,
        context: OrchestrationContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator:
        """Execute orchestrate() with contract-aware protection.

        On success: emits assembly_complete event.
        On failure: emits document_failed event → evaluates health →
        decides repair → if actions available, executes them → re-raises.
        """
        agent_id = context.agent_identity.id
        correlation_id = f"orchestration_{agent_id}_{int(time.time())}"
        branch_count = len(context.branches)
        start_time = time.time()

        try:
            async for item in self._orchestrator.orchestrate(
                context, deadline, pace_config,
            ):
                yield item

        except Exception as exc:
            self._kernel.event_sink(CompositionEvent(
                event_type="document_failed",
                correlation_id=correlation_id,
                timestamp=time.time(),
                context={
                    "engine": "orchestration",
                    "agent_id": agent_id,
                    "branches": branch_count,
                    "merge_strategy": context.merge_strategy,
                    "error_type": "execution",
                    "error_message": f"{type(exc).__name__}: {exc}",
                    "contract_violation": ContractViolation.OUTPUT_CONTRACT_VIOLATION,
                },
            ))

            report = self._kernel.evaluate_health()
            actions = self._kernel.decide_repair(report)
            if actions:
                self._kernel.execute_repairs(actions)
            raise

        elapsed = time.time() - start_time
        self._kernel.event_sink(CompositionEvent(
            event_type="assembly_complete",
            correlation_id=correlation_id,
            timestamp=time.time(),
            context={
                "engine": "orchestration",
                "agent_id": agent_id,
                "branches": branch_count,
                "duration_ms": int(elapsed * 1000),
                "status": "success",
            },
        ))

    @property
    def orchestrator(self) -> OrchestrationEngine:
        return self._orchestrator

    @property
    def kernel(self) -> KernelService:
        return self._kernel
