"""Real LLM-backed Planning Engine with deterministic MockLLMBackend.

Phase 17: First real engine — reuses GenerationAdapter rather than calling
LLM SDK directly. MockLLMBackend provides deterministic CI testing.
StubPlanningEngine remains untouched as the fast reference implementation.

Architecture:
  LLMPlanningEngine implements PlanningEngine Protocol.
  Uses GenerationAdapter for LLM calls (tracing, timeout, credentials).
  MockLLMBackend implements GenerationBackend Protocol with pre-canned responses.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, List

from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext, PlanningStep


# ── Mock LLM Backend ───────────────────────────────────────────────────

@dataclass(frozen=True)
class MockLLMBackend:
    """Deterministic LLM backend implementing GenerationBackend Protocol.

    Uses pre-canned responses in round-robin order. Frozen dataclass with
    _call_count mutation via object.__setattr__ (Phase 7 pattern).
    """

    responses: tuple[str, ...]
    _call_count: int = field(default=0, repr=False)

    def generate(
        self, prompt: str, context: List[Any], **params: Any
    ) -> GenerationResult:
        idx = self._call_count % len(self.responses)
        text = self.responses[idx]
        object.__setattr__(self, "_call_count", self._call_count + 1)

        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(text) // 4)
        return GenerationResult(
            text=text,
            model="mock/planning",
            finish_reason="stop",
            usage=MappingProxyType({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }),
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


# ── Prompt Templates ───────────────────────────────────────────────────

PLAN_DECOMPOSE_TEMPLATE = """\
You are a planning agent. Decompose the following goal into concrete steps.

Goal: {goal}

Sub-tasks to dispatch in parallel: {sub_tasks}
Max parallel branches: {max_branches}

Return a JSON array of planning steps. Each step has:
- "step_id": integer (0-based position in the reasoning chain)
- "depth": integer (0=root analysis, 1=sub-task decomposition)
- "parent_id": string or null (step_id of parent, null for root)
- "content": string (the reasoning text for this step)
- "is_terminal": boolean (true only for the final conclusion step)

Include exactly 3 steps:
1. Root analysis of the goal (depth=0, parent_id=null)
2. Sub-task decomposition into parallel branches (depth=1)
3. (terminal) Synthesis of branch results (depth=1, is_terminal=true)

Respond with ONLY the JSON array, no other text."""

PLAN_SYNTHESIZE_TEMPLATE = """\
Synthesize the following parallel branch results into a final conclusion.

Goal: {goal}
Branch results:
{branch_results}

Return a JSON object with:
- "content": string (the synthesized conclusion)

Respond with ONLY the JSON object, no other text."""

# Default mock responses — deterministic JSON for CI testing
DEFAULT_DECOMPOSE_RESPONSE = (
    '['
    '{"step_id": 0, "depth": 0, "parent_id": null, '
    '"content": "Analyzing goal: determine optimal execution strategy for '
    'the given objective, assessing complexity and resource requirements", '
    '"is_terminal": false},'
    '{"step_id": 1, "depth": 1, "parent_id": "step-0", '
    '"content": "Decomposing into 2 sub-tasks: fast_path (keyword retrieval) '
    'and full_rerank (semantic reranking) for parallel execution", '
    '"is_terminal": false},'
    '{"step_id": 2, "depth": 1, "parent_id": "step-1", '
    '"content": "Synthesizing merged results from 2 parallel branches: '
    'fast_path returned 3 items, full_rerank returned 2 items. '
    'Final conclusion incorporates both perspectives for comprehensive coverage", '
    '"is_terminal": true}'
    ']'
)

DEFAULT_SYNTHESIZE_RESPONSE = (
    '{"content": "Synthesized conclusion: The parallel execution across '
    'fast_path (keyword retrieval) and full_rerank (semantic reranking) '
    'branches produced complementary results. Fast path provided broad '
    'coverage while full reranking ensured precision. The combined output '
    'represents a comprehensive answer to the original goal."}'
)


# ── Output Parser ──────────────────────────────────────────────────────

def _parse_planning_steps(
    raw_text: str, max_steps: int = 20
) -> List[PlanningStep]:
    """Parse LLM output into PlanningStep instances.

    Handles markdown code fences, extra JSON fields, missing optional fields.
    Raises ValueError with context on parse failures.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse planning output as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )

    if not isinstance(data, list):
        raise ValueError(
            f"Expected JSON array of steps, got {type(data).__name__}"
        )

    steps: List[PlanningStep] = []
    for item in data[:max_steps]:
        try:
            steps.append(PlanningStep(
                step_index=int(item["step_id"]),
                reasoning_depth=int(item.get("depth", 0)),
                parent_step_id=item.get("parent_id"),
                content=str(item["content"]),
                is_terminal=bool(item.get("is_terminal", False)),
            ))
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid step at index {len(steps)}: {e}\nItem: {item}"
            )

    if not steps:
        raise ValueError("LLM returned empty step list")

    return steps


def _parse_synthesis(raw_text: str) -> str:
    """Parse LLM synthesis output into a conclusion string."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse synthesis output as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )

    content = data.get("content", "")
    if not content:
        raise ValueError("LLM synthesis response has empty content")
    return str(content)


# ── LLM Planning Engine ────────────────────────────────────────────────


class LLMPlanningEngine:
    """Real LLM-backed Planning Engine using GenerationAdapter.

    Implements PlanningEngine Protocol. 5-step flow:
      0. Analyze goal (LLM decompose call)
      1. Decompose into sub-tasks
      2-3. Parallel dispatch via StubOrchestrationEngine
      4. Synthesize (LLM synthesize call, terminal)

    Each StreamItem carries planning.* trace_context keys + agent.identity.
    Deadline enforcement before every yield. Token budget tracking.

    StubPlanningEngine remains the fast, deterministic reference.
    """

    identity = AgentIdentity(
        id="planner-llm-v1",
        role="planning",
        version="1.0.0",
        capabilities=(
            "task_decomposition", "parallel_planning", "llm_backed",
        ),
    )

    def __init__(
        self,
        adapter: Any,  # GenerationAdapter
        max_tokens: int = 4096,
        decompose_temperature: float = 0.3,
        synthesize_temperature: float = 0.5,
    ) -> None:
        self._adapter = adapter
        self._max_tokens = max_tokens
        self._decompose_temp = decompose_temperature
        self._synthesize_temp = synthesize_temperature

    async def plan(
        self,
        context: PlanningContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute 5-step LLM-backed plan.

        Args:
            context: PlanningContext with goal, agent identity, sub-tasks.
            deadline: Operation-level deadline in seconds (duration).
            pace_config: QoS parameters (accepted but no-op for now).
        """
        from engines.orchestration.stub import StubOrchestrationEngine

        start = time.perf_counter()
        identity_value = context.agent_identity.to_trace_value()
        cumulative_tokens = 0

        # ── Step 0-1: LLM decomposition ────────────────────────
        sub_tasks_str = ", ".join(context.sub_tasks) if context.sub_tasks else "none"
        decompose_prompt = PLAN_DECOMPOSE_TEMPLATE.format(
            goal=context.goal,
            sub_tasks=sub_tasks_str,
            max_branches=context.max_parallel_branches,
        )

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded before Step 0: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        try:
            result = await self._adapter.generate(
                decompose_prompt, [],
                temperature=self._decompose_temp,
                max_tokens=self._max_tokens,
            )
        except Exception as e:
            yield StreamItem(
                delta=f"LLM decompose failed: {e}",
                index=0,
                model="planning/llm",
                is_terminal=True,
                finish_reason="error",
                error=str(e),
                trace_context={
                    "planning.step_index": 0,
                    "planning.reasoning_depth": 0,
                    "planning.parent_step_id": None,
                    "planning.cumulative_tokens": cumulative_tokens,
                    "agent.identity": identity_value,
                },
            )
            return

        usage = dict(result.usage) if result.usage else {}
        cumulative_tokens += usage.get("total_tokens", 0)

        try:
            steps = _parse_planning_steps(result.text)
        except ValueError as e:
            yield StreamItem(
                delta=f"Failed to parse planning output: {e}",
                index=0,
                model="planning/llm",
                is_terminal=True,
                finish_reason="error",
                error=str(e),
                trace_context={
                    "planning.step_index": 0,
                    "planning.reasoning_depth": 0,
                    "planning.parent_step_id": None,
                    "planning.cumulative_tokens": cumulative_tokens,
                    "agent.identity": identity_value,
                },
            )
            return

        # Emit serial steps from LLM decomposition
        serial_steps = [s for s in steps if s.parent_step_id is None
                        or (s.parent_step_id is not None and s.is_terminal)]
        if not serial_steps:
            serial_steps = steps

        item_index = 0
        for step in serial_steps:
            if step.is_terminal:
                break  # terminal step handled after orchestration
            if time.perf_counter() - start > deadline:
                raise asyncio.TimeoutError(
                    f"Planning deadline exceeded at step {item_index}: "
                    f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
                )
            yield StreamItem(
                delta=step.content,
                index=item_index,
                model="planning/llm",
                is_terminal=False,
                finish_reason=None,
                trace_context={
                    "planning.step_index": step.step_index,
                    "planning.reasoning_depth": step.reasoning_depth,
                    "planning.parent_step_id": step.parent_step_id,
                    "planning.cumulative_tokens": cumulative_tokens,
                    "agent.identity": identity_value,
                },
            )
            item_index += 1

        # ── Steps 2-3: Parallel dispatch via orchestration ────
        orch_engine = StubOrchestrationEngine()
        orch_items: list[StreamItem] = []
        async for orch_item in orch_engine.orchestrate():
            orch_items.append(orch_item)

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded during orchestration: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        for orch_item in orch_items:
            augmented_ctx = (
                dict(orch_item.trace_context) if orch_item.trace_context else {}
            )
            augmented_ctx.update({
                "planning.step_index": orch_item.index + item_index,
                "planning.reasoning_depth": 2,
                "planning.parent_step_id": f"step-{item_index - 1}",
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            })

            yield StreamItem(
                delta=f"[planning] {orch_item.delta}",
                index=orch_item.index + item_index,
                model="planning/llm",
                is_terminal=False,
                finish_reason=None,
                trace_context=augmented_ctx,
            )

        final_index = item_index + len(orch_items)

        # ── Step 4: Synthesize (LLM terminal) ─────────────────
        branch_results = "\n".join(
            f"  [{i}] {item.delta}" for i, item in enumerate(orch_items)
        )
        synthesize_prompt = PLAN_SYNTHESIZE_TEMPLATE.format(
            goal=context.goal, branch_results=branch_results,
        )

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Planning deadline exceeded before synthesis: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        try:
            synth_result = await self._adapter.generate(
                synthesize_prompt, [],
                temperature=self._synthesize_temp,
                max_tokens=self._max_tokens // 2,
            )
        except Exception as e:
            yield StreamItem(
                delta=f"LLM synthesis failed: {e}",
                index=final_index,
                model="planning/llm",
                is_terminal=True,
                finish_reason="error",
                error=str(e),
                trace_context={
                    "planning.step_index": final_index,
                    "planning.reasoning_depth": 1,
                    "planning.parent_step_id": f"step-{item_index - 1}",
                    "planning.cumulative_tokens": cumulative_tokens,
                    "agent.identity": identity_value,
                },
            )
            return

        synth_usage = dict(synth_result.usage) if synth_result.usage else {}
        cumulative_tokens += synth_usage.get("total_tokens", 0)

        try:
            conclusion = _parse_synthesis(synth_result.text)
        except ValueError:
            conclusion = synth_result.text.strip()

        yield StreamItem(
            delta=conclusion,
            index=final_index,
            model="planning/llm",
            is_terminal=True,
            finish_reason="stop",
            trace_context={
                "planning.step_index": final_index,
                "planning.reasoning_depth": 1,
                "planning.parent_step_id": f"step-{item_index - 1}",
                "planning.cumulative_tokens": cumulative_tokens,
                "agent.identity": identity_value,
            },
        )
