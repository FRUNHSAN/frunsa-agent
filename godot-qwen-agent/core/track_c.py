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


# ── Configurable constants ──────────────────────────────────────────
MIN_PLAN_STEPS = 3  # Minimum plan steps before retry (configurable via env)


# ── V5.1: Lambda Gain Scheduling ───────────────────────────────────

def _lambda_hint(trust: float, e_t: float) -> str:
    """Inject system state as a dynamic prior into the Planning prompt.

    lambda = f(trust, e_t): adjusts the LLM's risk aversion, not its decision.
    Low trust or high e(t) -> lambda->0 -> conservative -> prefer FULL_DAG.
    High trust + low e(t) -> lambda free -> efficiency-optimized -> DIRECT OK.
    """
    if trust < 0.15 or e_t > 0.65:
        return (
            "[SYSTEM STATE] Trust critically low or tracking error elevated. "
            "Be extremely conservative — use DIRECT only for trivial single-word "
            "replies or explicit goodbyes. Default to FULL_DAG for everything else."
        )
    if trust < 0.30 or e_t > 0.55:
        return (
            "[SYSTEM STATE] Trust below comfort zone or error trending up. "
            "Lean conservative — DIRECT only for clear format adjustments "
            "('make it shorter', 'add more detail'). Borderline cases -> FULL_DAG."
        )
    if trust > 0.70 and e_t < 0.45:
        return (
            "[SYSTEM STATE] High trust, stable tracking. You have full autonomy "
            "to optimize for efficiency. DIRECT is encouraged for simple tasks."
        )
    return ""  # No hint — LLM uses its own semantic judgment


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
        adapter=None,  # GenerationAdapter for synthesis fallback
        bus=None,  # XRayBus for observability
    ) -> None:
        self._planning = planning_engine
        self._orch = orch_engine
        self._critic = critic_engine
        self._adapter = adapter
        self._bus = bus

    def _emit(self, stage: str, detail: str) -> None:
        if self._bus:
            self._bus.emit(stage, detail)

    def _emit_trace(self, node: TraceNode) -> None:
        if self._bus:
            self._bus.trace(node)

    # ── Public entry point ──────────────────────────────────────────

    def run(self, user: str, system: str, round_count: int = 0,
            trust: float = 0.5, e_t: float = 0.5) -> str:
        """Execute Track C pipeline synchronously. Called by REPL.

        V5.1: Lambda gain scheduling + DIRECT short-circuit.
        Flow: Planning → {DIRECT: Synthesis} | {FULL_DAG: Orch → Critic → (retry?) → Synthesize}
        """
        t0 = time.time()
        lambda_hint = _lambda_hint(trust, e_t)

        # ── Phase 1: Planning ──
        self._emit("🔀 Track C Planning", "⏳ 动态规划中...")
        plan_result = safe_async_run(self._do_plan(user, system, lambda_hint))
        is_direct = plan_result and len(plan_result) == 1 and plan_result[0].get("type") == "DIRECT"

        self._emit_trace(TraceNode(
            node_id=f"c_plan_{round_count}", name="TrackC_Planning",
            node_type="agent", status=TraceStatus.SUCCESS,
            metadata={"elapsed_ms": (time.time() - t0) * 1000,
                      "steps": len(plan_result),
                      "mode": "DIRECT" if is_direct else "FULL_DAG"},
        ))

        # ── V5.1: DIRECT short-circuit ──
        if is_direct:
            self._emit("🔀 Track C Planning", f"DIRECT (short-circuit, {time.time()-t0:.1f}s)")
            pad = Scratchpad(max_retries=0)
            pad.plan = plan_result
            pad.critic_score = 1.0  # No critic — assume satisfaction
            final = self._synthesize(user, system, pad)
            self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
            return final

        # ── FULL_DAG: unchanged pipeline ──
        self._emit("🔀 Track C Planning", f"FULL_DAG: {len(plan_result)} 步 ({time.time()-t0:.1f}s)")

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
            self._emit(f"🔀 Track C 评分", f"{score:.2f} ({time.time()-t_critic:.1f}s): {detail[:60]}")

            if not pad.needs_retry():
                self._emit("🔀 Track C 评分", f"{score:.2f} ✅ 通过")
                break

            pad.retry_count += 1
            self._emit("🔀 Track C 评分", f"{score:.2f} ❌ 重试 ({pad.retry_count}/{pad.max_retries})")

        # ── Phase 4: Synthesize final response ──
        self._emit("🔀 Track C 合成", "⏳ 合成最终回复...")
        final = self._synthesize(user, system, pad)
        self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
        return final

    # ── Async engine wrappers ───────────────────────────────────────

    async def _do_plan(self, user: str, system: str, lambda_hint: str = "",
                       retry: bool = False) -> list[dict]:
        """V5.1: Complexity-routing Planning with lambda gain scheduling.

        LLM chooses between two output formats:
          DIRECT  — trivial task, skip Orch+Critic, go straight to Synthesis.
          FULL_DAG — non-trivial task, full Planning→Orch→Critic pipeline.

        Lambda hint injects system state (trust, e_t) as a dynamic prior,
        adjusting the LLM's risk aversion without commanding its decision.
        """
        from engines.planning.interface import PlanningContext
        from core.contracts.streaming_protocol import PaceConfig
        import os

        state_hint = f"\n\n{lambda_hint}" if lambda_hint else ""
        min_steps = int(os.environ.get("MIN_PLAN_STEPS", MIN_PLAN_STEPS))

        if not retry:
            goal = (
                f"{user}\n\n"
                f"[规划指令] 根据用户意图的复杂度选择输出格式：\n\n"
                f"如果用户意图是格式微调、简单追问、闲聊或延续已有内容"
                f"（如'字多一点'、'继续'、'好的'），输出 DIRECT：\n"
                f'  {{"type": "DIRECT", "action": "直接基于上下文生成回复"}}\n\n'
                f"如果用户意图需要新增知识、多步推理或工具调用，输出 FULL_DAG：\n"
                f'  {{"type": "FULL_DAG", "steps": [{{"prompt": "...", "tool": ""}}, ...]}}\n'
                f"  （拆解为 {min_steps}-5 步，每步包含 prompt 和 tool 字段。"
                f"在 JSON 之前用 <!-- reasoning --> 注释简要说明选择理由。）"
                f"{state_hint}"
            )
        else:
            goal = (
                f"{user}\n\n"
                f"[约束: 必须拆解为至少 {min_steps} 个独立子任务。"
                f"每步包含 prompt 和 tool 字段。返回 JSON 数组。]"
            )

        ctx = PlanningContext(goal=goal, max_parallel_branches=2)
        items = await _collect(self._planning.plan(
            ctx, deadline=60.0, pace_config=PaceConfig(),
        ))

        # Group items by step_index
        groups: dict[int, list[str]] = {}
        for item in items:
            idx = 0
            if item.trace_context:
                idx = item.trace_context.get("planning.step_index", 0)
            groups.setdefault(idx, []).append(item.delta)

        # Build steps from grouped deltas
        steps = []
        for idx in sorted(groups.keys()):
            text = "".join(groups[idx]).strip()
            if text:
                # V5.1: Preserve type field for DIRECT detection
                step = {"prompt": text[:300], "tool": ""}
                if '"type": "DIRECT"' in text or "'type': 'DIRECT'" in text:
                    step["type"] = "DIRECT"
                elif '"type": "FULL_DAG"' in text or "'type': 'FULL_DAG'" in text:
                    step["type"] = "FULL_DAG"
                steps.append(step)

        # DIRECT: always valid (1 step is correct)
        if steps and steps[0].get("type") == "DIRECT":
            return steps

        # FULL_DAG: retry if too few steps
        if len(steps) < min_steps and not retry:
            self._emit("🔀 Track C Planning", f"仅 {len(steps)} 步 → 重新规划")
            return await self._do_plan(user, system, lambda_hint, retry=True)

        return steps if steps else [{"prompt": f"综合分析: {user}", "tool": ""}]

    async def _do_orchestrate(
        self, plan: list[dict], user: str, system: str, prev_context: str,
    ) -> list[str]:
        """Execute plan steps via OrchestrationEngine — parallelized (V4.3 speed)."""
        import asyncio as _asyncio
        tasks = [self._orchestrate_one(step, user, system, prev_context) for step in plan]
        raw = await _asyncio.gather(*tasks, return_exceptions=True)
        # Safety clamp: explicit error marking for downstream Critic/Synth
        return [r if isinstance(r, str) else f"[STEP_FAILED: {type(r).__name__}: {r}]" for r in raw]

    async def _orchestrate_one(
        self, step: dict, user: str, system: str, prev_context: str,
    ) -> str:
        """Execute a single orchestration branch."""
        from engines.orchestration.interface import OrchestrationContext, BranchSpec
        from engines.orchestration.identity import OrchestratorIdentity
        from core.contracts.streaming_protocol import PaceConfig

        branch = BranchSpec(
            name=step.get("prompt", str(step))[:60],
            pool=step.get("tool", "default"),
            items=1,
        )
        ctx = OrchestrationContext(
            branches=(branch,),
            agent_identity=OrchestratorIdentity(id="orch-v1", role="orchestration", version="1.0.0"),
            max_retries=1,
            metadata={"goal": user, "system_prompt": system, "context": prev_context},
        )
        items = await _collect(self._orch.orchestrate(
            ctx, deadline=60.0, pace_config=PaceConfig(),
        ))
        return "".join(item.delta for item in items)

    async def _do_critique(self, user: str, result_text: str) -> tuple[float, str]:
        """Evaluate results via CriticEngine."""
        from engines.critic.interface import CriticContext
        from core.contracts.streaming_protocol import PaceConfig

        ctx = CriticContext(
            plan_output=f"Goal: {user}\n\nResults: {result_text}",
            metadata={"goal": user},
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
        """Build final response from all step results + critique.

        Uses the injected GenerationAdapter for LLM synthesis.
        """
        parts = [
            f"用户问题: {user}",
            f"分析结果: {pad.truncated_for_critic()}",
            f"Critic评分: {pad.critic_score:.2f} — {pad.critic_detail}",
        ]
        if pad.retry_count > 0:
            parts.append(f"(经过 {pad.retry_count} 次重试后通过)")
        prompt = f"{system}\n\n" + "\n".join(parts) + "\n请基于以上内容生成最终回复。"

        if self._adapter:
            from core.contracts import GenerationResult
            result = safe_async_run(self._adapter.generate(prompt, [], {}))
            if isinstance(result, GenerationResult):
                return result.text
            return str(result)
        # Last resort: return concatenated results
        return "\n\n".join(pad.step_results[-3:])
