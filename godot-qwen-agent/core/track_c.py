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


# ── V5.3 Path 2: Dual-Sensor Fusion (drift ⊕ clarity) ─────────────────

def _compute_drift_factor(raw_drift):
    """Map absolute cosine distance [0,2] to drift factor [0,1].
    Deadzone 0.20: normal topic flow, f=0.
    Ramp 0.20-0.60: substantial direction shift.
    Saturation >0.60: user overturned all assumptions, f=1.
    Calibrated from Session 70: R1→R2 drift=0.54, R2→R3 drift=0.42."""
    if raw_drift < 0.20:
        return 0.0
    if raw_drift > 0.60:
        return 1.0
    return (raw_drift - 0.20) / 0.40


def compute_dual_sensor_f(raw_drift: float, clarity: float) -> float:
    """Dual-sensor fusion: drift (cross-round trajectory) + clarity (in-round state).

    f_drift: how much user changed topics (temporal, drift factor).
    f_clarity: how confused user is (instantaneous, 1 - clarity).

    Lucid suppression: clarity > 0.80 → min(f_drift, 0.20).
    High clarity + high drift = user is lucidly changing topics, not confused.
    Suppress drift-driven exploration to stay focused.

    Otherwise OR logic: max(f_drift, f_clarity).
    Either sensor alone can trigger exploration — drift OR confusion.

    Returns fused sensor factor f ∈ [0.0, 1.0].
    """
    f_drift = _compute_drift_factor(raw_drift)
    f_clarity = max(0.0, 1.0 - clarity)

    # Lucid topic switch: user is clear → suppress drift-triggered exploration
    if clarity > 0.80:
        return min(f_drift, 0.20)

    # OR logic: either signal triggers exploration
    return max(f_drift, f_clarity)


def _path2_branch_count(f: float) -> int:
    """Fused sensor factor → Planning branches. Pure math — zero keyword logic.

    f ≤ 0.30:   EXPLOIT  (1 branch, focused execution)
    0.30 < f ≤ 0.50: BALANCED (2 branches, moderate exploration)
    f > 0.50:   EXPLORE  (3 branches, maximal coverage)
    """
    if f <= 0.3:
        return 1  # EXPLOIT
    if f > 0.5:
        return 3  # EXPLORE
    return 2      # BALANCED


def _critic_factors(raw_drift, e_t):
    """f(drift): user direction change via deadzone+ramp.
       g(e_t): strategy failure via deadzone+ramp."""
    f = _compute_drift_factor(raw_drift)
    g = max(0.0, min(1.0, (e_t - 0.55) / 0.15))
    return f, g


def _critic_threshold(f, g, session_gain: float = 1.0):
    """Multiplicative gating. θ drops only when user changed topic AND strategy fails.

    V6.2: session_gain from Wasserstein Bayesian smoothing provides domain-adaptive
    sensitivity. Wide domain (gain>1) → θ slightly relaxed. Narrow domain (gain<1) →
    θ slightly tightened. Effect bounded at ±0.05 — gain is subordinate to the
    primary f×g gating.
    """
    base = max(0.50, 0.75 - 0.25 * f * g)
    # Domain-adaptive sensitivity: ±0.05 max adjustment
    theta = base - 0.05 * (session_gain - 1.0)
    return max(0.50, min(0.75, theta))


def _dynamic_output_mult(branch_count, raw_drift):
    """Cognitive complexity → output capacity multiplier.
    More branches + higher drift = system is exploring deeply → let it speak fully."""
    mult = 1.0
    if branch_count >= 3:
        mult = 1.8
    elif branch_count >= 2:
        mult = 1.4
    if raw_drift > 0.5:
        mult = max(mult, 1.6)  # Major topic shift → ensure room
    return mult


# ── V6.1: DAG Topology Engine ────────────────────────────────────────

def _extract_step_fields(text: str, step: dict) -> None:
    """Try to extract V6.1 structural fields from LLM step output.

    LLM may embed produces/needs/depends_on in JSON within the step text.
    Graceful degradation: if parsing fails, fields are absent (no crash).
    """
    import json as _json
    import re as _re
    try:
        # Find the first JSON object in the text
        match = _re.search(r'\{[^{}]*\}', text.replace('\n', ' '))
        if match:
            data = _json.loads(match.group())
            for key in ("produces", "needs", "depends_on",
                         "test_cases", "intent_type"):
                if key in data:
                    step[key] = data[key]
    except (_json.JSONDecodeError, KeyError, ValueError):
        pass  # LLM didn't output structured JSON — fields absent, no crash


def _build_dag_and_depth(steps: list[dict]) -> tuple[list[dict], int]:
    """Build DAG from step tags + indices, compute maximal safe parallel depth.

    Resolution order:
      1. Match produces/needs tags (deterministic string equality)
      2. Fall back to depends_on indices for unmatched needs
      3. Resolve transitive dependencies for tags

    Returns (steps_with_deps, parallel_depth).
    parallel_depth = 1 if cycle detected (graph theory: no topological order exists).
    """
    n = len(steps)

    # ── 1. Build tag-to-index map ──
    tag_to_idx: dict[str, int] = {}
    for i, s in enumerate(steps):
        tag = str(s.get("produces", "")).strip()
        if tag:
            tag_to_idx[tag] = i

    # ── 2. Resolve dependencies per step ──
    for i, s in enumerate(steps):
        resolved = set()

        # Tag-based: match needs tags to produces tags
        needs_tag = str(s.get("needs", "")).strip()
        if needs_tag and needs_tag in tag_to_idx:
            resolved.add(tag_to_idx[needs_tag])

        # Index-based fallback: explicit depends_on indices
        raw_deps = s.get("depends_on", [])
        if isinstance(raw_deps, list):
            for d in raw_deps:
                if isinstance(d, int) and 0 <= d < n and d != i:
                    resolved.add(d)

        s["_resolved_deps"] = sorted(resolved)

    # ── 3. Sanitize: filter out-of-bounds, self-loops ──
    for s in steps:
        s["_resolved_deps"] = [d for d in s.get("_resolved_deps", [])
                               if 0 <= d < n and d != steps.index(s)]

    # ── 4. Cycle detection (Kahn's algorithm) ──
    in_degree = [len(s.get("_resolved_deps", [])) for s in steps]
    queue = [i for i, d in enumerate(in_degree) if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for i, s in enumerate(steps):
            if node in s.get("_resolved_deps", []):
                in_degree[i] -= 1
                if in_degree[i] == 0:
                    queue.append(i)

    if visited < n:
        # Cycle detected — LLM hallucination. Safe fallback: full sequential.
        return steps, 1

    # ── 5. BFS level assignment on verified DAG ──
    levels: dict[int, int] = {}
    for i, s in enumerate(steps):
        deps = s.get("_resolved_deps", [])
        if not deps:
            levels[i] = 0
        else:
            levels[i] = max(levels.get(d, 0) for d in deps) + 1

    from collections import Counter
    level_counts = Counter(levels.values())
    max_depth = max(level_counts.values()) if level_counts else 1

    return steps, max_depth


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

    # V6.1: Global Critic rate limiter — prevents RPM throttling when
    # parallel_depth > 1 and multiple branches complete simultaneously.
    _CRITIC_SEMAPHORE = None

    @classmethod
    def _get_critic_semaphore(cls):
        if cls._CRITIC_SEMAPHORE is None:
            import asyncio as _asyncio
            cls._CRITIC_SEMAPHORE = _asyncio.Semaphore(2)
        return cls._CRITIC_SEMAPHORE

    def __init__(
        self,
        planning_engine,
        orch_engine,
        critic_engine,
        adapter=None,  # GenerationAdapter for synthesis fallback
        bus=None,  # XRayBus for observability
        stream_llm=None,  # V7 Phase 1: raw LLM client for streaming synthesis
    ) -> None:
        self._planning = planning_engine
        self._orch = orch_engine
        self._critic = critic_engine
        self._adapter = adapter
        self._bus = bus
        self._stream_llm = stream_llm

    def _emit(self, stage: str, detail: str) -> None:
        if self._bus:
            self._bus.emit(stage, detail)

    def _emit_trace(self, node: TraceNode) -> None:
        if self._bus:
            self._bus.trace(node)

    # ── Public entry point ──────────────────────────────────────────

    def run(self, user: str, system: str, round_count: int = 0,
            trust: float = 0.5, e_t: float = 0.5,
            raw_drift: float = 0.0,
            clarity: float = 0.5,
            session_gain: float = 1.0,
            explore_bias: float = 0.0,
            compromise_bias: float = 0.0,
            stream_callback=None):  # V7 Phase 1: callable(token_str) per chunk
        """Execute Track C pipeline. Returns (response_text, output_capacity_mult).

        V5.3: Dual-sensor fusion — raw semantic drift (cross-round) + LLM clarity
        (in-round) jointly drive Planning branch_count via compute_dual_sensor_f.
        Critic threshold remains drift-only (preserves sensitivity to semantic
        space instability even during lucid topic switches).

        V6.2: session_gain from Wasserstein Bayesian smoothing adjusts Critic
        sensitivity — wide domain (gain>1) slightly relaxes, narrow (gain<1)
        slightly tightens. Max effect ±0.05 on θ.

        V6.3: explore_bias/compromise_bias from Path 1 meta_adapt state fission.
        explore_bias → Planning (wider search when intent is contradictory).
        compromise_bias → Critic (lower bar when capability is exhausted).
        P11: all signals are primitive snapshots locked at t₀. No mid-execution
        re-read of external state machines.

        Flow: Planning → {DIRECT: Synthesis} | {FULL_DAG: Orch → Critic → (retry?) → Synthesize}
        """
        t0 = time.time()
        lambda_hint = _lambda_hint(trust, e_t)

        # ── V5.3 Path 2: Dual-sensor fusion (drift ⊕ clarity) ──
        f_fused = compute_dual_sensor_f(raw_drift, clarity)
        # V6.3: explore_bias → Planning only (widen search for intent contradiction)
        f_planning = min(1.0, f_fused + explore_bias)
        branch_count = _path2_branch_count(f_planning)
        # Critic: drift-only (not fused) — keeps sensitivity to semantic space instability
        f_drift, g = _critic_factors(raw_drift, e_t)
        theta = _critic_threshold(f_drift, g, session_gain)
        # V6.3: compromise_bias → Critic only (relax standards for capability exhaustion)
        theta = max(0.50, theta - compromise_bias)
        output_mult = _dynamic_output_mult(branch_count, raw_drift)
        mode = "EXPLORE" if branch_count >= 3 else "BALANCED" if branch_count >= 2 else "EXPLOIT"
        # 🧊 = lucid suppression active: high clarity killed a drift spike
        suppression_mark = " 🧊" if clarity > 0.80 and raw_drift > 0.40 else ""
        # V6.3 bias marks
        if explore_bias > 0:
            suppression_mark += " 🔍"  # exploring: intent contradiction bias
        if compromise_bias > 0:
            suppression_mark += " 🤝"  # compromising: capability exhaustion bias
        self._emit("Path 2",
            f"{mode}{suppression_mark} (drift={raw_drift:.3f}, clarity={clarity:.2f}, "
            f"f={f_planning:.2f}, branches={branch_count}, θ={theta:.2f}, out×{output_mult:.1f})")
        # ── Phase 1: Planning ──
        self._emit("🔀 Track C Planning", "⏳ 动态规划中...")
        plan_result = safe_async_run(self._do_plan(
            user, system, lambda_hint, branch_count))
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
            if stream_callback:
                final = self._stream_and_collect(user, system, pad, stream_callback)
            else:
                final = self._synthesize(user, system, pad)
            self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
            return final, output_mult

        # ── FULL_DAG: build DAG topology, compute parallel_depth ──
        plan_with_deps, parallel_depth = _build_dag_and_depth(plan_result)
        self._emit("🔀 Track C Planning",
            f"FULL_DAG: {len(plan_result)} 步, DAG depth={parallel_depth} ({time.time()-t0:.1f}s)")

        # ── Phase 2: Orchestration → Critic (retry loop) ──
        pad = Scratchpad(max_retries=2)
        pad.plan = plan_with_deps

        while True:
            t_orch = time.time()
            self._emit("🔀 Track C Orch", f"⏳ 执行 {len(pad.plan)} 步 (depth={parallel_depth})...")
            pad.step_results = safe_async_run(
                self._do_orchestrate(pad.plan, user, system, pad.truncated_for_critic(),
                                     parallel_depth=parallel_depth)
            )
            orch_elapsed = time.time() - t_orch
            self._emit("🔀 Track C Orch", f"完成 {len(pad.step_results)} 步 ({orch_elapsed:.1f}s)")

            # ── Phase 3: Critic (rate-limited) ──
            t_critic = time.time()
            self._emit("🔀 Track C Critic", "⏳ 评估中...")
            score, detail = safe_async_run(
                self._do_critique(user, pad.truncated_for_critic(), theta)
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
        if stream_callback:
            final = self._stream_and_collect(user, system, pad, stream_callback)
        else:
            final = self._synthesize(user, system, pad)
        self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
        return final, output_mult

    # ── Async engine wrappers ───────────────────────────────────────

    async def _do_plan(self, user: str, system: str, lambda_hint: str = "",
                       branch_count: int = 1, retry: bool = False) -> list[dict]:
        """V6: Complexity-routing Planning with lambda + Path 2 gain scheduling.

        LLM chooses between DIRECT (shallow) and FULL_DAG (deep).
        When branch_count > 1, FULL_DAG generates parallel exploration paths
        from different perspectives — each a distinct hypothesis.
        """
        from engines.planning.interface import PlanningContext
        from core.contracts.streaming_protocol import PaceConfig
        import os

        state_hint = f"\n\n{lambda_hint}" if lambda_hint else ""
        min_steps = int(os.environ.get("MIN_PLAN_STEPS", MIN_PLAN_STEPS))

        if branch_count > 1:
            branch_hint = (
                f"生成 {branch_count} 条从不同角度切入的探索路径。"
                f"每条路径代表一种截然不同的假设或视角，避免内容重复。"
            )
        else:
            branch_hint = ""

        if not retry:
            goal = (
                f"{user}\n\n"
                f"[规划指令] 根据用户意图的复杂度选择输出格式：\n\n"
                f"如果用户意图是格式微调、简单追问、闲聊或延续已有内容"
                f"（如'字多一点'、'继续'、'好的'），输出 DIRECT：\n"
                f'  {{"type": "DIRECT", "action": "直接基于上下文生成回复"}}\n\n'
                f"如果用户意图需要新增知识、多步推理或工具调用，输出 FULL_DAG：\n"
                f'  {{"type": "FULL_DAG", "steps": [{{"prompt": "...", "tool": "", '
                f'"produces": "标签(可选)", "needs": "标签(可选)", '
                f'"intent_type": "EXECUTABLE|PSEUDOCODE|DEMONSTRATION", '
                f'"test_cases": [{{"input": "...", "expected": ...}}]}}, ...]}}\n'
                f"  （拆解为 {min_steps}-5 步，每步包含 prompt 和 tool 字段。\n"
                f"  可选字段 produces: 本步骤产出的数据标签（如 'paper_list', 'code_v1'）。\n"
                f"  可选字段 needs: 本步骤需要的前序数据标签。标签命名必须一致。\n"
                f"  V7.2 Test-First 契约: 如果步骤涉及代码生成(tool=sandbox_python)，\n"
                f"  必须先声明 test_cases。每个 test case 包含 input(输入参数) 和\n"
                f"  expected(期望输出)。断言格式必须严格使用特殊定界符:\n"
                f'  assert func(input) == expected, f"⊢EXPECTED⊢{{expected}}⊢ACTUAL⊢{{actual}}"\n'
                f"  test_cases 只能包含 assert 语句。禁止 import/class/for/while/I/O。\n"
                f"  可选字段 intent_type: EXECUTABLE(需物理验证)|PSEUDOCODE(仅语法)|DEMONSTRATION(纯展示)。\n"
                f"在 JSON 之前用 <!-- reasoning --> 注释简要说明选择理由。）"
                f"{' ' + branch_hint if branch_hint else ''}"
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
                # V6.1: Extract structural fields (produces/needs/depends_on)
                _extract_step_fields(text, step)
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
        parallel_depth: int = 1,
    ) -> list[str]:
        """Execute plan steps via OrchestrationEngine — V6.1 DAG-aware concurrency.

        parallel_depth from DAG topology: 1=sequential, 2+=Semaphore-limited parallel.
        Steps with unresolved dependencies are serialized by the Orch engine.
        """
        import asyncio as _asyncio
        tasks = [self._orchestrate_one(step, user, system, prev_context,
                                       parallel_depth=parallel_depth)
                 for step in plan]
        raw = await _asyncio.gather(*tasks, return_exceptions=True)
        # Safety clamp: explicit error marking for downstream Critic/Synth
        return [r if isinstance(r, str) else f"[STEP_FAILED: {type(r).__name__}: {r}]" for r in raw]

    async def _orchestrate_one(
        self, step: dict, user: str, system: str, prev_context: str,
        parallel_depth: int = 1,
        budget_slice: int = 1,            # V8 groundwork: per-Loop budget
        retry_policy=None,                # V8 groundwork: formal Loop injection point
    ) -> str:
        """Execute a single orchestration branch. V6.1: DAG-aware concurrency.

        V8 groundwork:
          budget_slice: per-Loop budget units for multi-Agent budget boundaries.
          retry_policy: optional callable(step, attempt_count) → bool.
            None = default retry behavior. V8 replaces with formal Loop 2-morphism.
        """
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
            parallel_depth=parallel_depth,
            metadata={"goal": user, "system_prompt": system, "context": prev_context},
        )
        items = await _collect(self._orch.orchestrate(
            ctx, deadline=60.0, pace_config=PaceConfig(),
        ))
        return "".join(item.delta for item in items)

    async def _do_critique(self, user: str, result_text: str,
                           theta: float = 0.75) -> tuple[float, str]:
        """Evaluate results via CriticEngine. V6: theta from Path 2 gain schedule."""
        from engines.critic.interface import CriticContext
        from core.contracts.streaming_protocol import PaceConfig

        theta_hint = ""
        if theta < 0.75:
            theta_hint = (
                f"\n[SYSTEM] High uncertainty mode. Lower your passing threshold "
                f"to {theta:.2f} — prioritize recall over precision. "
                f"Accept results that are directionally useful even if imperfect."
            )

        ctx = CriticContext(
            plan_output=f"Goal: {user}\n\nResults: {result_text}{theta_hint}",
            metadata={"goal": user, "v6.critic_theta": theta},
        )
        # V6.1: Critic rate limiter — max 2 concurrent Critic LLM calls
        async with self._get_critic_semaphore():
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

    def _build_synthesis_prompt(self, user: str, system: str, pad: Scratchpad) -> str:
        """Build the synthesis prompt. Shared by _synthesize and _synthesize_stream."""
        parts = [
            f"用户问题: {user}",
            f"分析结果: {pad.truncated_for_critic()}",
            f"Critic评分: {pad.critic_score:.2f} — {pad.critic_detail}",
        ]
        if pad.retry_count > 0:
            parts.append(f"(经过 {pad.retry_count} 次重试后通过)")
        return f"{system}\n\n" + "\n".join(parts) + "\n请基于以上内容生成最终回复。"

    def _synthesize(self, user: str, system: str, pad: Scratchpad) -> str:
        """Build final response from all step results + critique.

        Uses the injected GenerationAdapter for LLM synthesis.
        """
        prompt = self._build_synthesis_prompt(user, system, pad)

        if self._adapter:
            from core.contracts import GenerationResult
            result = safe_async_run(self._adapter.generate(prompt, [], {}))
            if isinstance(result, GenerationResult):
                return result.text
            return str(result)
        # Last resort: return concatenated results
        return "\n\n".join(pad.step_results[-3:])

    def _stream_and_collect(self, user: str, system: str, pad: Scratchpad,
                            callback) -> str:
        """Stream synthesis tokens through callback, return full text."""
        parts: list[str] = []
        for chunk in self._synthesize_stream(user, system, pad):
            parts.append(chunk)
            try:
                callback(chunk)
            except Exception:
                pass  # Display failure must not crash synthesis
        return "".join(parts)

    def _synthesize_stream(self, user: str, system: str, pad: Scratchpad):
        """V7 Phase 1: Stream synthesis tokens via raw LLM client.

        Yields str chunks. Falls back to non-streaming _synthesize if
        no stream_llm is available.
        """
        if self._stream_llm is None:
            yield self._synthesize(user, system, pad)
            return

        prompt = self._build_synthesis_prompt(user, system, pad)
        try:
            for chunk in self._stream_llm.generate_stream(prompt):
                yield chunk
        except Exception:
            # Fallback: generate synchronously
            yield self._synthesize(user, system, pad)
