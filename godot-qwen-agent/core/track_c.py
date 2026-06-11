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


# ── V7.2 Phase 1: Code extraction ────────────────────────────────────

def _extract_code(text: str) -> str:
    """π: S → C — extract Python code block from Orch synthesis output.

    Tries: 1) fenced block, 2) def/class block, 3) any text that looks like code.
    Returns empty string if no code found (→ FORMAT_ERROR, no budget).
    """
    import re
    # Try fenced code block (with or without closing fence)
    m = re.search(r'```(?:python|py)?\s*\n(.*?)(?:```|$)', text, re.DOTALL)
    if m and len(m.group(1).strip()) >= 10:
        return m.group(1).strip()
    # Fallback: find def/class with body (any indented continuation lines)
    m = re.search(r'((?:def|class)\s+\w+[^\n]*\n(?:\s{2,}[^\n]+\n?)+)', text)
    if m:
        return m.group(1).strip()
    # Last resort: any def/class line with trailing content
    m = re.search(r'((?:def|class)\s+\w+[^\n]+\n.{10,}?(?:\n\n|\n$|$))', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return ""


def _format_retry_hint(hint: str) -> str:
    """Wrap ErrorMapper fix_hint as a Planning constraint."""
    if not hint:
        return ""
    return f"\n[PHYSICAL CONSTRAINT] Previous code failed. Fix: {hint}"


def _signature_lock_hint() -> str:
    """Step 4.5: Prompt-level interface isomorphism constraint."""
    return (
        "\n[PHYSICAL CONSTRAINT] Retry rule: fix ONLY the internal logic. "
        "Keep function name, parameter list, and return type EXACTLY the same."
    )


# ── V7.5 P26: Buffer overflow guard for streaming physical verification ──

class BufferOverflowError(Exception):
    """Circuit breaker: streaming buffer exceeded hard limit.

    Raised when physical verification buffer exceeds MAX_BUFFER_TOKENS.
    Triggers semantic escape — same treatment as TIMEOUT (Patch 2).
    """
    pass

MAX_BUFFER_TOKENS = 2048  # ~4KB memory ceiling, NIST IR 8269 §4.3 compliant


# ── V5.1: Lambda Gain Scheduling ───────────────────────────────────

def _lambda_hint(trust: float, e_t: float) -> str:
    """V7.8: Continuous lambda hint — trust and e(t) values embedded in prompt text.

    Instead of discrete bins, the continuous values {trust:.0%} and {e_t:.0%}
    are injected directly into the prompt. The LLM sees T=0.31 and T=0.54 as
    different numbers, producing genuinely continuous behavioral modulation.
    """
    parts = []

    # ── Autonomy gradient: trust-driven risk aversion ──
    if trust < 0.15:
        parts.append(
            "[SYSTEM STATE] Trust critically low ({:.0%}). "
            "Be extremely conservative — use DIRECT only for trivial single-word "
            "replies or explicit goodbyes. Default to FULL_DAG for everything else.".format(trust)
        )
    elif trust < 0.30:
        parts.append(
            "[SYSTEM STATE] Trust below comfort zone ({:.0%}). "
            "Lean conservative — DIRECT only for clear format adjustments. "
            "Borderline cases -> FULL_DAG.".format(trust)
        )
    elif trust < 0.70:
        # Continuous autonomy: trust value embedded without hard directive
        if trust < 0.50:
            parts.append(
                "[SYSTEM STATE] Moderate trust ({:.0%}). "
                "Use your judgment — no forced conservative or liberal bias.".format(trust)
            )
        else:
            parts.append(
                "[SYSTEM STATE] Trust building ({:.0%}). "
                "You may optimize for efficiency on clear, simple tasks.".format(trust)
            )
    else:
        parts.append(
            "[SYSTEM STATE] High trust ({:.0%}), stable relationship. "
            "Full autonomy. DIRECT is encouraged for simple tasks.".format(trust)
        )

    # ── Entropy gradient: e(t)-driven uncertainty expression ──
    if e_t > 0.65:
        parts.append(
            "[UNCERTAINTY] Tracking error elevated ({:.0%}). "
            "If you are unsure about any point, explicitly state your confidence level.".format(e_t)
        )
    elif e_t > 0.50:
        parts.append(
            "[UNCERTAINTY] Moderate uncertainty ({:.0%}). "
            "Acknowledge ambiguity where it exists, but don't hedge on clear points.".format(e_t)
        )

    return "\n".join(parts) if parts else ""


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


# ── V7.3: Resistance-field DAG ─────────────────────────────────────────

RESISTANCE_WEIGHTS: dict[str, float] = {
    # Pure semantic (zero side effects)
    "":                            0.0,   # no tool — text generation only
    "search_web":                  0.1,   # read-only, public data
    "rag_search":                  0.1,   # read-only, local data
    # Code execution (memory-isolated)
    "sandbox_python":              2.0,
    # MCP: filesystem
    "mcp__filesystem_read":        5.0,   # read-only, real files
    "mcp__filesystem_write":      50.0,   # WRITE to real filesystem — high risk
    "mcp__filesystem_delete":    100.0,   # DELETE — extreme risk
    # MCP: database
    "mcp__database_query":        30.0,   # SELECT only
    "mcp__database_write":       100.0,   # INSERT/UPDATE/DELETE
    # MCP: network
    "mcp__network_fetch":         10.0,   # outbound HTTP
    "mcp__network_api":           40.0,   # authenticated API calls
}


def _resistance_weight(tool_name: str) -> float:
    """Look up resistance weight with graceful degradation."""
    if not tool_name:
        return 0.0
    return RESISTANCE_WEIGHTS.get(tool_name, 0.0)


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


def _dep_depth(step: dict, steps: list[dict]) -> int:
    """Dependency depth — used to break ties in resistance-equivalent tasks.

    Plateau decomposition: when |R(u) - R(v)| < epsilon within the same
    BFS fiber, secondary sort by dependency depth ensures Morse-Smale
    well-definedness on degenerate fibers.
    """
    deps = step.get("_resolved_deps", [])
    if not deps:
        return 0
    return 1 + max(_dep_depth_idx(d, steps) for d in deps)


def _dep_depth_idx(idx: int, steps: list[dict]) -> int:
    """Resolve dependency depth from a resolved index."""
    if 0 <= idx < len(steps):
        return _dep_depth(steps[idx], steps)
    return 0


def _build_dag_and_depth(steps: list[dict],
                         resistance_weights: dict[str, float] | None = None,
                         emit=None  # optional X-Ray callback for topological diagnostics
                         ) -> tuple[list[dict], int, float, dict]:
    """Build DAG from step tags + indices, compute maximal safe parallel depth.

    V6.1: Kahn cycle detection + BFS level assignment.
    V7.3: Resistance-field stable sort — within each BFS fiber, reads are
          sorted by resistance ascending; writes keep original Planning order
          (causality preservation — Red-Team #3).

    Resolution order:
      1. Match produces/needs tags (deterministic string equality)
      2. Fall back to depends_on indices for unmatched needs
      3. Resolve transitive dependencies for tags

    Returns (steps_with_deps, parallel_depth, max_resistance).
    parallel_depth = 1 if cycle detected (graph theory: no topological order exists).
    """
    n = len(steps)
    rw = resistance_weights or {}

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
        return steps, 1, 0.0, {}

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

    # ── 6. V7.3: Resistance-field stable sort per BFS fiber ──
    # Red-Team #3: Causality preservation — writes keep original order.
    # Reads are sorted by resistance ascending. Merge: reads → writes.
    # Mathematical: sheaf R defined only on V_read; V_write is discrete.
    if rw:
        level_groups: dict[int, list[dict]] = {}
        for i, s in enumerate(steps):
            level_groups.setdefault(levels.get(i, 0), []).append(s)

        for level, level_steps in level_groups.items():
            # Split fiber into writes (causal) and reads (resistance-sortable)
            writes = [s for s in level_steps
                      if s.get("tool", "").endswith(
                          ("_write", "_delete", "_insert", "_update"))]
            reads = [s for s in level_steps if s not in writes]

            # Reads: sort by resistance ascending (gradient descent on potential w).
            # Secondary sort by dependency depth for resistance ties (plateau decomposition
            # — preserves Morse-Smale well-definedness on degenerate fibers).
            reads.sort(key=lambda s: (
                rw.get(s.get("tool", ""), 0.0),
                _dep_depth(s, steps),
            ))

            # Merge: reads first (scout), writes last (commit)
            level_groups[level] = reads + writes

        # Reconstruct steps list from sorted level groups (in level order)
        sorted_steps: list[dict] = []
        for level in sorted(level_groups.keys()):
            sorted_steps.extend(level_groups[level])
        steps[:] = sorted_steps

    # ── 6.5: Potential monotonicity assertion (Morse necessary condition) ──
    # For all dependency edges u->v: R(u) <= R(v) + epsilon.
    # A violation means a higher-resistance task is a prerequisite of a
    # lower-resistance one — the Morse function has a local maximum.
    if rw:
        for s in steps:
            for dep_idx in s.get("_resolved_deps", []):
                if 0 <= dep_idx < len(steps):
                    r_u = rw.get(steps[dep_idx].get("tool", ""), 0.0)
                    r_v = rw.get(s.get("tool", ""), 0.0)
                    if r_u > r_v + 1.0:  # epsilon = 1.0 tolerance
                        msg = (
                            f"R inversion: "
                            f"R({steps[dep_idx].get('tool','?')})={r_u:.0f} > "
                            f"R({s.get('tool','?')})={r_v:.0f} on edge "
                            f"{dep_idx}->{steps.index(s)} — "
                            f"Morse gradient violated (P24)"
                        )
                        if emit:
                            emit("🔣 拓扑诊断", msg)
                        else:
                            import sys
                            print(f"[TOPOLOGY WARN] {msg}", file=sys.stderr)

    # ── 7. Max resistance + homotopy classes ──
    max_resistance = max(
        (rw.get(s.get("tool", ""), 0.0) for s in steps),
        default=0.0)

    # ── 7.5: BFS level -> homotopy class explicit mapping ──
    homotopy_classes: dict[int, dict] = {}
    level_groups_final: dict[int, list[dict]] = {}
    for s in steps:
        lev = levels.get(steps.index(s), 0)
        level_groups_final.setdefault(lev, []).append(s)
    for level in sorted(level_groups_final.keys()):
        tasks = level_groups_final[level]
        resistances = [rw.get(t.get("tool", ""), 0.0) for t in tasks]
        homotopy_classes[level] = {
            "tasks": tasks,
            "resistance_range": (
                min(resistances) if resistances else 0.0,
                max(resistances) if resistances else 0.0),
            "count": len(tasks),
        }

    return steps, max_depth, max_resistance, homotopy_classes


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
        tool_engine=None,  # V8.4: ToolEngine for real tool dispatch (4th engine)
    ) -> None:
        self._planning = planning_engine
        self._orch = orch_engine
        self._critic = critic_engine
        self._adapter = adapter
        self._bus = bus
        self._stream_llm = stream_llm
        self._tool_engine = tool_engine
        self._tool_results: list[dict] = []  # V8.4: accumulated per-run

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
            planning_hint: str = "",   # V7.9: Planning-domain contract context
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
        self._tool_results.clear()  # V8.4: reset per-run
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
            user, system, lambda_hint, planning_hint, branch_count))
        is_direct = plan_result and len(plan_result) == 1 and plan_result[0].get("type") == "DIRECT"

        self._emit_trace(TraceNode(
            node_id=f"c_plan_{round_count}", name="TrackC_Planning",
            node_type="agent", status=TraceStatus.SUCCESS,
            metadata={"elapsed_ms": (time.time() - t0) * 1000,
                      "steps": len(plan_result),
                      "mode": "DIRECT" if is_direct else "FULL_DAG"},
        ))

        # ── V5.1: DIRECT short-circuit ──
        # Safety gate: block DIRECT when clarity is critically low AND
        # the user shows significant emotional signal. Low clarity means
        # the Planning engine can't reliably judge if the user's input is
        # a simple continuation ("好的") or a complex grievance ("你出问题了").
        # Forcing FULL_DAG ensures the Critic evaluates the response before
        # it reaches the user — preventing recursive self-diagnosis spirals.
        # V8.4: DIRECT safety gate — force FULL_DAG when tools exist and
        # request is not clearly a trivial social/continuation message.
        # DIRECT bypasses ToolEngine entirely — tool-capable requests must
        # go through FULL_DAG or the LLM will hallucinate [TOOL:xxx] in text.
        if is_direct and self._tool_engine is not None:
            t = user.strip()
            is_trivial = (len(t) <= 10 or
                          any(t.startswith(w) for w in
                              ("你好", "拜拜", "再见", "好的", "嗯", "哦", "行", "ok",
                               "谢谢", "继续", "hi", "hello", "bye")))
            if not is_trivial:
                self._emit("🔀 Track C Planning",
                    "DIRECT overridden — tools available, forcing FULL_DAG")
                is_direct = False
                plan_result = [
                    {"prompt": f"{user}", "tool": "",
                     "produces": "", "needs": "", "test_cases": []}]

        if is_direct and clarity < 0.20:
            self._emit("🔀 Track C Planning",
                f"DIRECT blocked — clarity={clarity:.2f} too low, "
                f"forcing FULL_DAG for safety")
            is_direct = False
            # Synthesize a minimal plan for the Critic to evaluate
            plan_result = [
                {"prompt": f"用户反馈: {user}", "tool": "",
                 "intent_type": "DEMONSTRATION"}
            ]

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
        plan_with_deps, parallel_depth, max_resistance, homotopy_classes = (
            _build_dag_and_depth(plan_result, RESISTANCE_WEIGHTS,
                                 emit=self._emit))
        self._emit("🔀 Track C Planning",
            f"FULL_DAG: {len(plan_result)} 步, depth={parallel_depth}"
            f"{', maxR=' + str(max_resistance) if max_resistance > 0 else ''}"
            f"{', H-classes=' + str(len(homotopy_classes)) if homotopy_classes else ''}"
            f" ({time.time()-t0:.1f}s)")

        # ── Verify fiber cross-section bounds (P25) ──
        for hc_level, hc in homotopy_classes.items():
            if hc["count"] > parallel_depth:
                self._emit("🔀 Track C Planning",
                    f"H_{hc_level} oversubscribed "
                    f"(|H|={hc['count']} > depth={parallel_depth}, "
                    f"R in {hc['resistance_range']}) — auto-batching")

        # ── V7.2 Phase 1: PhysicalBudget (DAG上的联络) ──
        from core.critic.dual_track import PhysicalBudget as _PhysicalBudget
        phys_budget = _PhysicalBudget(max_budget=5.0)

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

        # ── V7.2 Phase 2: Hard physical retry loop around Synthesis ──
        phys_retries = 0
        max_phys_retries = 2
        accumulated_hints: list[str] = []  # Patch 1: integral term
        augmented_tc: list[dict] = []       # V7.3: sigma-monotone test cases
        final = ""
        chunks_buffer: list[str] = []       # Moved outside loop for post-retry scope

        while phys_retries <= max_phys_retries:
            if phys_retries == 0:
                self._emit("🔀 Track C 合成", "⏳ 合成最终回复...")
            else:
                self._emit("🔀 Track C 合成",
                    f"⏳ 物理 Retry ({phys_retries}/{max_phys_retries})...")

            # Patch 3: annealing — final attempt gets explicit critical tag
            constraints = (
                accumulated_hints +
                ["[CRITICAL] 最后一次修正。严格按以上约束修改，不要引入任何其他变更。"]
                if phys_retries >= max_phys_retries and accumulated_hints
                else accumulated_hints
            ) if accumulated_hints else None

            # V7.3: if we have augmented test_cases, inject them as constraints
            if augmented_tc:
                tc_summary = "; ".join(
                    f"test[{i}]: {t.get('input','?')} -> {t.get('expected','?')}"
                    for i, t in enumerate(augmented_tc[:3])
                )
                tc_hint = (
                    f"[PHYSICAL CONSTRAINT] Retry must pass these additional "
                    f"boundary tests: {tc_summary}"
                )
                if constraints:
                    constraints.append(tc_hint)
                else:
                    constraints = [tc_hint]

            # ── V7.5 P26: Buffered streaming for physical hard-gate ──
            # Non-streaming: synthesize in-process, verify, return.
            # Streaming: buffer tokens, verify, flush only after PASS.
            # This prevents broken code from reaching the user before verification
            # (NIST AI 100-2e2 §5.1: physical verification must complete before output).
            chunks_buffer.clear()  # Reset for this retry iteration

            if stream_callback:
                def _buffer_cb(token: str) -> None:
                    if len(chunks_buffer) < MAX_BUFFER_TOKENS:
                        chunks_buffer.append(token)
                    else:
                        raise BufferOverflowError(
                            f"Physical verification buffer exceeded "
                            f"{MAX_BUFFER_TOKENS} tokens — "
                            f"likely infinite-loop code generation"
                        )
                try:
                    final = self._stream_and_collect(
                        user, system, pad, _buffer_cb, constraints)
                except BufferOverflowError:
                    self._emit("🔧 物理验证",
                        "BUFFER OVERFLOW → semantic escape")
                    final += (
                        "\n\n[⚠ PHYSICAL BUFFER OVERFLOW: "
                        "代码生成可能包含死循环, 已中断]"
                    )
                    break
            else:
                final = self._synthesize(user, system, pad, constraints)

            # ── V7.5: DualTrackCritic — unified semantic+physical gate ──
            # The missing link: semantic score (from CriticEngine) and physical
            # result (from SandboxExecutor) combine via multiplicative gating.
            # θ AND q — not additive, not veto. The verdict decides next action.
            # ── Check if any step actually uses a physical tool ──
            _has_sandbox = any(
                s.get("tool", "") == "sandbox_python" for s in pad.plan)
            code = _extract_code(final) if _has_sandbox else ""
            from core.execution.sandbox import SandboxExecutor, PhysicalState
            from core.execution.error_mapper import ErrorMapper
            from core.critic.dual_track import DualTrackCritic, CriticVerdict, CriticDecision

            dual_critic = DualTrackCritic()

            if not code or len(code) < 10:
                # No code to verify → semantic-only gate.
                # If semantic score is already low, the Critic retry loop
                # before Synthesis already exhausted its attempts. Continuing
                # the physical retry loop won't fix a semantic problem — break.
                decision = dual_critic.evaluate(
                    pad.critic_score, theta,
                    physical_result=None, intent_type="DEMONSTRATION")
                self._emit("🔧 双轨验证",
                    f"semantic-only: score={pad.critic_score:.2f} θ={theta:.2f} → {decision.verdict.value}")
                if decision.verdict == CriticVerdict.RETRY:
                    # Semantic retries already exhausted — force accept
                    self._emit("🔧 双轨验证",
                        "semantic RETRY in no-code path — retries exhausted, accept")
                    decision = CriticDecision(
                        verdict=CriticVerdict.PASS,
                        semantic_score=pad.critic_score,
                        reason="semantic retry exhausted (no physical check)")
                # phys_result never assigned in this branch — skip physical handlers
                phys_result = None
            else:
                # ── Smooth budget gate (Morse-Bott) ──
                resistance_factor = 1.0 + 0.2 * max(0.0, (max_resistance - 10.0) / 10.0)
                effective_cost = max(1.0, min(3.0, resistance_factor))
                if phys_budget.remaining < effective_cost:
                    self._emit("🔧 物理验证",
                        f"REJECT: budget {phys_budget.remaining:.1f} < "
                        f"effective_cost {effective_cost:.1f} (R={max_resistance:.0f})")
                    final += (
                        f"\n\n[⚠ PHYSICAL BUDGET: 高阻力操作 (R={max_resistance:.0f}) "
                        f"需要 {effective_cost:.1f} 预算, 剩余 {phys_budget.remaining:.1f}]"
                    )
                    if stream_callback and chunks_buffer:
                        for token in chunks_buffer:
                            try: stream_callback(token)
                            except Exception: pass
                    break

                # ── Physical execution ──
                executor = SandboxExecutor()
                phys_result = executor.run(
                    code, augmented_tc if augmented_tc else None,
                    "EXECUTABLE", phys_budget)

                # ── Semantic + Physical multiplicative gate ──
                mapper = ErrorMapper()
                mapping = mapper.map(phys_result, code) if phys_result.state != PhysicalState.PASS else None
                fix_hint = mapping.fix_hint if mapping else ""

                decision = dual_critic.evaluate(
                    semantic_score=pad.critic_score,
                    theta=theta,
                    physical_result=phys_result,
                    intent_type="EXECUTABLE",
                    fix_hint=fix_hint,
                )
                self._emit("🔧 双轨验证",
                    f"sem={pad.critic_score:.2f} θ={theta:.2f} phys={phys_result.state.value} "
                    f"→ {decision.verdict.value} ({decision.reason[:50]})")

            # ── Act on dual-track verdict ──
            if decision.verdict == CriticVerdict.PASS:
                if phys_retries > 0:
                    self._emit("🔧 双轨验证",
                        f"PASS after {phys_retries} retries, "
                        f"budget={phys_budget.remaining:.1f}"
                        + (f", aug_tc={len(augmented_tc)}" if augmented_tc else ""))
                # Flush buffered tokens to user
                if stream_callback and chunks_buffer:
                    for token in chunks_buffer:
                        try: stream_callback(token)
                        except Exception: pass
                break

            if decision.verdict == CriticVerdict.FAIL_FATAL:
                self._emit("🔧 双轨验证",
                    f"FAIL_FATAL: {decision.reason} — Rigid Contract #5, aborting")
                final += (
                    f"\n\n[⛔ PHYSICAL FATAL: {decision.reason}. "
                    f"刚性契约 #5 — 无条件终止.]"
                )
                if stream_callback and chunks_buffer:
                    for token in chunks_buffer:
                        try: stream_callback(token)
                        except Exception: pass
                break

            # ── CriticVerdict.RETRY: only physical failures count against budget ──
            # Semantic retries (low critic score, no physical issue) don't
            # consume physical retry quota — they bounce back to Synthesis
            # with accumulated constraints.
            is_physical_fail = "physical" in decision.reason.lower()
            if is_physical_fail:
                phys_retries += 1

            # Patch 1: integral term — accumulate all historical constraints
            accumulated_hints.append(
                f"PHYSICAL RETRY ({phys_retries}/{max_phys_retries}): "
                f"{decision.fix_hint or decision.reason}"
                f" — 修复时必须保持函数名、参数、返回类型完全不变，只改内部逻辑。"
            )

            # V7.3: sigma-monotone test case augmentation
            # (only when physical execution actually ran)
            if phys_result is not None and phys_result.test_results:
                from core.execution.error_mapper import augment_test_cases
                new_tc = augment_test_cases(
                    mapping.error_type if mapping else "",
                    failed_test=phys_result.test_results[0] if phys_result.test_results else None,
                )
                if new_tc:
                    augmented_tc.extend(new_tc)
                    self._emit("🔧 双轨验证",
                        f"augmented {len(new_tc)} boundary tests (total={len(augmented_tc)})")

            self._emit("🔧 双轨验证",
                f"RETRY ({phys_retries}/{max_phys_retries}): {decision.reason[:80]}")

        # ── Post-retry: flush buffer if streaming (max retries exhausted) ──
        if stream_callback and chunks_buffer and phys_retries >= max_phys_retries:
            final += "\n\n[⚠ PHYSICAL RETRIES EXHAUSTED: 代码可能仍有问题]"
            for token in chunks_buffer:
                try:
                    stream_callback(token)
                except Exception:
                    pass

        self._emit("🔀 Track C 合成", f"完成 ({time.time()-t0:.1f}s)")
        return final, output_mult

    # ── Async engine wrappers ───────────────────────────────────────

    async def _do_plan(self, user: str, system: str, lambda_hint: str = "",
                       planning_hint: str = "",
                       branch_count: int = 1, retry: bool = False) -> list[dict]:
        """V7.9: Complexity-routing Planning with lambda + contract context.

        LLM chooses between DIRECT (shallow) and FULL_DAG (deep).
        When branch_count > 1, FULL_DAG generates parallel exploration paths
        from different perspectives — each a distinct hypothesis.

        planning_hint carries Planning-domain contract context (semantic
        confidence, response length target). Built by REPL layer — Track C
        knows nothing about Blueprint or trust.
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
                f'  {{"type": "DIRECT", "action": "直接基于上下文生成回复"}}\n'
                f"  DIRECT 模式下禁止在回复中写 [TOOL:xxx]——工具调用只能通过 FULL_DAG 完成。\n\n"
                f"如果用户意图需要新增知识、多步推理或工具调用，输出 FULL_DAG：\n"
                f'  {{"type": "FULL_DAG", "steps": [{{"prompt": "...", "tool": "", '
                f'"produces": "标签(可选)", "needs": "标签(可选)", '
                f'"intent_type": "EXECUTABLE|PSEUDOCODE|DEMONSTRATION", '
                f'"test_cases": [{{"input": "...", "expected": ...}}]}}, ...]}}\n'
                f"  （拆解为 {min_steps}-5 步，每步包含 prompt 和 tool 字段。\n"
                f"  可选字段 produces: 本步骤产出的数据标签（如 'paper_list', 'code_v1'）。\n"
                f"  可选字段 needs: 本步骤需要的前序数据标签。标签命名必须一致。\n"
                f"  V7.2: 如果步骤涉及代码生成，必须设置 tool=\"sandbox_python\"\n"
                f"  且 intent_type=\"EXECUTABLE\"，并先声明 test_cases。\n"
                f"  每个 test case 包含 input(输入参数) 和 expected(期望输出)。\n"
                f"  断言格式必须严格使用特殊定界符:\n"
                f'  assert func(input) == expected, f"⊢EXPECTED⊢{{expected}}⊢ACTUAL⊢{{actual}}"\n'
                f"  test_cases 只能包含 assert 语句。禁止 import/class/for/while/I/O。\n"
                f"  可选字段 intent_type: EXECUTABLE(需物理验证)|PSEUDOCODE(仅语法)|DEMONSTRATION(纯展示)。\n"
                f"在 JSON 之前用 <!-- reasoning --> 注释简要说明选择理由。）"
                f"{' ' + branch_hint if branch_hint else ''}"
                f"{self._build_tools_hint()}"
                f"{state_hint}"
                f"{chr(10) + chr(10) + planning_hint if planning_hint else ''}"
            )
        else:
            goal = (
                f"{user}\n\n"
                f"[约束: 必须拆解为至少 {min_steps} 个独立子任务。"
                f"每步包含 prompt 和 tool 字段。返回 JSON 数组。]"
                f"{chr(10) + chr(10) + planning_hint if planning_hint else ''}"
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
        """Execute plan steps via OrchestrationEngine — DAG-aware concurrency.

        Semaphore(parallel_depth) enforces fiber cross-section bound (P25):
        at most parallel_depth tasks run concurrently within each BFS level.
        This is not cosmetic — it's the topological constraint that prevents
        resource oversubscription across homotopy classes.
        """
        import asyncio as _asyncio
        _sem = _asyncio.Semaphore(parallel_depth)

        async def _run_gated(step):
            async with _sem:
                return await self._orchestrate_one(
                    step, user, system, prev_context,
                    parallel_depth=parallel_depth)

        tasks = [_run_gated(s) for s in plan]
        raw = await _asyncio.gather(*tasks, return_exceptions=True)
        # Safety clamp: explicit error marking for downstream Critic/Synth
        return [r if isinstance(r, str) else f"[STEP_FAILED: {type(r).__name__}: {r}]" for r in raw]

    async def _orchestrate_one(
        self, step: dict, user: str, system: str, prev_context: str,
        parallel_depth: int = 1,
        budget_slice: int = 1,            # V8 groundwork: per-Loop budget
        retry_policy=None,                # V8 groundwork: formal Loop injection point
    ) -> str:
        """Execute a single orchestration branch.

        V6.1: DAG-aware concurrency.
        V7.2: SandboxExecutor verification in Synthesis hard retry loop.
        V7.3: Phi functor — post-hoc physical verification for ALL physical tools.
        V8 groundwork: budget_slice + retry_policy injection points.
        """
        from engines.orchestration.interface import OrchestrationContext, BranchSpec
        from engines.orchestration.identity import OrchestratorIdentity
        from core.contracts.streaming_protocol import PaceConfig

        branch = BranchSpec(
            name=step.get("prompt", str(step))[:60],
            pool=step.get("tool", "default"),
            items=1,
        )
        # ── V8.4: Real tool dispatch via ToolEngine (4th engine) ──
        tool_name = step.get("tool", "")
        if tool_name and tool_name != "default" and self._tool_engine is not None:
            try:
                from engines.tool.interface import ToolContext
                items = await _collect(self._tool_engine.execute(
                    ToolContext(tool_name=tool_name, parameters=step),
                    deadline=30.0, pace_config=PaceConfig(),
                ))
                result = "".join(item.delta for item in items)
                if items:
                    tc = items[-1].trace_context if hasattr(items[-1], 'trace_context') else {}
                    self._tool_results.append({
                        "success": tc.get("tool.success", False),
                        "tool_name": tool_name,
                        "semantic_summary": tc.get("tool.semantic_summary", ""),
                        "latency_ms": tc.get("tool.elapsed_ms", 0),
                    })
                return result
            except Exception:
                pass  # Fall through to LLM simulation on ToolEngine failure

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
        result = "".join(item.delta for item in items)

        # ── V7.3: Phi functor — physical verification for side-effect tools ──
        if tool_name and tool_name != "default":
            result = self._verify_physical_tool(tool_name, result)

        return result

    def _build_tools_hint(self) -> str:
        """V8.4: List available tools in planning prompt.

        Strongly biases Planning toward FULL_DAG when a tool-relevant
        request is detected. Without this, the LLM defaults to DIRECT
        for simple-sounding tool requests ('write hello world').
        """
        if not self._tool_engine:
            return ""
        try:
            from core.contracts import COMPONENT_REGISTRY
            tools = COMPONENT_REGISTRY.list("tool")
            if not tools:
                tool_list = [k for k in COMPONENT_REGISTRY._registry.get("tool", {})]
            else:
                tool_list = tools[:6]
            if not tool_list:
                return ""
            names = ", ".join(tool_list)
            return (
                f"\n\n[可用工具] {names}。"
                f"重要规则：任何涉及文件操作（创建、读取、修改、删除）、"
                f"系统命令执行、代码运行、搜索查询的请求，"
                f"必须选择 FULL_DAG 模式并在 steps 中设置 tool 字段。"
                f"即使是简单的文件创建（如'写一个hello world到文件'）也必须用 FULL_DAG。"
                f"只有纯文本闲聊、格式微调、确认回复才可以用 DIRECT。"
            )
        except Exception:
            return ""

    def _verify_physical_tool(self, tool_name: str, result: str) -> str:
        """V7.3: Post-hoc physical verification via Phi: Tool -> Phys.

        Scans orchestrator result for tool failure indicators when the step
        uses a physical (side-effect-producing) tool. On failure, injects
        [PHYSICAL FAIL] annotation for downstream Critic/Synthesis consumption.

        Deeper integration (direct ToolResult access) deferred to V8 when
        the orchestrator exposes per-tool execution results.
        """
        from core.execution.tool_verifier import (
            ToolPhysicalVerifier, is_physical_tool,
        )
        from core.execution.sandbox import PhysicalState

        if not is_physical_tool(tool_name):
            return result

        # Post-hoc: scan result for error indicators
        verifier = ToolPhysicalVerifier()
        phys_state = verifier.verify_text(tool_name, result)

        if phys_state is None:
            return result  # No error detected in text

        if phys_state == PhysicalState.FATAL_EXTERNAL:
            self._emit("🔧 物理验证",
                f"FATAL_EXTERNAL: {tool_name} — external rejection, circuit breaker tripped")
            return (
                f"{result}\n\n"
                f"[PHYSICAL FATAL: {tool_name} received external rejection "
                f"(rate-limit/auth/quota). Circuit breaker tripped. "
                f"No retry — escalate to user.]"
            )

        if phys_state == PhysicalState.SANDBOX_VIOLATION:
            self._emit("🔧 物理验证",
                f"SANDBOX_VIOLATION: {tool_name} — Rigid Contract #5")
            return (
                f"{result}\n\n"
                f"[PHYSICAL FATAL: {tool_name} permission denied. "
                f"Rigid Contract #5 — unconditional abort.]"
            )

        # RUNTIME_ERR / TIMEOUT — retryable
        self._emit("🔧 物理验证",
            f"FAIL: {tool_name} — {phys_state.value}")
        return (
            f"{result}\n\n"
            f"[PHYSICAL FAIL: {tool_name} returned {phys_state.value}. "
            f"Retry with corrected parameters.]"
        )

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

    def _build_synthesis_prompt(self, user: str, system: str, pad: Scratchpad,
                                 constraints: list[str] | None = None) -> str:
        """Build the synthesis prompt. V7.2: supports physical constraints injection."""
        parts = [
            f"用户问题: {user}",
            f"分析结果: {pad.truncated_for_critic()}",
            f"Critic评分: {pad.critic_score:.2f} — {pad.critic_detail}",
        ]
        if pad.retry_count > 0:
            parts.append(f"(经过 {pad.retry_count} 次重试后通过)")

        # V7.2: Physical constraints as structured block — visually distinct
        if constraints:
            constraint_block = "\n".join(
                f"  [{i+1}] {c}" for i, c in enumerate(constraints)
            )
            parts.insert(1,
                f"\n{'='*40}\n"
                f"[PHYSICAL CONSTRAINTS — 以下修改是强制性的]\n"
                f"{constraint_block}\n"
                f"{'='*40}\n"
            )

        return f"{system}\n\n" + "\n".join(parts) + "\n请基于以上内容生成最终回复。"

    def _synthesize(self, user: str, system: str, pad: Scratchpad,
                    constraints: list[str] | None = None) -> str:
        """Build final response from all step results + critique."""
        prompt = self._build_synthesis_prompt(user, system, pad, constraints)
        if self._adapter:
            from core.contracts import GenerationResult
            result = safe_async_run(self._adapter.generate(prompt, [], {}))
            if isinstance(result, GenerationResult):
                return result.text
            return str(result)
        return "\n\n".join(pad.step_results[-3:])

    def _stream_and_collect(self, user: str, system: str, pad: Scratchpad,
                            callback, constraints: list[str] | None = None) -> str:
        """Stream synthesis tokens through callback, return full text."""
        parts: list[str] = []
        for chunk in self._synthesize_stream(user, system, pad, constraints):
            parts.append(chunk)
            try:
                callback(chunk)
            except Exception:
                pass
        return "".join(parts)

    def _synthesize_stream(self, user: str, system: str, pad: Scratchpad,
                           constraints: list[str] | None = None):
        """V7 Phase 1: Stream synthesis tokens via raw LLM client."""
        if self._stream_llm is None:
            yield self._synthesize(user, system, pad, constraints)
            return
        prompt = self._build_synthesis_prompt(user, system, pad, constraints)
        try:
            for chunk in self._stream_llm.generate_stream(prompt):
                yield chunk
        except Exception:
            yield self._synthesize(user, system, pad, constraints)
