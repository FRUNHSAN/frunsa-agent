"""Critic engine contract: data model and engine protocol.

Phase 18 defines the SHAPE of a Critic engine — zero implementation.
CriticContext bundles plan output with metadata extension slot.

Protocol signature uniformity: async def evaluate(context, deadline, pace_config)
-> AsyncIterator[StreamItem] — same shape as PlanningEngine.plan().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping, Protocol

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.critic.identity import CriticAgent


@dataclass(frozen=True)
class CriticContext:
    """Input context for the Critic engine.

    Principle 3: metadata is an opaque extension slot — not a trace key,
    not guardrail-enforced. Engine developers instrument it with debug
    info without touching the core contract surface.

    Fields:
        plan_output: The planning engine's output to evaluate.
        agent_identity: Critic agent identity.
        metadata: Opaque extension slot (Principle 3).
    """

    plan_output: str
    agent_identity: CriticAgent = field(
        default_factory=lambda: CriticAgent(
            id="critic-v1",
            role="critic",
            version="1.0.0",
            capabilities=("result_evaluation", "quality_scoring"),
        )
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

class CriticEngine(Protocol):
    """Protocol that every Critic engine must implement.

    Produces an async stream of StreamItems, each carrying:
      - critic.score (float)
      - critic.verdict (str)
      - agent.identity (dict)

    Args:
        context: CriticContext with plan_output and agent identity.
        deadline: Operation-level deadline in seconds (duration).
        pace_config: QoS parameters.

    Yields:
        StreamItem with trace_context containing:
        {
            "critic.score": float,
            "critic.verdict": str,
            "agent.identity": dict,
        }
    """

    async def evaluate(
        self,
        context: CriticContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        ...
