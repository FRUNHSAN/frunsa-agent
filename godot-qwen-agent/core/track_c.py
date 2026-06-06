"""Track C — Engine-deepened pipeline: LLM Planning → Orch → Critic with retry.

Three tracks form a complexity tier system:
  Tier 0 (Track A) — Direct LLM, zero engines
  Tier 1 (Track B) — Static 3-step pipeline
  Tier 2 (Track C) — Full engine pipeline (this file)

Shared infrastructure (XRayBus, Container, Blueprint) across all tracks.
Only Track C wires the real PlanningEngine / OrchestrationEngine / CriticEngine.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any, Callable

from core.trace_node import TraceStatus, TraceNode


# ── Safe async bridge (暗礁 1: event loop bomb) ──────────────────────

def safe_async_run(coro):
    """Run a coroutine safely regardless of current event loop state.

    - No running loop → asyncio.run() (fresh loop)
    - Already inside an async context → thread pool (prevents
      RuntimeError from httpx clients bound to old loops)
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


# ── Scratchpad (暗礁 2: token explosion mitigation built-in) ────────

class Scratchpad:
    """Mutable shared state across Track C steps.

    WARNING: this is for LLM consumption, not human reading.
    TRUNCATE before feeding to Critic — stale data from failed retries
    will blow up the context window.
    """

    def __init__(self, max_retries: int = 2) -> None:
        self.plan: list[dict] = []        # Planning steps from engine
        self.step_results: list[str] = []  # Orchestration outputs
        self.critic_score: float = 0.0
        self.critic_detail: str = ""
        self.retry_count: int = 0
        self.max_retries: int = max_retries

    def truncated_for_critic(self) -> str:
        """Return compact representation for Critic prompt injection.

        On retries, only the LAST result is kept (truncated to 1000 chars).
        This prevents token explosion from accumulating failed outputs.
        """
        if self.retry_count > 0 and self.step_results:
            last = self.step_results[-1][:1000]
            return last + ("...(truncated)" if len(self.step_results[-1]) > 1000 else "")
        combined = " | ".join(r[:500] for r in self.step_results[-3:])
        return combined[:1500]

    def needs_retry(self) -> bool:
        return self.critic_score < 0.70 and self.retry_count < self.max_retries


# ── Collector helper: drain async iterator into list ─────────────────

async def _collect(agen):
    """Drain an AsyncIterator[StreamItem] into a list of StreamItems."""
    items = []
    async for item in agen:
        items.append(item)
    return items


# ── Engine runner: assemble full pipeline ────────────────────────────

class TrackCEngine:
    """Assembles Planning → Orch → Critic engines and runs the pipeline.

    Does NOT own the engines — they are injected from Container.
    This is a pure orchestrator: receives engines, runs the flow.
    """

    def __init__(
        self,
        planning_engine,
        orch_engine,
        critic_engine,
        bus=None,  # XRayBus for observability
    ) -> None:
        self._planning = planning_engine
        self._orch = orch_engine
        self._critic = critic_engine
        self._bus = bus

    def _emit(self, stage: str, detail: str) -> None:
        if self._bus:
            self._bus.emit(stage, detail)

    def _emit_trace(self, node: TraceNode) -> None:
        if self._bus:
            self._bus.trace(node)

    # ── Public entry point ──────────────────────────────────────────

    def run(self, user: str, system: str, round_count: int = 0) -> str:
        """Execute full Track C pipeline synchronously. Called by REPL.

        Flow: Planning → Orchestration → Critic → (retry?) → Synthesize
        """
        t0 = time.time()

        # ── Phase 1: Planning ──
        self._emit("🔀 Track C Planning", "⏳ 动态规划中...")
        plan_result = safe_async_run(self._do_plan(user, system))
        self._emit_trace(TraceNode(
            node_id=f"c_plan_{round_count}", name="TrackC_Planning",
            node_type="agent", status=TraceStatus.SUCCESS,
            metadata={"elapsed_ms": (time.time() - t0) * 1000, "steps": len(plan_result)},
        ))
        self._emit("🔀 Track C Planning", f"拆解 {len(plan_result)} 步 ({time.time()-t0:.1f}s)")

        # ── Phase 2: Orchestration → Critic (retry loop) ──
        pad = Scratchpad(max_retries=2)
        pad.plan = plan_result

        while True:
            t_orch = time.time()
            self._emit("🔀 Track C Orch", f"⏳ 执行 {len(pad.plan)} 步...")
            pad.step_results = safe_async_run(
                self._do_orchestrate(pad.plan, user, system, pad.truncated_for_critic())
            )
            orch_elapsed = time.time() - t_orch
            self._emit("🔀 Track C Orch", f"完成 {len(pad.step_results)} 步 ({orch_elapsed:.1f}s)")

            # ── Phase 3: Critic ──
            t_critic = time.time()
            self._emit("🔀 Track C Critic", "⏳ 评估中...")
            score, detail = safe_async_run(
                self._do_critique(user, pad.truncated_for_critic())
            )
            pad.critic_score = score
            pad.critic_detail = detail
            self._emit("🔀 Track C Critic", f"评分={score:.2f} ({time.time()-t_critic:.1f}s): {detail[:60]}")

            if not pad.needs_retry():
                break

            pad.retry_count += 1
            self._emit("🔀 Track C Critic", f"不满意 → 重试 ({pad.retry_count}/{pad.max_retries})")

        # ── Phase 4: Synthesize final response ──
        self._emit("🔀 Track C 合成", "⏳ 合成最终回复...")
        final = self._synthesize(user, system, pad)
        self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
        return final

    # ── Async engine wrappers ───────────────────────────────────────

    async def _do_plan(self, user: str, system: str) -> list[dict]:
        """Call PlanningEngine, extract steps from StreamItems."""
        from engines.planning.interface import PlanningContext
        from core.contracts.streaming_protocol import PaceConfig

        ctx = PlanningContext(
            goal=user,
            max_parallel_branches=2,
        )
        items = await _collect(self._planning.plan(
            ctx, deadline=60.0, pace_config=PaceConfig(),
        ))
        # Extract steps from terminal item's trace_context
        steps = []
        for item in items:
            if item.trace_context and "planning.steps" in item.trace_context:
                steps = item.trace_context["planning.steps"]
        if not steps:
            # Fallback: synthesize from all deltas
            full_text = "".join(i.delta for i in items)
            steps = [{"prompt": full_text[:200], "tool": ""}]
        return steps

    async def _do_orchestrate(
        self, plan: list[dict], user: str, system: str, prev_context: str,
    ) -> list[str]:
        """Execute each plan step via OrchestrationEngine."""
        from engines.orchestration.interface import OrchestrationContext, BranchSpec
        from core.contracts.streaming_protocol import PaceConfig

        results = []
        for i, step in enumerate(plan):
            branch = BranchSpec(
                id=f"step_{i}",
                prompt=step.get("prompt", str(step)),
                tool=step.get("tool", ""),
            )
            ctx = OrchestrationContext(
                goal=user,
                branches=(branch,),
                system_prompt=system,
                previous_context=prev_context,
            )
            items = await _collect(self._orch.orchestrate(
                ctx, deadline=60.0, pace_config=PaceConfig(),
            ))
            full = "".join(item.delta for item in items)
            if full:
                results.append(full)
        return results

    async def _do_critique(self, user: str, result_text: str) -> tuple[float, str]:
        """Evaluate results via CriticEngine."""
        from engines.critic.interface import CriticContext
        from core.contracts.streaming_protocol import PaceConfig

        ctx = CriticContext(
            goal=user,
            candidate=result_text,
        )
        items = await _collect(self._critic.evaluate(
            ctx, deadline=30.0, pace_config=PaceConfig(),
        ))
        # Extract score from trace_context
        score = 0.5
        detail = ""
        for item in items:
            if item.trace_context and "critic.score" in item.trace_context:
                score = float(item.trace_context["critic.score"])
                detail = item.trace_context.get("critic.detail", "")
        if not detail:
            full = "".join(i.delta for i in items)
            detail = full[:200]
        return score, detail or "满意"

    # ── Synthesis ───────────────────────────────────────────────────

    def _synthesize(self, user: str, system: str, pad: Scratchpad) -> str:
        """Build final response from all step results + critique."""
        parts = [
            f"用户问题: {user}",
            f"分析结果: {pad.truncated_for_critic()}",
            f"Critic评分: {pad.critic_score:.2f} — {pad.critic_detail}",
        ]
        if pad.retry_count > 0:
            parts.append(f"(经过 {pad.retry_count} 次重试后通过)")
        prompt = f"{system}\n\n" + "\n".join(parts) + "\n请基于以上内容生成最终回复。"

        # Use planning engine's adapter for synthesis (or direct LLM call)
        # Fallback: use the orchestration engine's backend
        from core.contracts import GenerationResult
        result = safe_async_run(self._planning._adapter.generate(prompt, [], {}))
        if isinstance(result, GenerationResult):
            return result.text
        return str(result)
