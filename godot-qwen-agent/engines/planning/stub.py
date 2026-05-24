"""Minimal Planning engine stub for adapter contract validation.

Produces a hardcoded 3-step reasoning sequence. No real LLM calls.
Exists solely to verify that Phase 9/9.1 adapter extension points
(trace_context passthrough, adaptive_strategy routing, deadline timeout)
work correctly with a second engine type.

Phase 10: stub for contract testing only.
Phase 11+: replace with real LLM-backed planning.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.planning.interface import PlanningStep


class StubPlanningEngine:
    """Hardcoded 3-step planner. Implements PlanningEngine Protocol.

    Step 0: Analyze (depth 0, root)
    Step 1: Decompose (depth 1, child of step 0)
    Step 2: Conclude (depth 2, terminal)

    Each step checks elapsed time against the deadline. If exceeded,
    raises asyncio.TimeoutError — validating the send_with_deadline
    layered timeout contract.
    """

    async def plan(
        self,
        goal: str,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute hardcoded 3-step plan with deadline enforcement.

        Args:
            goal: The planning objective (used in step content text).
            deadline: Operation-level deadline in seconds (duration).
                The engine records start time and checks elapsed time
                before each step yield.
            pace_config: QoS parameters. adaptive_strategy should be "jitter".
        """
        start = time.perf_counter()

        steps = [
            PlanningStep(
                step_index=0,
                reasoning_depth=0,
                parent_step_id=None,
                content=f"Analyzing goal: {goal}",
                is_terminal=False,
            ),
            PlanningStep(
                step_index=1,
                reasoning_depth=1,
                parent_step_id="step-0",
                content="Decomposing into sub-tasks: (1) gather context, (2) evaluate options, (3) select approach",
                is_terminal=False,
            ),
            PlanningStep(
                step_index=2,
                reasoning_depth=2,
                parent_step_id="step-1",
                content="Final conclusion: approach selected based on constraints",
                is_terminal=True,
            ),
        ]

        for step in steps:
            # Check deadline before yielding each step.
            # perf_counter() used for microsecond resolution — monotonic()
            # has ~15ms granularity on Windows, insufficient for sub-ms deadlines.
            if time.perf_counter() - start > deadline:
                raise asyncio.TimeoutError(
                    f"Planning deadline exceeded: {time.perf_counter() - start:.3f}s > {deadline:.3f}s "
                    f"(step {step.step_index}, depth {step.reasoning_depth})"
                )

            yield StreamItem(
                delta=step.content,
                index=step.step_index,
                model="planning/stub",
                is_terminal=step.is_terminal,
                finish_reason="stop" if step.is_terminal else None,
                trace_context={
                    "planning.step_index": step.step_index,
                    "planning.reasoning_depth": step.reasoning_depth,
                    "planning.parent_step_id": step.parent_step_id,
                    "planning.cumulative_tokens": len(step.content),
                },
            )
