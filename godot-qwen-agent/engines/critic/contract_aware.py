"""Contract-Aware Critic Engine — Phase 23d.

Wraps any CriticEngine with contract-adaptive protection.
Same decorator pattern as ContractAwarePlanningEngine and
ContractAwareOrchestrationEngine.
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
from engines.critic.interface import CriticContext, CriticEngine


class ContractAwareCriticEngine:
    """CriticEngine wrapper with contract-adaptive immune system.

    Drop-in replacement for any CriticEngine — same evaluate()
    signature. The underlying critic never knows it's being watched.
    """

    def __init__(
        self,
        critic: CriticEngine,
        kernel: KernelService,
    ) -> None:
        self._critic = critic
        self._kernel = kernel

    async def evaluate(
        self,
        context: CriticContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator:
        """Execute evaluate() with contract-aware protection.

        On success: emits assembly_complete event.
        On failure: emits document_failed event → evaluates health →
        decides repair → if actions available, executes them → re-raises.
        """
        agent_id = context.agent_identity.id
        correlation_id = f"critic_{agent_id}_{int(time.time())}"
        start_time = time.time()

        try:
            async for item in self._critic.evaluate(
                context, deadline, pace_config,
            ):
                yield item

        except Exception as exc:
            self._kernel.event_sink(CompositionEvent(
                event_type="document_failed",
                correlation_id=correlation_id,
                timestamp=time.time(),
                context={
                    "engine": "critic",
                    "agent_id": agent_id,
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
                "engine": "critic",
                "agent_id": agent_id,
                "duration_ms": int(elapsed * 1000),
                "status": "success",
            },
        ))

    @property
    def critic(self) -> CriticEngine:
        return self._critic

    @property
    def kernel(self) -> KernelService:
        return self._kernel
