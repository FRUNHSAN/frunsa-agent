"""Planning engine contract: data model and engine protocol.

Phase 10 defines the SHAPE of a Planning engine — zero implementation.
PlanningStep is the engine's internal model; the stub converts it to
StreamItem for transport through AsyncDataStreamAdapter.

trace_context key namespace convention (established here):
  All keys use "planning." prefix with dot-separator. Other engines
  declare their own prefix (e.g. "rag."). The trace_context_namespace
  guardrail enforces this at WARNING level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Protocol

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig


@dataclass(frozen=True)
class PlanningStep:
    """Minimal semantic unit produced by a Planning engine.

    This is the engine's INTERNAL data model — not a wire format.
    The stub/adapter converts PlanningStep → StreamItem for transport.

    Fields:
        step_index: Zero-based position in the reasoning chain.
        reasoning_depth: Nesting level (0 = top-level goal, 1+ = sub-task).
        parent_step_id: The step_index this step decomposes from (None for root).
        content: The reasoning text for this step.
        is_terminal: True for the final conclusion step in a plan.
    """

    step_index: int
    reasoning_depth: int
    parent_step_id: Optional[str]
    content: str
    is_terminal: bool = False


class PlanningEngine(Protocol):
    """Protocol that every Planning engine must implement.

    Produces an async stream of StreamItems, each carrying planning.*
    trace_context keys. Consumers (adapters, pipelines) treat the stream
    as opaque — they pass through StreamItems without inspecting trace_context.

    Args:
        goal: The planning objective (natural language).
        deadline: Operation-level deadline in seconds (duration, not absolute
            timestamp). The engine is responsible for checking elapsed time
            against this value and raising asyncio.TimeoutError if exceeded.
            Maps to TransportBackend.send_with_deadline when going through
            AsyncDataStreamAdapter.
        pace_config: QoS parameters. Planning engines should set
            adaptive_strategy="jitter" to declare burst-tolerance needs.
            The PaceShapingWrapper reads this and routes to the appropriate
            pacing strategy.

    Yields:
        StreamItem with trace_context containing planning.* keys:
        {
            "planning.step_index": int,
            "planning.reasoning_depth": int,
            "planning.parent_step_id": Optional[str],
            "planning.cumulative_tokens": int,
        }
    """

    async def plan(
        self,
        goal: str,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        ...
