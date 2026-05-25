"""Minimal Critic engine stub — Phase 16.

Evaluates planning engine output and assigns quality scores + verdicts.
3 serial steps: receive → evaluate → terminal.

Each StreamItem carries:
  - critic.score (float): quality score 0.0-1.0
  - critic.verdict (str): "accept", "reject", or "rework"
  - agent.identity (dict): CriticAgent identity
"""

from __future__ import annotations

from typing import AsyncIterator

from core.contracts.generation import StreamItem
from engines.critic.identity import CriticAgent


class StubCriticEngine:
    """Simulates critic evaluation of planning engine output.

    Produces 3 StreamItems with varying scores and verdicts.
    Follows the engine stub pattern: frozen identity, async generator,
    trace_context on every item, terminal sentinel.
    """

    def __init__(self, agent: CriticAgent | None = None) -> None:
        self._agent = agent or CriticAgent(
            id="critic-v1",
            role="critic",
            version="1.0.0",
            capabilities=("result_evaluation", "quality_scoring"),
        )

    async def evaluate(self) -> AsyncIterator[StreamItem]:
        evaluations = [
            {"step": "task_decomposition", "score": 0.85, "verdict": "accept",
             "delta": "Task decomposition: clear sub-goals, reasonable granularity."},
            {"step": "parallel_dispatch", "score": 0.72, "verdict": "rework",
             "delta": "Parallel dispatch: branch count appropriate but merge strategy unspecified."},
            {"step": "result_synthesis", "score": 0.90, "verdict": "accept",
             "delta": "Result synthesis: well-structured, all branch outputs integrated."},
        ]

        total = len(evaluations)
        identity = self._agent.to_trace_value()

        for idx, ev in enumerate(evaluations):
            yield StreamItem(
                delta=ev["delta"],
                index=idx,
                model="critic/stub",
                is_terminal=(idx == total - 1),
                finish_reason="stop" if idx == total - 1 else None,
                trace_context={
                    "critic.score": ev["score"],
                    "critic.verdict": ev["verdict"],
                    "agent.identity": identity,
                },
            )
