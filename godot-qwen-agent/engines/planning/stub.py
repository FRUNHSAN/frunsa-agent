"""Minimal Planning engine stub for adapter contract validation.

Phase 10: Hardcoded 3-step reasoning sequence.
Phase 15: Enhanced to 5-step scenario with parallel branch dispatch via
    StubOrchestrationEngine — the first cross-engine consumer pattern.
    Every StreamItem carries agent.identity + planning keys.
    Orchestration items are augmented (not replaced) with planning/agent context.

Phase 15 is a REVERSE STRESS TEST: it validates (or falsifies) the Phase 14
orchestration contract by consuming orchestration services from a real planning
scenario with parallel branches.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext, PlanningStep
from engines.orchestration.stub import StubOrchestrationEngine


class StubPlanningEngine:
    """Enhanced 5-step planner with parallel branch dispatch.

    Implements PlanningEngine Protocol. Produces an 8-item stream:
      Step 0 (serial):    Analyze goal, emit agent identity
      Step 1 (serial):    Decompose into sub-tasks
      Steps 2-3 (parallel via orchestration):
          Branch A (fast_path):    3 items
          Branch B (full_rerank):  2 items
          Merged into 5 items with sequential merge_ordinal
      Step 4 (serial, terminal): Synthesize merged results

    Each StreamItem carries:
      - All 4 planning.* keys (produced by planning engine)
      - agent.identity dict (produced by planning engine)
      - Orchestration passthrough items ALSO carry all 6 orchestration.* keys
        + component keys (retrieval.chunk_id, retrieval.latency_ms)

    Deadline enforcement: checks elapsed time before each step yield.
    Raises asyncio.TimeoutError if deadline exceeded.
    """

    identity = AgentIdentity(
        id="planner-v1",
        role="planning",
        version="1.0.0",
        capabilities=("task_decomposition", "parallel_planning"),
    )

    async def plan(
        self,
        context: PlanningContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute 5-step plan with parallel branch dispatch via orchestration.

        Args:
            context: PlanningContext with goal, agent identity, sub-tasks.
            deadline: Operation-level deadline in seconds (duration).
            pace_config: QoS parameters.
        """
        start = time.perf_counter()
        identity_value = context.agent_identity.to_trace_value()
        cumulative_tokens = 0

        # ── Step 0: Analyze goal (serial, depth 0, root) ──────────
        step0 = PlanningStep(
            step_index=0,
            reasoning_depth=0,
            parent_step_id=None,
            content=f"Analyzing goal: {context.goal}",
            is_terminal=False,
        )
        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded at step 0: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )
        cumulative_tokens += len(step0.content)
        yield StreamItem(
            delta=step0.content,
            index=0,
            model="planning/stub",
            is_terminal=False,
            finish_reason=None,
            trace_context={
                "planning.step_index": step0.step_index,
                "planning.reasoning_depth": step0.reasoning_depth,
                "planning.parent_step_id": step0.parent_step_id,
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            },
        )

        # ── Step 1: Decompose into sub-tasks (serial, depth 1) ───
        sub_tasks = context.sub_tasks or (
            "fast_path: keyword-based retrieval",
            "full_rerank: semantic reranking",
        )
        step1 = PlanningStep(
            step_index=1,
            reasoning_depth=1,
            parent_step_id="step-0",
            content=f"Decomposing into {len(sub_tasks)} sub-tasks: "
                    f"{'; '.join(sub_tasks)}",
            is_terminal=False,
        )
        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded at step 1: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )
        cumulative_tokens += len(step1.content)
        yield StreamItem(
            delta=step1.content,
            index=1,
            model="planning/stub",
            is_terminal=False,
            finish_reason=None,
            trace_context={
                "planning.step_index": step1.step_index,
                "planning.reasoning_depth": step1.reasoning_depth,
                "planning.parent_step_id": step1.parent_step_id,
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            },
        )

        # ── Steps 2-3: Parallel dispatch via orchestration engine ──
        orch_engine = StubOrchestrationEngine()
        orch_items: list[StreamItem] = []
        async for orch_item in orch_engine.orchestrate():
            orch_items.append(orch_item)

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded during orchestration dispatch: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        active_step = step1
        for orch_item in orch_items:
            cumulative_tokens += len(orch_item.delta)
            # Augment orchestration item with planning keys + agent identity.
            # Orchestration keys and component keys are passed through from
            # the orchestration stub's trace_context.
            augmented_ctx = dict(orch_item.trace_context) if orch_item.trace_context else {}
            augmented_ctx.update({
                "planning.step_index": orch_item.index + 2,  # offset by serial steps
                "planning.reasoning_depth": 2,
                "planning.parent_step_id": "step-1",
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            })

            yield StreamItem(
                delta=f"[planning] {orch_item.delta}",
                index=orch_item.index + 2,
                model="planning/stub",
                is_terminal=False,
                finish_reason=None,
                trace_context=augmented_ctx,
            )

        # ── Step 4: Synthesize merged results (serial, terminal) ──
        merge_count = len(orch_items)
        step4 = PlanningStep(
            step_index=merge_count + 2,
            reasoning_depth=1,
            parent_step_id="step-1",
            content=f"Synthesizing {merge_count} merged results from "
                    f"{len(sub_tasks)} parallel branches",
            is_terminal=True,
        )
        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded at step 4: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )
        cumulative_tokens += len(step4.content)
        yield StreamItem(
            delta=step4.content,
            index=merge_count + 2,
            model="planning/stub",
            is_terminal=True,
            finish_reason="stop",
            trace_context={
                "planning.step_index": step4.step_index,
                "planning.reasoning_depth": step4.reasoning_depth,
                "planning.parent_step_id": step4.parent_step_id,
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            },
        )
