"""Real LLM-backed Critic Engine with deterministic MockCriticBackend.

Phase 18: Third real engine — evaluates planning engine output with LLM
scoring instead of hardcoded values. MockCriticBackend provides
deterministic CI testing. StubCriticEngine remains the fast reference.

Architecture:
  LLMCriticEngine implements CriticEngine Protocol.
  Uses GenerationAdapter for LLM calls (tracing, timeout, credentials).
  MockCriticBackend implements GenerationBackend Protocol with pre-canned responses.

Engine flow:
  0. Receive CriticContext with plan_output and metadata slot
  1. Task decomposition evaluation (LLM) -> score + verdict
  2. Parallel dispatch evaluation (LLM) -> score + verdict
  3. Result synthesis evaluation (LLM, terminal) -> score + verdict
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, List

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.critic.identity import CriticAgent
from engines.critic.interface import CriticContext


# ── Mock LLM Backend ───────────────────────────────────────────────────

@dataclass(frozen=True)
class MockCriticBackend:
    """Deterministic LLM backend for critic CI testing.

    Uses pre-canned responses in round-robin order. Frozen dataclass with
    _call_count mutation via object.__setattr__ (Phase 7 pattern).

    Three response slots per cycle: decomposition -> dispatch -> synthesis.
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
            model="mock/critic",
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

CRITIC_DECOMPOSITION_PROMPT = """\
You are a critic agent evaluating a planning engine's task decomposition.

Plan output to evaluate:
{plan_output}

Evaluate the task decomposition quality. Consider:
- Are sub-goals clearly defined?
- Is the granularity appropriate?
- Are dependencies between steps clear?

Return a JSON object with:
- "score": float (0.0-1.0 quality score)
- "verdict": string ("accept", "rework", or "reject")
- "reasoning": string (brief explanation)

Respond with ONLY the JSON object, no other text."""

CRITIC_DISPATCH_PROMPT = """\
You are a critic agent evaluating a planning engine's parallel dispatch strategy.

Plan output to evaluate:
{plan_output}

Evaluate the parallel dispatch quality. Consider:
- Is the branch count appropriate?
- Are merge strategies specified?
- Is the parallel depth reasonable?

Return a JSON object with:
- "score": float (0.0-1.0 quality score)
- "verdict": string ("accept", "rework", or "reject")
- "reasoning": string (brief explanation)

Respond with ONLY the JSON object, no other text."""

CRITIC_SYNTHESIS_PROMPT = """\
You are a critic agent evaluating a planning engine's result synthesis.

Plan output to evaluate:
{plan_output}

Evaluate the synthesis quality. Consider:
- Are all branch outputs integrated?
- Is the final conclusion well-structured?
- Are divergent perspectives reconciled?

Return a JSON object with:
- "score": float (0.0-1.0 quality score)
- "verdict": string ("accept", "rework", or "reject")
- "reasoning": string (brief explanation)

Respond with ONLY the JSON object, no other text."""

# Default mock responses — match stub values exactly
DEFAULT_DECOMPOSITION_RESPONSE = (
    '{"score": 0.85, "verdict": "accept", '
    '"reasoning": "Clear sub-goals."}'
)

DEFAULT_DISPATCH_RESPONSE = (
    '{"score": 0.72, "verdict": "rework", '
    '"reasoning": "Merge strategy unspecified."}'
)

DEFAULT_SYNTHESIS_RESPONSE = (
    '{"score": 0.90, "verdict": "accept", '
    '"reasoning": "Well-structured synthesis."}'
)


# ── Default Backend Factory ────────────────────────────────────────────

def _default_mock_backend() -> MockCriticBackend:
    """Create the default mock backend for CI testing."""
    return MockCriticBackend(responses=(
        DEFAULT_DECOMPOSITION_RESPONSE,
        DEFAULT_DISPATCH_RESPONSE,
        DEFAULT_SYNTHESIS_RESPONSE,
    ))


# ── Output Parser ──────────────────────────────────────────────────────

def _parse_critic_evaluation(raw_text: str) -> dict:
    """Parse LLM critic output into a dict with score, verdict, reasoning.

    Handles markdown code fences and extra JSON fields.
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
            f"Failed to parse critic output as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    if "score" not in data:
        raise ValueError("Critic response missing 'score' field")
    if "verdict" not in data:
        raise ValueError("Critic response missing 'verdict' field")

    score = data["score"]
    if not isinstance(score, (int, float)):
        raise ValueError(f"Score must be numeric, got {type(score).__name__}")

    verdict = data["verdict"]
    if verdict not in ("accept", "rework", "reject"):
        raise ValueError(f"Invalid verdict '{verdict}', expected accept/rework/reject")

    return data


# ── LLM Critic Engine ──────────────────────────────────────────────────


class LLMCriticEngine:
    """Real LLM-backed Critic Engine using GenerationAdapter.

    Implements CriticEngine Protocol. 3-step evaluation flow:
      0. Task decomposition evaluation (LLM)
      1. Parallel dispatch evaluation (LLM)
      2. Result synthesis evaluation (LLM, terminal)

    Each StreamItem carries critic.score, critic.verdict, and agent.identity.
    MockCriticBackend default responses match StubCriticEngine values exactly.

    Principle 1 (Assembly Contract): injectable as critic_factory (future).
    Principle 2 (Contract Locking): critic keys enforced by guardrail.
    """

    identity = CriticAgent(
        id="critic-llm-v1",
        role="critic",
        version="1.0.0",
        capabilities=(
            "result_evaluation", "quality_scoring", "llm_backed",
        ),
    )

    def __init__(
        self,
        adapter: GenerationAdapter,
        evaluation_temperature: float = 0.3,
    ) -> None:
        self._adapter = adapter
        self._eval_temp = evaluation_temperature

    async def evaluate(
        self,
        context: CriticContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute 3-step LLM-backed critic evaluation.

        Args:
            context: CriticContext with plan_output and agent identity.
            deadline: Operation-level deadline in seconds (duration).
            pace_config: QoS parameters.
        """
        start = time.perf_counter()
        identity_value = self.identity.to_trace_value()
        plan_output = context.plan_output

        evaluations = [
            ("task_decomposition", CRITIC_DECOMPOSITION_PROMPT, DEFAULT_DECOMPOSITION_RESPONSE),
            ("parallel_dispatch", CRITIC_DISPATCH_PROMPT, DEFAULT_DISPATCH_RESPONSE),
            ("result_synthesis", CRITIC_SYNTHESIS_PROMPT, DEFAULT_SYNTHESIS_RESPONSE),
        ]

        total = len(evaluations)

        for idx, (step_name, prompt_template, _default) in enumerate(evaluations):
            if time.perf_counter() - start > deadline:
                raise asyncio.TimeoutError(
                    f"Critic deadline exceeded at step {idx} '{step_name}': "
                    f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
                )

            prompt = prompt_template.format(plan_output=plan_output)

            try:
                result = await self._adapter.generate(
                    prompt, [],
                    temperature=self._eval_temp,
                )
                eval_data = _parse_critic_evaluation(result.text)
            except Exception as e:
                yield StreamItem(
                    delta=f"Critic {step_name} evaluation failed: {e}",
                    index=idx,
                    model="critic/llm",
                    is_terminal=(idx == total - 1),
                    finish_reason="error" if idx == total - 1 else None,
                    error=str(e),
                    trace_context={
                        "critic.score": 0.0,
                        "critic.verdict": "reject",
                        "agent.identity": identity_value,
                    },
                )
                if idx == total - 1:
                    return
                continue

            delta = (
                f"{step_name}: score={eval_data['score']}, "
                f"verdict={eval_data['verdict']}, "
                f"reasoning={eval_data.get('reasoning', '')}"
            )

            yield StreamItem(
                delta=delta,
                index=idx,
                model="critic/llm",
                is_terminal=(idx == total - 1),
                finish_reason="stop" if idx == total - 1 else None,
                trace_context={
                    "critic.score": float(eval_data["score"]),
                    "critic.verdict": eval_data["verdict"],
                    "agent.identity": identity_value,
                },
            )
