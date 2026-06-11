"""REPL — interactive loop. Depends only on Container, no knowledge of backends."""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from datetime import datetime

import numpy as _np

from core.container import Container
from core.contracts.blueprint_schema import BLUEPRINT_SCHEMA
from core.adapters.agent_router import decide as route_decide
from core.adapters.stream_interceptor import FSMState
from core.xray import XRay
from core.trace_node import TraceNode, TraceStatus


async def _collect_stream(agen):
    """Drain an AsyncIterator into a list."""
    items = []
    async for item in agen:
        items.append(item)
    return items


def _get_registered_tools() -> list[dict]:
    """Return list of {name, description, required_params} for all registered tools."""
    from core.contracts.registry import COMPONENT_REGISTRY
    result = []
    for name in COMPONENT_REGISTRY.list_strategies("tool"):
        try:
            cls = COMPONENT_REGISTRY.get("tool", name)
            schema = getattr(cls, "parameters_schema", {})
            if isinstance(schema, property):
                try:
                    schema = schema.fget(cls())
                except Exception:
                    schema = {}
            desc = getattr(cls, "description", "")
            if isinstance(desc, property):
                try:
                    desc = desc.fget(cls())
                except Exception:
                    desc = name
            if not desc and hasattr(cls, "_mcp_description"):
                desc = cls._mcp_description
            result.append({
                "name": name,
                "description": str(desc)[:100],
                "required_params": schema.get("required", []) if isinstance(schema, dict) else [],
            })
        except Exception:
            pass
    return result

# ── V7.7: Semantic command classifier moved to SemanticTrustEngine.observe() ──
# The old _get_command_model(), _classify_command(), __null__ Voronoi cell
# have been replaced by sheaf-theoretic local sections with ⊥ = E \\ ∪ U_i.
# See core/adapters/semantic_trust.py for the unified observer.


class Repl:
    """Interactive chat loop. Assembled by Container, run by main()."""

    def __init__(self, ctr: Container) -> None:
        self.c = ctr
        # ── V7.4: Restore identity prior for trust (cross-session continuity) ──
        self._identity_prior = self._restore_identity_prior()
        self.trust = self._identity_prior.get("trust_initial", 0.30)
        # ── V7.5: Active concern at session start ──
        self._kernel_snapshot = None  # Updated after each Track C run
        self._session_start_time = time.time()  # For session duration tracking
        self.round_count = 0
        self.healthy_rounds = 0  # Phase 8: consecutive healthy rounds counter
        self.pending: list[dict] = []
        self.pending_consent: list[dict] = []  # Phase 9: proposals awaiting user consent
        self._restore_contract_state()  # Phase 8b: cross-session persistence
        self.history: list[str] = []
        self.contract_events: list[str] = []
        self._amendments_shown: set[str] = set()
        self.prev_response_len = 0
        self.prev_signal: dict = {"dimension": None, "score": 0.0}
        self._last_interaction_time: float | None = None  # V5: tracking error
        # ── V5 Phase B: State-Feedback Route Controller ──
        self._route_track: str = "A"
        self._e_inc_streak: int = 0
        self._e_dec_streak: int = 0
        self._prev_e_t: float = 0.5
        # ── V5 Path 3: Execution Constraint Reflex ──
        self._exec_truncation_streak: int = 0
        self._exec_reflex_active: bool = False
        # ── V6: Semantic drift tracking (Path 2 sensor) ──
        self._prev_user_emb = None       # Previous round's user embedding
        self._embedding_window: list = []   # V6.2: last N user embeddings for session variance
        self._prev_raw_drift: float | None = None  # V6.3: previous round drift for bias tensor
        self._drift_history: list[float] = []  # Drift values for Z-score baseline
        # V6.2: WassersteinProxy — calibrated async at startup
        from core.adapters.wasserstein_proxy import WassersteinProxy
        self._wasserstein = WassersteinProxy.uncalibrated()
        self._w_calibration_started: bool = False
        # ── V7.6: Adaptive contract feedback loop ──
        self._clarity_high: int = 0
        self._frustration_high: int = 0
        self._sensor_cooldown: dict[str, int] = {}
        self._restore_streaks()
        self._sem = None  # V7.7: unified semantic observer (set in run())
        self._semantic_confidence: float = 1.0  # V7.9: continuous ⊥ confidence (replaces bool)
        # Embedding model loads lazily on first _route_task() or _classify_command() call

    # ── V5 Status dashboard ──

    def _print_v5_status(self) -> None:
        """Machine-readable + human-scannable V5 internal state."""
        import statistics as _stats
        acc = self.c.selection_pressure
        meta = self.c.meta_adapt
        te = self.c.tracking_error

        trust_var = acc.get_variance("trust")
        ph = list(meta._pressure_history)
        if len(ph) >= 4:
            mu = _stats.mean(ph)
            sigma = _stats.stdev(ph) if len(ph) >= 2 else 0.0
            dyn_thresh = mu + meta._pressure_sigma * sigma
            dist = dyn_thresh - trust_var
        else:
            mu, sigma, dyn_thresh, dist = 0.19, 0.03, 1.0, float("inf")  # Cold-start defaults

        sid = self.c.profile.session_count
        print(f"\\n  [v5-status] session={sid} round={self.round_count}")

        print(f"  -- Core --")
        print(f"  trust_ema      = {acc.trust_ema:.3f}")
        print(f"  variance       = {trust_var:.4f}  "
              f"(mu={mu:.4f} sigma={sigma:.4f} -> mu+2sig={dyn_thresh:.4f}  "
              f"dist={dist:+.4f})")
        print(f"  tracking_err   = {te.value:.3f}  (samples={te.samples})")

        print(f"  -- Meta-Adapt --")
        print(f"  threshold      = {meta.default_threshold:.3f}")
        print(f"  path1_count    = {meta.trigger_count - meta.pressure_trigger_count}")
        print(f"  path2_count    = {meta.pressure_trigger_count}")
        print(f"  relaxed        = {meta.is_relaxed}")
        print(f"  escalated      = {meta.escalated}")

        print(f"  -- Spinal (Path 3) --")
        print(f"  trunc_streak   = {self._exec_truncation_streak}  (trigger >=2)")
        print(f"  reflex_active  = {self._exec_reflex_active}")
        pl = self.c.output_pipeline
        print(f"  char_mult      = {pl.char_limit_multiplier:.1f}x")
        print(f"  sent_mult      = {pl.sentence_limit_multiplier:.1f}x")

        print(f"  -- Cognition --")
        print(f"  cognition_mark = {meta.cognition if meta.cognition else 'NONE'}")

        print(f"  -- Route Controller (Phase B) --")
        print(f"  route_track    = {self._route_track}")
        print(f"  e_inc_streak   = {self._e_inc_streak}")
        print(f"  e_dec_streak   = {self._e_dec_streak}")

        print(f"  -- e(t) History (last 5) --")
        eh = list(meta._error_history)
        if eh:
            bars = "".join("BLOCK" if e > meta.error_threshold else "_" for e in eh)
            print(f"  {bars}  BLOCK=>{meta.error_threshold:.2f}")

    # ── Prompt construction (delegates to adapters) ──

    def _build_prompt(self, uid: str = "default", xray: "XRay | None" = None) -> str:
        from core.adapters.output_grammar import build_grammar as build_gbnf

        def _build_contract_directive(bp_fields: dict) -> str:
            v = bp_fields.get("response_verbose_level", "HIGH")
            initiative = bp_fields.get("conversational_initiative", "BALANCED")
            tone = bp_fields.get("tone_style", "WARM")
            anchoring = bp_fields.get("contextual_anchoring", "HIGH")
            parts = ["[CURRENT MODE]"]

            # ── V7.8: Continuum interpolation replacing hardcoded v_map ──
            # Each level maps to (min_words, max_words, template).
            # The template uses {words} for the interpolated word count.
            VERBOSE_CONTINUUM = {
                "HIGH":    (600, 800, "详细解释, {words} 字, 多用列表, 可分段"),
                "MEDIUM":  (300, 400, "均衡解释, {words} 字, 适度分段"),
                "LOW":     (100, 150, "简洁回复, {words} 字, 单段落"),
                "MINIMAL": (20,  50,  "极简回复, 不超过 {words} 字"),
            }
            prev_v = getattr(self, '_prev_verbose_level', None)
            if prev_v and prev_v != v and prev_v in VERBOSE_CONTINUUM and v in VERBOSE_CONTINUUM:
                # Transition: use midpoint word count for smooth handoff
                prev_max = VERBOSE_CONTINUUM[prev_v][1]
                curr_min = VERBOSE_CONTINUUM[v][0]
                mid_words = int((prev_max + curr_min) / 2)
                parts.append(f"输出规范: {VERBOSE_CONTINUUM[v][2].format(words=mid_words)} （过渡期）")
            else:
                r = VERBOSE_CONTINUUM.get(v, (300, 400, "均衡, {words} 字"))
                parts.append(f"输出规范: {r[2].format(words=r[1])}")
            self._prev_verbose_level = v

            # ── V7.8: Tone continuum ──
            TONE_CONTINUUM = {
                "ENTHUSIASTIC": "热情洋溢，适度使用感叹号和表情符号",
                "WARM":         "温和共情，语气友善自然",
                "CALM":         "克制冷静，最小化情感表达",
                "PRAGMATIC":    "务实直白，不加修饰语和填充词",
            }
            prev_tone = getattr(self, '_prev_tone_style', None)
            if prev_tone and prev_tone != tone:
                # V7.8: Natural language transition — LLM interpolates between styles
                parts.append(
                    f"语气: 当前正在从「{TONE_CONTINUUM.get(prev_tone, prev_tone)}」"
                    f"向「{TONE_CONTINUUM.get(tone, tone)}」过渡。"
                    f"请采用两者之间的中间风格，自然融合，不要生硬切换。"
                )
            else:
                parts.append(f"语气: {TONE_CONTINUUM.get(tone, tone)}")
            self._prev_tone_style = tone
            # ── End V7.8 ──

            init_map = {"PROACTIVE": "主动引导对话", "BALANCED": "自然有来有回",
                        "RESPONSIVE_ONLY": "绝对不反问"}
            parts.append(f"主动性: {init_map.get(initiative, initiative)}")
            if anchoring == "LOW":
                parts.append("禁止: 晨光/阳光/月光/夜色/微风等时间天气隐喻。直接说事。")
            # Self-evolving values: render custom instruction from Blueprint
            for key in ("tone_style", "response_verbose_level", "explanation_style"):
                inst = self.c.bp.get_instruction(key)
                if inst:
                    parts.append(f"自定义特质({key}): {inst}")
            parts.append("禁止以'你说得对'/'你的判断正确'开头。分歧是尊重。")
            if v in ("LOW", "MINIMAL"):
                parts.append("格式锁: 单段落, 禁止列表/标题/引用。禁止复合句。")
            return "\n".join(parts)

        def _build_context(hist, events) -> str:
            parts = []
            if events:
                parts.append("[契约历史: " + " → ".join(events[-3:]) + "]")
            if hist:
                parts.append("[最近上下文]\n" + "\n".join(hist[-6:]))
            return "\n".join(parts) if parts else ""

        contract = _build_contract_directive(self.c.bp.snapshot)
        context = _build_context(self.history, self.contract_events)
        now = datetime.now().strftime("%H:%M")
        system = f"{contract}\n当前时间: {now}\n{context}".strip()
        # ── V7.9: continuous ⊥ clarification injection ──
        conf = getattr(self, '_semantic_confidence', 1.0)
        if conf < self.SEMANTIC_CONFIDENCE_GAP:
            system += (
                f"\n[语义状态] 上一轮用户输入处于语义模糊区域"
                f"（置信度 {conf:.0%}）。"
                f"如果你不确定用户意图，请礼貌地请用户澄清，不要猜测。"
            )
        return system

    def _detect_explicit_command(self, text: str) -> tuple[str, str] | None:
        """V7.7: Semantic command detection via unified sheaf-theoretic observer.

        Uses self._sem.observe() — which jointly models emotion × command
        on the product fiber with ⊥ region rejection and cross-coefficient
        reweighting. Falls back to keyword matching only when the semantic
        engine is unavailable.
        """
        if self._sem is None:
            return self._keyword_fallback(text)
        try:
            obs = self._sem.observe(text)
        except Exception:
            return self._keyword_fallback(text)
        # Gate: null region, gap region, or low confidence → no command
        # ── V7.9: continuous ⊥ confidence (replaces V7.8 boolean flag) ──
        if obs.null_region:
            self._semantic_confidence = obs.confidence
            self.c.bus.emit("语义真空", f"⊥ region, confidence={obs.confidence:.2f}")
            return None
        if obs.gap_region:
            self._semantic_confidence = obs.confidence
            self.c.bus.emit("语义歧义", f"gap region, {len(obs.command_candidates)} candidates")
            return None

        self._semantic_confidence = 1.0
        if obs.confidence < 0.55:
            return None
        if obs.command is None:
            return None
        return (obs.command["key"], obs.command["value"])

    @staticmethod
    def _keyword_fallback(text: str) -> tuple[str, str] | None:
        """Last-resort command detection when embedding model is unavailable."""
        t = text.strip()
        if any(w in t for w in ("字少点", "别啰嗦", "简洁", "简单点说", "短一点")):
            return ("response_verbose_level", "MINIMAL")
        if any(w in t for w in ("详细点", "展开", "多说点", "展开讲讲")):
            return ("response_verbose_level", "HIGH")
        if any(w in t for w in ("字多点", "多一点", "多一点点", "多讲几句")):
            return ("response_verbose_level", "MEDIUM")
        if any(w in t for w in ("带点感情", "来点人味", "像朋友")):
            return ("tone_style", "WARM")
        if any(w in t for w in ("别问了", "不要问", "别反问", "别老问")):
            return ("conversational_initiative", "RESPONSIVE_ONLY")
        if any(w in t for w in ("你问", "问问题", "反问", "问我", "问几个", "继续问", "多问")):
            return ("conversational_initiative", "PROACTIVE")
        return None

    # ═══════════════════════════════════════════════════════════════════
    # V7.9: Planning semantic adapter — translate contract state for Planning LLM
    # ═══════════════════════════════════════════════════════════════════

    # Only fields whose semantic domain matches Planning enter this map.
    # execution_autonomy → hard branch_count constraint (not in prompt)
    # tone_style, conversational_initiative, contextual_anchoring → Synthesis domain
    PLANNING_SEMANTIC_MAP = {
        "response_verbose_level": (
            "📏 预期最终回复长度: {}。如果该长度显著短于默认值，"
            "你可以适当减少规划步数或降低分解粒度。"
        ),
    }

    SEMANTIC_CONFIDENCE_GAP = 0.8    # Below → Planning should note ambiguity
    SEMANTIC_CONFIDENCE_CRISIS = 0.4  # Below → strongly suggest clarification

    def _build_planning_contract_hint(self) -> str:
        """Translate structured contract state into Planning-domain context.

        Uses _semantic_confidence (continuous ∈ [0,1]) — no boolean collapse.
        Track C receives this as flat text; it knows nothing about Blueprint.
        """
        hints = []

        # 1. Semantic confidence — continuous injection
        confidence = getattr(self, '_semantic_confidence', 1.0)
        if confidence < self.SEMANTIC_CONFIDENCE_CRISIS:
            hints.append(
                f"⚠️ 语义置信度极低 ({confidence:.0%})，"
                f"强烈建议优先规划澄清步骤，暂停复杂任务分解"
            )
        elif confidence < self.SEMANTIC_CONFIDENCE_GAP:
            hints.append(
                f"⚠️ 语义存在轻微歧义（置信度 {confidence:.0%}），"
                f"规划时请保留一定的容错分支"
            )

        # 2. Response length expectation — parametric template
        verbose = self.c.bp.enforce("response_verbose_level")
        if verbose:
            hints.append(
                self.PLANNING_SEMANTIC_MAP["response_verbose_level"].format(verbose)
            )

        if not hints:
            return ""
        return "\n\n[Planning Context] " + " | ".join(hints)

    # ═══════════════════════════════════════════════════════════════════
    # V5 Phase B: State-Feedback Route Controller
    #
    # u(t) = pi(e(t), sigma2(t), trust(t)) -> {A, B, C}
    #
    # Principle of Exhausted Capacity (Cap(Route=C) interlock):
    #   Path 1 only unlocks when route == C. Lower standards only after
    #   exhausting processing capacity.
    #
    # Schmitt Trigger (asymmetric hysteresis):
    #   Upgrade: 2 consecutive e(t) increases + e(t) > 0.55
    #   Downgrade: 3 consecutive e(t) decreases
    #
    # Cold-start Minimax: err-C cost bounded, err-A cost unbounded.
    #   sigma2 low-SNR at cold start -> use user effort as intent proxy.
    #
    # Constitutional: Path 3 (spinal) untouchable; Path 1/2 read-only.

    @staticmethod
    def _compute_confidence(e_t, trust_var, trust):
        """Synthetic confidence for /v5-status display. Not used in routing."""
        norm_var = min(trust_var / 0.5, 1.0)
        penalty = 0.4 * e_t + 0.3 * norm_var + 0.3 * (1.0 - trust)
        conf = max(0.05, 1.0 - penalty)
        if conf > 0.70:    return "confident", conf
        elif conf > 0.40:  return "cautious", conf
        else:              return "uncertain", conf

    def _route_controller(self, e_t, trust_var, trust, user_text):
        """State-feedback route controller. Returns (track_label, reason)."""
        t = user_text.strip()
        meta = self.c.meta_adapt

        # Keep e(t) baseline fresh regardless of overrides (prevents phantom
        # trend accumulation when trust_crisis overrides suppress routing).
        if e_t != self._prev_e_t:
            if e_t > self._prev_e_t:
                self._e_inc_streak += 1
                self._e_dec_streak = 0
            else:
                self._e_dec_streak += 1
                self._e_inc_streak = 0
        self._prev_e_t = e_t

        # 0. Social signals -> A
        # Chinese farewells like "好的谢谢，拜拜" can be 7+ chars.
        # Use more generous length bound + known social keywords.
        socials = ("拜拜","再见","bye","你好","晚安","谢谢","好的","嗯","哦","行","ok","hi","嗨","哈喽")
        if len(t) <= 10 and any(w in t for w in socials):
            return "A", "social"

        # 1. Trust crisis -> A (reset trend on entry — stale signals during crisis)
        if trust < 0.10:
            self._e_inc_streak = 0
            self._e_dec_streak = 0
            return "A", "trust_crisis"

        # 2. Path 2 escalated -> force A (environment too unstable for engine)
        if meta.escalated:
            self._route_track = "A"
            return "A", "path2_escalated"

        # 3. Path 1 relaxed -> force A (Principle of Exhausted Capacity)
        #    C has already been tried and failed. Fall back to direct.
        if meta.is_relaxed:
            self._route_track = "A"
            return "A", "path1_relaxed"

        # Cold-start exploration (Minimax: err-C bounded, err-A unbounded)
        # 10+ Chinese chars = substantial user effort = strong intent proxy.
        if self.round_count <= 2:
            structural = user_text.count("\n") + user_text.count("?") + user_text.count("？") + user_text.count("：")
            if len(user_text) > 10 or structural > 1:
                self._route_track = "C"
                return "C", "coldstart_probe"
            self._route_track = "A"
            return "A", "coldstart_default"

        # Steady-state: Schmitt trigger on e(t) trend (binary A/C)
        # Trend already updated at top of function — just check thresholds here.
        cur = self._route_track
        # Upgrade: 2 consecutive increases + e(t) above threshold -> fire engine
        if self._e_inc_streak >= 2 and e_t > 0.55:
            self._route_track = "C"
            self._e_inc_streak = 0
            return "C", "upgrade"

        # Downgrade: 3 consecutive decreases -> fall back to direct
        if self._e_dec_streak >= 3:
            self._route_track = "A"
            self._e_dec_streak = 0
            return "A", "downgrade"

        # sigma2 safety valve: high variance -> force A
        if trust_var > 0.3 and cur != "A":
            self._route_track = "A"
            return "A", "variance_safety"

        return cur, "hold"
    def _execute_tool(self, tool_name: str, params: dict, xray: XRay) -> str:
        """Execute a tool through ToolEngine (4th engine) with ActionPipeline gate."""
        # Contract gate (backlash, trust, autonomy)
        check = self.c.action_pipeline.check(tool_name)
        if not check["allowed"]:
            return f"[契约拦截: {check['reason']}]"

        try:
            from engines.tool import ToolContext
            from core.contracts.streaming_protocol import PaceConfig
            from core.track_c import safe_async_run

            ctx = ToolContext(tool_name=tool_name, parameters=params)
            items = safe_async_run(_collect_stream(
                self.c.tool_engine.execute(ctx, deadline=30.0, pace_config=PaceConfig())
            ))
            # Extract delta from StreamItems
            full = "".join(item.delta for item in items)
            if full:
                return full
            # Check for error in trace_context
            for item in items:
                if not item.trace_context:
                    continue
                if not item.trace_context.get("tool.success", True):
                    err = item.trace_context.get("tool.error", "unknown")
                    return f"[工具执行失败: {err}]"
            return "[工具返回空结果]"
        except Exception as e:
            return f"[工具异常: {e}]"

    @staticmethod
    def _detect_user_consent(text: str) -> str | None:
        """Phase 9: detect user consent/refusal for pending contract proposals.

        Returns '同意', '拒绝', or None (unrelated input).
        """
        t = text.strip()
        if any(w in t for w in ("可以", "好", "行", "同意", "没问题", "嗯行", "好的", "ok", "yes")):
            return "同意"
        if any(w in t for w in ("不用", "不行", "别", "不了", "不要", "拒绝", "no")):
            return "拒绝"
        return None

    # ═══════════════════════════════════════════════════════════════════
    # V7.4: Identity manifold integration
    # ═══════════════════════════════════════════════════════════════════

    def _restore_identity_prior(self) -> dict:
        """Restore cross-session identity prior at session start.

        Called once per REPL instantiation. Injects semantic + physical
        priors from the identity manifold into the current session's
        initial conditions.
        """
        try:
            uid = self.c.cfg.user_id
            return self.c.identity_store.restore_prior(uid)
        except Exception:
            return {"trust_initial": 0.30, "physical_caution": 1.0}

    def _evolve_identity(self) -> None:
        """Capture session sufficient statistic and evolve identity point.

        Called at session end (/quit or /new boundary).
        Feeds compressed statistics into the identity manifold's OU + push
        pipeline. Graceful degradation — identity errors never crash the REPL.
        """
        if self.round_count < 1:
            return  # No interaction — nothing to evolve
        try:
            uid = self.c.cfg.user_id
            stats = self._build_session_statistic()
            self.c.identity_store.evolve(uid, stats)
        except Exception:
            pass  # Identity is best-effort

    def _build_session_statistic(self) -> "SessionSufficientStatistic":
        """Build compressed sufficient statistic from current session.

        Aggregates all the live signals (trust, drift, clarity, e(t),
        physical events) into a frozen statistic. Never includes raw text.
        """
        from core.memory.identity_manifold import SessionSufficientStatistic

        # Compute physical-3 scores from this session
        # tool_risk_score: mean RESISTANCE_WEIGHT of tools actually used
        tool_risk_score = 0.5  # Default neutral
        budget_exhausted = 0.0
        retry_success = 0.5

        # If Track C engine has physical stats available
        if hasattr(self, '_track_c_engine'):
            eng = self._track_c_engine
            phys = getattr(eng, '_physical_stats', None)
            if phys and isinstance(phys, dict):
                tool_scores = phys.get("tool_risk_scores", [])
                if tool_scores:
                    import statistics
                    tool_risk_score = statistics.mean(tool_scores)
                phys_attempts = phys.get("physical_attempts", 0)
                phys_failures = phys.get("physical_failures", 0)
                if phys_attempts > 0:
                    budget_exhausted = phys.get("budget_exhaustions", 0) / phys_attempts
                    retries = phys.get("retries", 0)
                    retry_passes = phys.get("retry_passes", 0)
                    if retries > 0:
                        retry_success = retry_passes / retries

        return SessionSufficientStatistic(
            trust_final=self.trust,
            drift_values=tuple(self._drift_history[-20:]),
            clarity_values=(),   # Clarity history not tracked per-round currently
            e_t_values=(),       # e(t) history accessible via tracking_error
            selection_pressure_triggers=self.c.meta_adapt.trigger_count,
            physical_failures=getattr(
                getattr(self, '_track_c_engine', None), '_physical_failures', 0
            ),
            physical_attempts=getattr(
                getattr(self, '_track_c_engine', None), '_physical_attempts', 0
            ),
            tool_risk_score=tool_risk_score,
            budget_exhausted_ratio=budget_exhausted,
            retry_success_ratio=retry_success,
            session_duration_sec=time.time() - (self._session_start_time or time.time()),
            round_count=self.round_count,
        )

    # ── V7.5: Active concern ─────────────────────────────────────────

    def _check_active_interrupt(self) -> None:
        """Check internal tension at session start and emit soft interrupt.

        Loads the previous session's kernel snapshot, samples tension,
        and prints a natural-language interrupt if warranted.
        Graceful degradation — errors never crash the REPL.

        V7.5-visibility: always prints a one-line status so the user
        knows the entropy monitor ran, even when nothing is amiss.
        """
        try:
            uid = self.c.cfg.user_id
            from core.watcher.entropy_monitor import load_snapshot
            identity = self.c.identity_store.load(uid)
            snapshot = load_snapshot(".identity", uid, identity.session_count)
            if snapshot is None:
                print(f"  [守望者] 无残留牵挂 — 干净启动")
                return

            # Sample tension
            reading = self.c.entropy_monitor.sample(snapshot, identity)
            msg = self.c.entropy_monitor.format_interrupt(
                reading, identity, snapshot)
            if msg:
                print(f"\n{msg}")
            else:
                d = snapshot.dangling_dag_count
                pf = snapshot.physical_failures
                parts = []
                if d:
                    parts.append(f"dangling={d}")
                if pf:
                    parts.append(f"phys_fails={pf}")
                status = ", ".join(parts) if parts else "clean"
                print(f"  [守望者] 上次残留: {status} (S_int={reading.S_int:.2f} < θ) — 无需干预")
        except Exception:
            pass  # Active concern is best-effort

    def _update_snapshot_after_track(self, track_snapshot: dict | None) -> None:
        """C2: Accumulate snapshot across multiple Track C runs in session.

        Uses max(dangling) and sum(failures) to preserve worst-case state.
        Track A calls this with empty dict to clear DAG/physical fields.
        """
        if track_snapshot is None:
            track_snapshot = {}
        from core.watcher.entropy_monitor import KernelStateSnapshot

        prev = self._kernel_snapshot
        new_dangling = track_snapshot.get("dangling_dag_count", 0)
        new_e_t = track_snapshot.get("accumulated_e_t", 0.0)
        new_budget = track_snapshot.get("budget_remaining_ratio", 1.0)
        new_phys_f = track_snapshot.get("physical_failures", 0)
        new_phys_a = track_snapshot.get("physical_attempts", 0)
        new_mcp_f = track_snapshot.get("mcp_failures", 0)
        new_mcp_a = track_snapshot.get("mcp_attempts", 0)

        if prev is None:
            self._kernel_snapshot = KernelStateSnapshot(
                dangling_dag_count=new_dangling,
                accumulated_e_t=new_e_t,
                budget_remaining_ratio=new_budget,
                physical_failures=new_phys_f,
                physical_attempts=new_phys_a,
                mcp_failures=new_mcp_f,
                mcp_attempts=new_mcp_a,
            )
        else:
            # C2: accumulate — max dangling, sum failures
            self._kernel_snapshot = KernelStateSnapshot(
                dangling_dag_count=max(prev.dangling_dag_count, new_dangling),
                accumulated_e_t=new_e_t,  # latest e_t
                budget_remaining_ratio=new_budget,  # latest budget
                physical_failures=prev.physical_failures + new_phys_f,
                physical_attempts=prev.physical_attempts + new_phys_a,
                mcp_failures=prev.mcp_failures + new_mcp_f,
                mcp_attempts=prev.mcp_attempts + new_mcp_a,
            )

    def _persist_snapshot(self) -> None:
        """Persist kernel snapshot at session end."""
        if self._kernel_snapshot is None:
            return
        try:
            uid = self.c.cfg.user_id
            identity = self.c.identity_store.load(uid)
            from core.watcher.entropy_monitor import persist_snapshot
            persist_snapshot(".identity", uid, self._kernel_snapshot,
                           identity.session_count)
        except Exception:
            pass

    def _restore_contract_state(self) -> None:
        """Phase 8b: restore contract state from previous session on startup."""
        snapshot = self.c.profile.load_blueprint_snapshot()
        if not snapshot:
            return
        # Schema guard: only restore fields that exist in current schema
        valid_keys = set(self.c.bp.fields.keys())
        restored = 0
        for key, val in snapshot.items():
            if key in valid_keys and val is not None:
                try:
                    self.c.bp.apply_proposal(key, val, ignore_cooldown=True)
                    restored += 1
                except Exception:
                    pass  # Skip invalid field values gracefully
        if restored > 0:
            print(f"  [系统] 已从上次会话恢复 {restored} 个合同字段", flush=True)

        # Restore trust baseline if available
        trust_snap = snapshot.get("_trust_baseline")
        if trust_snap is not None and 0.0 <= float(trust_snap) <= 1.0:
            self.trust = float(trust_snap)
            self.c.action_pipeline.trust = self.trust

        # Restore learner thresholds if available
        thresholds = snapshot.get("_thresholds")
        if isinstance(thresholds, dict):
            try:
                self.c.learner.restore_thresholds(thresholds)
            except Exception:
                pass

    def _compute_bias_tensor(self) -> tuple[float, float]:
        """V6.3: Fission relax_bias into two orthogonal control signals.

        Reads meta_adapt snapshot once (P11: execution-time state freeze).
        Uses previous round's raw_drift to classify failure mode:
          - Drift > 0.5 → Intent Contradiction: explore hard, keep Critic strict
          - Drift ≤ 0.5 → Capability Exhaustion: stay focused, relax Critic slightly
          - Drift = None → Minimax: worst-case = intent contradiction

        Returns (explore_bias, compromise_bias). Both zero when not relaxed.
        Pure function: no side effects, no cross-round accumulation.
        """
        snapshot = self.c.meta_adapt.snapshot()
        if not snapshot.get("relaxed", False):
            return 0.0, 0.0

        last_drift = self._prev_raw_drift
        # Minimax Fallback (Patch 3): no history → worst-case = maximum entropy
        if last_drift is None:
            last_drift = 1.0  # [0, 2] endpoint = assume chaos, not calm

        if last_drift > 0.5:
            # Cause B: Intent Contradiction — goal is malformed, explore widely
            return 0.20, 0.00
        else:
            # Cause A: Capability Exhaustion — goal is clear, system can't deliver
            return 0.00, 0.05

    def _start_wasserstein_calibration(self, embed_model) -> None:
        """V6.2: Async background WassersteinProxy calibration.

        Encodes benchmark QA pairs and runs calibrate() in a daemon thread.
        Falls back silently on any error — calibration is best-effort.
        """
        import threading
        from core.adapters.benchmark_qa import get_perfect_text_pairs, get_bad_text_pairs

        def _run():
            try:
                perfect_text = get_perfect_text_pairs()
                bad_text = get_bad_text_pairs()
                perfect_embs = [
                    (embed_model.encode([q])[0], embed_model.encode([a])[0])
                    for q, a in perfect_text
                ]
                bad_embs = [
                    (embed_model.encode([q])[0], embed_model.encode([a])[0])
                    for q, a in bad_text
                ]
                self._wasserstein.calibrate(perfect_embs, bad_embs)
                import sys
                print("  [W-Proxy] calibrated OK", file=sys.stderr)
            except Exception as e:
                import sys
                print(f"  [WARN] W-Proxy: calibration failed ({e})", file=sys.stderr)

        threading.Thread(target=_run, daemon=True).start()

    def _run_track_c(self, user: str, system: str, xray: XRay, live=None,
                     trust: float = 0.5, e_t: float = 0.5,
                     raw_drift: float = 0.0,
                     clarity: float = 0.5,
                     session_gain: float = 1.0,
                     explore_bias: float = 0.0,
                     compromise_bias: float = 0.0,
                     planning_hint: str = "",
                     stream_callback=None):
        """Track C: full engine pipeline. V7 Phase 1: streaming synthesis.
        Returns (response, output_mult, snapshot_dict)."""
        from core.track_c import TrackCEngine
        engine = self._get_track_c_engine()
        response, cog_mult = engine.run(user, system, self.round_count,
                          trust=trust, e_t=e_t, raw_drift=raw_drift,
                          clarity=clarity, session_gain=session_gain,
                          explore_bias=explore_bias, compromise_bias=compromise_bias,
                          planning_hint=planning_hint,
                          stream_callback=stream_callback)
        # V7.5: build snapshot from engine state after execution
        snap = {
            "dangling_dag_count": getattr(engine, '_last_dangling_count', 0),
            "accumulated_e_t": e_t,
            "budget_remaining_ratio": getattr(engine, '_last_budget_ratio', 1.0),
            "physical_failures": getattr(engine, '_physical_failures', 0),
            "physical_attempts": getattr(engine, '_physical_attempts', 0),
            "mcp_failures": getattr(engine, '_mcp_failures', 0),
            "mcp_attempts": getattr(engine, '_mcp_attempts', 0),
        }
        return response, cog_mult, snap

    def _get_track_c_engine(self):
        """Lazy-init Track C engine with real CloudLLM backend."""
        if not hasattr(self, '_track_c_engine'):
            from core.adapters.cloudllm_backend import CloudLLMBackend
            from core.adapters.generator_adapter import GenerationAdapter
            from engines.planning.llm import LLMPlanningEngine
            from engines.orchestration.llm import LLMOrchestrationEngine
            from engines.critic.llm import LLMCriticEngine
            from core.track_c import TrackCEngine

            backend = CloudLLMBackend(self.c.cloud_llm, model="deepseek-chat")
            adapter = GenerationAdapter(backend)

            from engines.planning.contract_aware import ContractAwarePlanningEngine
            from engines.orchestration.contract_aware import ContractAwareOrchestrationEngine
            from engines.critic.contract_aware import ContractAwareCriticEngine

            planning = ContractAwarePlanningEngine(
                LLMPlanningEngine(adapter, kernel=self.c), kernel=self.c,
            )
            orch = ContractAwareOrchestrationEngine(
                LLMOrchestrationEngine(adapter, kernel=self.c), kernel=self.c,
            )
            critic = ContractAwareCriticEngine(
                LLMCriticEngine(adapter, kernel=self.c), kernel=self.c,
            )

            self._track_c_engine = TrackCEngine(
                planning_engine=planning,
                orch_engine=orch,
                critic_engine=critic,
                adapter=adapter,
                bus=self.c.bus,
                stream_llm=self.c.cloud_llm,  # V7 Phase 1: streaming synthesis
            )
        return self._track_c_engine

    def _build_tools_section(self) -> str:
        """Build an [可用工具] section listing all registered tools."""
        try:
            tools = _get_registered_tools()
        except Exception:
            return ""
        if not tools:
            return ""
        lines = ["[可用工具 — 你可以自主选择调用以下工具来完成任务]"]
        for t in tools:
            desc = t.get("description", "")[:80]
            params = ", ".join(t.get("required_params", []))
            lines.append(f"  - {t['name']}: {desc} (参数: {params})")
        lines.append("调用格式: 在回复中写 [TOOL:工具名] {\"参数\":\"值\"}")
        return "\n".join(lines)


    def _update_live(self, xray: XRay, live=None) -> None:
        if live and xray._stages:
            xray.render_live(live)

    def _do_rag(self, query: str, xray: XRay) -> str:
        """Execute RAG pipeline: search → guard → return context or blocked message."""
        from core.adapters.knowledge_search import search as kb_search
        check = self.c.action_pipeline.check("knowledge_search")
        if not check["allowed"]:
            reason = check["reason"]
            print(f"  [RAG] 🔴 拦截: {reason}")
            self.c.bus.emit("知识网关", f"拦截: {reason}")
            return f"[RAG拦截: {reason}]"

        # Semantic mode for Chinese (no word boundaries in keyword mode)
        results = kb_search(query, max_results=5, mode="semantic")
        if not results:
            # Fallback to keyword
            results = kb_search(query, max_results=5, mode="keyword")
        if not results:
            print(f"  [RAG] 未找到匹配: {query}")
            return ""

        filtered = self.c.action_pipeline.guard_post_retrieval("knowledge_search", results)
        context_parts = []
        blocked_count = 0
        for r in filtered:
            blocked = "不可访问" in r.get("content", "")
            if blocked:
                blocked_count += 1
            else:
                self.c.bus.emit("RAG检索", f"命中 {r['file']}")
                context_parts.append(f"[来源: {r['file']}]\n{r['content']}")

        if blocked_count > 0:
            print(f"  [RAG] {blocked_count} 个拦截, {len(filtered)-blocked_count} 个命中")

        rag_context = "\n\n".join(context_parts)
        if not rag_context.strip():
            return "[RAG: 未找到可访问的匹配内容]"
        return rag_context

    def _apply_proposal(self, prop: dict, label: str = "") -> bool:
        accepted, reason = self.c.engine.evaluate(prop, self.c.bp, self.trust)
        if accepted:
            ok, msg = self.c.bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
            if ok:
                self.c.engine.record_evolution(self.trust)
                self.c.profile.record_modification(prop["target_blueprint_key"], prop["new_value"])
                if label:
                    print(f"  [{label}] {prop['target_blueprint_key']} -> {prop['new_value']}")
                return True
        return False

    # ── V7.6: Adaptive contract feedback loop ──────────────────────────

    # Parameter constants (configurable)
    ENTER_STREAK_CLARITY: int = 3      # Rounds of clarity > 0.7 to trigger ∇V
    EXIT_STREAK_FRUSTRATION: int = 3   # Rounds of frustration > 0.5 to exit (hysteresis)
    MIN_SENSOR_COOLDOWN: int = 5       # Min rounds between sensor_adapt on same key
    MAX_GRADIENT_NORM: float = 0.3     # Lipschitz constraint on ∇V (Banach contraction)

    # Compile-time assertion: cooldown >= max hysteresis to prevent dead zones
    assert MIN_SENSOR_COOLDOWN >= max(ENTER_STREAK_CLARITY, EXIT_STREAK_FRUSTRATION), (
        f"V7.6 invariant: cooldown ({MIN_SENSOR_COOLDOWN}) must >= "
        f"max(enter={ENTER_STREAK_CLARITY}, exit={EXIT_STREAK_FRUSTRATION})"
    )

    def _restore_streaks(self) -> None:
        """Restore streak counters from previous session."""
        self._clarity_high = getattr(self.c.profile, '_v76_clarity_streak', 0) or 0
        self._frustration_high = getattr(self.c.profile, '_v76_frustration_streak', 0) or 0

    def _persist_streaks(self) -> None:
        """Save streak counters for cross-session survival (裂缝 1)."""
        try:
            self.c.profile._v76_clarity_streak = self._clarity_high
            self.c.profile._v76_frustration_streak = self._frustration_high
        except Exception:
            pass

    def _force_reset_proposal(self, target_key: str, new_value: str,
                              reason: str = "") -> bool:
        """Apply a contract change bypassing trust gate (裂缝 3).

        For /new and other user-initiated resets. Skips trust gate and
        cooldown, but preserves audit trail.
        """
        ok, msg = self.c.bp.apply_proposal(target_key, new_value,
                                            ignore_cooldown=True)
        if ok:
            self.c.profile.record_modification(target_key, new_value)
            self.c.engine.record_evolution(self.trust)
            self.c.bus.emit("契约重置",
                f"{target_key} → {new_value} ({reason})")
        return ok

    def _compute_selection_pressure(self, clarity: float, frustration: float,
                                    dim, dim_score: float, phys_pass: bool) -> float:
        """σ(r) = σ_clarity + σ_emotion + σ_competence + σ_explicit.

        Selection pressure on the interaction manifold. Orthogonal decomposition
        into four components, each measuring a different selection signal.
        """
        sigma = 0.0

        # σ_clarity: user understands the response (+α₁ when clear and calm)
        if clarity > 0.7 and frustration < 0.1:
            sigma += 0.01

        # σ_emotion: user emotional state (-α₂ when severely frustrated)
        if frustration > 0.7:
            sigma -= 0.02

        # σ_competence: system proved itself (+α₃ on physical PASS)
        if phys_pass:
            sigma += 0.01

        # σ_explicit: user positive feedback from ANY positive emotion dimension.
        # The observer might return "curiosity", "gratitude", etc — all
        # indicate engagement. Use the dimension's own score directly,
        # with sarcasm confidence weighting to filter ironic positives.
        _POSITIVE_DIMS = {"gratitude", "curiosity"}
        if dim in _POSITIVE_DIMS:
            pos_score = dim_score
            sarcasm = getattr(self, '_prev_sarcasm', 0.0)
            confidence = max(0.0, 1.0 - sarcasm)
            if pos_score > 0.6:
                sigma += 0.02 * confidence

        # Hard clamp: asymmetric bounds (penalty can be slightly larger)
        return max(-0.05, min(0.03, sigma))

    def _trust_breathe(self, sigma: float) -> float:
        """T(t) = T(0) + ∫σ dτ — trust as path integral of selection pressure."""
        T_new = self.trust + sigma
        return max(0.0, min(1.0, T_new))

    def _contract_adapt(self, clarity: float, frustration: float) -> None:
        """c_{t+1} = c_t - η·∇V(c_t; s) — contract gradient descent.

        η = f(T): frozen when trust < 0.10, slow when < 0.30, full otherwise.
        Lipschitz constraint ||c' - c|| ≤ MAX_GRADIENT_NORM (裂缝 2.1).
        Hysteresis: enter THEORETICAL at clarity>0.7×3, exit at frustration>0.5×3.
        """
        # ── η: learning rate gated by trust ──
        if self.trust < 0.10:
            return  # Frozen — trust too low
        eta = 0.5 if self.trust < 0.30 else 1.0

        # ── Streak tracking (hysteresis) ──
        if clarity > 0.7:
            self._clarity_high += 1
        else:
            self._clarity_high = 0

        if frustration > 0.5:
            self._frustration_high += 1
        else:
            self._frustration_high = 0

        proposals: list[dict] = []

        # ── ∇_{explanation} V: clarity streak → deeper explanations ──
        if self._clarity_high >= self.ENTER_STREAK_CLARITY:
            current = self.c.bp.enforce("explanation_style")
            if current != "THEORETICAL":
                proposals.append({
                    "target_blueprint_key": "explanation_style",
                    "new_value": "THEORETICAL",
                    "source": "sensor_gradient",
                    "trigger_condition": (
                        f"clarity={clarity:.2f}×{self._clarity_high}r"),
                })
            self._clarity_high = 0

        # ── ∇_{tone} V: frustration streak → warmer tone ──
        if self._frustration_high >= self.EXIT_STREAK_FRUSTRATION:
            current = self.c.bp.enforce("tone_style")
            if current != "WARM":
                proposals.append({
                    "target_blueprint_key": "tone_style",
                    "new_value": "WARM",
                    "source": "sensor_gradient",
                    "trigger_condition": (
                        f"frustration={frustration:.2f}×{self._frustration_high}r"),
                })
            self._frustration_high = 0

        # ── Apply proposals through cooldown + Lipschitz gates ──
        for prop in proposals:
            key = prop["target_blueprint_key"]
            last = self._sensor_cooldown.get(key, -999)
            if self.round_count - last < self.MIN_SENSOR_COOLDOWN:
                continue  # Cooldown — skip
            # ── V7.8: Lipschitz enforcement ──
            if not self._check_lipschitz(key, prop["new_value"]):
                continue  # Step too large — reject
            if self._apply_proposal(prop, label="∇V"):
                self._sensor_cooldown[key] = self.round_count

    def _check_lipschitz(self, key: str, new_value: str) -> bool:
        """Enforce ||c' - c|| ≤ MAX_GRADIENT_NORM (Banach contraction).

        For enum fields: step = |new_ordinal - current_ordinal| / max_ordinal.
        For non-enum fields: always accept (no ordinal scale to measure).
        """
        current = self.c.bp.enforce(key)
        if current is None:
            return True  # Unknown field — let schema validation handle it
        from core.contracts.blueprint_schema import BLUEPRINT_SCHEMA
        schema = BLUEPRINT_SCHEMA.get(key)
        if not schema or schema.get("type") != "enum":
            return True
        values = schema.get("values", [])
        if current not in values or new_value not in values:
            return True  # Novel value — schema validation handles it
        step_size = abs(values.index(new_value) - values.index(current)) / max(len(values) - 1, 1)
        if step_size > self.MAX_GRADIENT_NORM:
            self.c.bus.emit("Lipschitz", f"{key}: |{current}→{new_value}| = {step_size:.2f} > {self.MAX_GRADIENT_NORM}")
            return False
        return True

    # ── Main loop ──

    def run(self) -> None:
        bp, trust = self.c.bp, self.trust
        uid = self.c.cfg.user_id
        session_log: list[str] = []
        rag_mode = False  # Toggle: /rag on | /rag off

        # ── V7.5: Active concern check at session start ──
        self._check_active_interrupt()

        # ── V7.4: Identity manifold status ──
        id_prior = getattr(self, '_identity_prior', {})
        id_caution = id_prior.get("physical_caution", 1.0)
        id_trust_src = "identity" if id_prior else "default"
        id_sessions = self.c.identity_store.load(uid).session_count if self.c.identity_store else 0

        print(f"\n{'='*50}")
        print(f"PLAN5 Live — {uid}")
        print(f"  blueprint: {bp.snapshot}")
        print(f"  trust: {trust:.2f} (from {id_trust_src}) | sessions: {id_sessions}")
        if id_caution != 1.0:
            print(f"  physical_caution: {id_caution:.2f}")
        print(f"  /quit 退出 | /new 新对话")
        print(f"{'='*50}")

        # Semantic trust (lazy load) — V5.3: dual-engine observer
        USE_SEMANTIC = False
        sem = None
        try:
            from core.adapters.semantic_trust import SemanticTrustEngine
            sem = SemanticTrustEngine(llm_client=self.c.cloud_llm)
            USE_SEMANTIC = True
            self._sem = sem  # V7.7: store for _detect_explicit_command + drift
        except (ImportError, OSError):
            self._sem = None
            pass

        while True:
            bp.tick(half_life_rounds=20)
            try:
                user = input(f"\n[{uid}]> ")
            except (EOFError, KeyboardInterrupt):
                break
            cmd = user.strip().lower()
            if cmd in ("/quit", "/exit"):
                self._persist_snapshot()  # V7.5: save snapshot before quit
                break
            if cmd == "/new":
                self._persist_snapshot()  # V7.5: save snapshot before reset
                self._evolve_identity()  # V7.4: persist current session before reset
                # V7.5 UX: reset snapshot for fresh session
                self._kernel_snapshot = None
                self.round_count = 0
                self.history.clear()
                self.contract_events.clear()
                self._force_reset_proposal("tone_style", "WARM", reason="user_reset")
                self._force_reset_proposal("conversational_initiative", "BALANCED", reason="user_reset")
                # V7.4: Restore trust from identity prior (not hardcoded 0.30)
                prior = self._restore_identity_prior()
                self.trust = prior.get("trust_initial", 0.30)
                self.c.profile.start_session()
                # ── V5: reset controller + spinal state ──
                self._route_track = "A"
                self._e_inc_streak = 0
                self._e_dec_streak = 0
                self._prev_e_t = 0.5
                self._exec_truncation_streak = 0
                self._prev_user_emb = None           # Reset semantic drift
                self._drift_history.clear()
                if self._exec_reflex_active:
                    self.c.output_pipeline.char_limit_multiplier = self.c.output_pipeline._base_char_multiplier
                    self.c.output_pipeline.sentence_limit_multiplier = self.c.output_pipeline._base_sentence_multiplier
                    self._exec_reflex_active = False
                print(f"  [新对话] Session {self.c.profile.session_count}. 情绪状态已重置。")
                continue
            if cmd == "/v5-status":
                self._print_v5_status()
                continue
            if cmd == "/mood":
                print(f"  当前: tone={bp.fields.get('tone_style','?')} "
                      f"trust={trust:.2f} initiative={bp.fields.get('conversational_initiative','?')}")
                continue
            if cmd == "/rag on":
                rag_mode = True
                print(f"  [RAG] 本地知识库模式已开启。")
                continue
            if cmd == "/rag off":
                rag_mode = False
                print(f"  [RAG] 本地知识库模式已关闭。")
                continue
            if cmd == "/ignore":
                # V7.5 UX: permanent dismiss of active concern
                from core.watcher.entropy_monitor import delete_snapshot
                delete_snapshot(".identity", uid)
                self._kernel_snapshot = None
                print("  [牵挂] 已关闭。不会再主动提醒。")
                continue
            if cmd == "/mcp" or cmd.startswith("/mcp "):
                # /mcp <tool_name> <json_params>
                parts = user.strip().split(None, 2)
                if len(parts) < 3:
                    print("  用法: /mcp <工具名> <JSON参数>")
                    print("  例如: /mcp read_text_file {\"path\":\"CLAUDE.md\"}")
                    continue
                import json as _json
                try:
                    params = _json.loads(parts[2])
                except _json.JSONDecodeError as e:
                    print(f"  JSON 解析失败: {e}")
                    continue
                xray = XRay()
                result = self._execute_tool(parts[1], params, xray)
                # Truncate long results
                if len(result) > 800:
                    result = result[:800] + f"\n... (截断, 共 {len(result)} 字符)"
                print(f"  [MCP] {parts[1]} →")
                print(result)
                continue
            if cmd == "/tools":
                from core.contracts.registry import COMPONENT_REGISTRY
                tools = COMPONENT_REGISTRY.list_strategies("tool")
                if tools:
                    print(f"  [🔧 工具] 已注册 {len(tools)} 个:")
                    for t in tools:
                        print(f"    - {t}")
                else:
                    print("  [🔧 工具] 无已注册工具。用 --mcp <server> 启动 MCP 服务器。")
                continue
            if cmd == "/trace":
                nodes = self.c.bus.export_trace()
                if nodes:
                    import json as _json
                    print(_json.dumps(nodes, ensure_ascii=False, indent=2))
                else:
                    print("  [trace] 无 Trace 数据。")
                continue
            if cmd == "/rag stats":
                from core.adapters.knowledge_search import cache_stats
                s = cache_stats()
                print(f"  [RAG] 缓存: {s['files_cached']} 文件, "
                      f"{s['queries_cached']} 查询, {s['size_mb']}MB")
                continue
            if cmd.startswith("/rag"):
                # Direct RAG query: /rag 微服务
                xray = XRay()
                query = user[5:].strip() or "test"
                self._do_rag(query, xray)
                continue
            if not user.strip():
                continue

            # ── V7.5: Content-free fast path ──
            # Inputs with no meaningful content (pure punctuation, random
            # keystrokes, single CJK particles without semantic payload)
            # skip the full engine pipeline. This prevents 30-second
            # EXPLORE+FULL_DAG for "nnnn" type inputs.
            stripped = user.strip()
            _has_cjk = any('一' <= c <= '鿿' for c in stripped)
            _has_alpha = any(c.isalpha() for c in stripped)
            _wordish = len(stripped) >= 3 and (_has_cjk or _has_alpha)
            if not _wordish and len(stripped) <= 6:
                # Content-free — echo back quickly, skip all engines
                print(f"\n[agent] 👋")
                self.history.append(f"User: {user}")
                self.history.append("Agent: [content-free skip]")
                continue

            xray = XRay()
            self.c.bus.subscribe(xray)  # X-Ray = observer on the bus
            self.round_count += 1
            try:
                from rich.live import Live
                live = Live(auto_refresh=False, vertical_overflow="visible")
                live.start()
            except ImportError:
                live = None
            if self.round_count == 1:
                self.c.profile.start_session()
                print(f"  [新对话] Session {self.c.profile.session_count}.")

            # ── V5.3 Observe Phase: Dual-Engine Observer ──
            # 1a. Fast Path: embedding-based emotional/state signals (~30ms)
            dim, score = None, 0.0
            clarity = 0.5  # default neutral (no LLM available)
            sig = {"dimension": None, "score": 0.0, "all_scores": {}}
            if USE_SEMANTIC and sem:
                try:
                    sig = sem.detect(user)
                except Exception:
                    sig = {"dimension": None, "score": 0.0, "all_scores": {}}
                dim, score = sig["dimension"], sig["score"]
            if dim:
                self.c.bus.emit("语义感知", f"{dim}={score:.3f}")
                self._update_live(xray, live)

            # 1b + 1c: Reasoning Path (LLM clarity, ~1s) + Historical Path (drift, ~30ms)
            #          Run concurrently: submit clarity to thread pool, compute drift on
            #          main thread while LLM API call is in flight (I/O releases GIL).
            raw_drift = 0.0
            _cur_emb = None  # V6.2: saved for window+gain after both branches
            if USE_SEMANTIC and sem:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                    _future = _pool.submit(sem.assess_clarity, user)
                    # ── Drift computation runs WHILE clarity LLM is in flight ──
                    if len(user.strip()) > 3:
                        try:
                            cur_emb = self._sem.model.encode([user])[0]
                            _cur_emb = cur_emb  # V6.2: save for window
                            if self._prev_user_emb is not None:
                                cos_sim = float(_np.dot(cur_emb, self._prev_user_emb)
                                                / (_np.linalg.norm(cur_emb) * _np.linalg.norm(self._prev_user_emb) + 1e-8))
                                raw_drift = 1.0 - cos_sim
                            self._prev_user_emb = cur_emb
                        except Exception:
                            pass  # Embedding model unavailable → raw_drift stays 0
                    # Barrier: collect clarity (with guarantees cleanup)
                    try:
                        clarity = _future.result(timeout=5.0)
                    except Exception:
                        clarity = 0.5  # LLM hung — neutral fallback

                # ── Clarity sanity gate ──
                # If the LLM returns 0.0 for everything (including "你好呀"),
                # Clarity sanity gate: if the LLM returns ≤0.35 for short
                # clear inputs ("你好呀","对对对","再讲多点"), the sensor is
                # de facto blind. Use input structure as fallback.
                # DeepSeek routinely returns 0.0-0.20 for perfectly clear
                # Chinese inputs — the fallback is essential.
                if clarity <= 0.35:
                    stripped = user.strip()
                    cjk_count = sum(1 for c in stripped if '一' <= c <= '鿿')
                    alpha_count = sum(1 for c in stripped if c.isalpha())
                    wordish = cjk_count + alpha_count
                    if wordish <= 3:
                        clarity = 0.65  # Very short CJK — almost certainly clear
                    elif wordish <= 8:
                        clarity = 0.55  # Short — likely clear
                    elif len(stripped) <= 30:
                        clarity = 0.45
                    else:
                        clarity = 0.35  # Long input — ambiguous, keep low

                self.c.bus.emit("观测器", f"clarity={clarity:.2f}")
                self._update_live(xray, live)
            else:
                # No semantic engine — just compute drift
                if len(user.strip()) > 3:
                    try:
                        cur_emb = self._sem.model.encode([user])[0]
                        _cur_emb = cur_emb  # V6.2: save for window
                        if self._prev_user_emb is not None:
                            cos_sim = float(_np.dot(cur_emb, self._prev_user_emb)
                                            / (_np.linalg.norm(cur_emb) * _np.linalg.norm(self._prev_user_emb) + 1e-8))
                            raw_drift = 1.0 - cos_sim
                        self._prev_user_emb = cur_emb
                    except Exception:
                        pass

            # ── V6.2: Session embedding window → variance → gain ──
            if _cur_emb is not None:
                self._embedding_window.append(_cur_emb)
                if len(self._embedding_window) > 15:
                    self._embedding_window.pop(0)
                # Async background calibration (first-round trigger)
                if not self._w_calibration_started:
                    self._w_calibration_started = True
                    self._start_wasserstein_calibration(self._sem.model)

            session_gain = 1.0
            if len(self._embedding_window) >= 2:
                emb_stack = _np.stack(self._embedding_window)
                session_var = float(_np.var(emb_stack, axis=0).mean())
                session_gain = self._wasserstein.compute_session_gain(
                    session_var, n_rounds=len(self._embedding_window))
            self.c.bus.emit("观测器", f"w-gain={session_gain:.2f}")
            self._update_live(xray, live)

            # ── V6.3: Bias tensor fission (Path 1 → Planning/Critic) ──
            explore_bias, compromise_bias = self._compute_bias_tensor()
            if explore_bias > 0 or compromise_bias > 0:
                self.c.bus.emit("Path 1→C",
                    f"explore={explore_bias:.2f} compromise={compromise_bias:.2f}")
                self._update_live(xray, live)
            self._prev_raw_drift = raw_drift  # Save for next round's bias tensor

            # ── Phase 9: pending consent proposals ──
            if self.pending_consent:
                consent = self._detect_user_consent(user)
                if consent == "同意":
                    for a in self.pending_consent:
                        self.c.kernel_execute_repairs([a])
                        self.c.profile.record_consent_result(a["action"], "同意", a.get("reason",""))
                        direction = "降低" if a["action"] == "lower_autonomy" else "恢复"
                        self.c.bus.emit("合同协商", f"[执行] {direction}自主权限 → {a.get('target','?')}")
                    self.pending_consent.clear()
                    continue
                elif consent == "拒绝":
                    for a in self.pending_consent:
                        self.c.profile.record_consent_result(a["action"], "拒绝", a.get("reason",""))
                    self.c.bus.emit("合同协商", "[取消] 用户拒绝, 保持当前权限")
                    self.pending_consent.clear()
                    continue
                # else: unrelated input, keep proposals pending and fall through to normal processing

            # ── Pending proposals ──
            for prop in list(self.pending):
                if self._apply_proposal(prop, label="SYSTEM2"):
                    self.contract_events.append(f"[R{self.round_count}] {prop['target_blueprint_key']} -> {prop['new_value']}")
                self.pending.remove(prop)

            # ── Explicit commands ──
            explicit = self._detect_explicit_command(user)
            if explicit:
                cmd_prop = {
                    "target_blueprint_key": explicit[0], "new_value": explicit[1],
                    "source": "explicit_user_command",
                    "trigger_condition": "user_said_so",
                    "human_reason": f"User said: '{user[:40]}'",
                }
                if self._apply_proposal(cmd_prop, label="USER COMMAND"):
                    self.contract_events.append(f"[R{self.round_count}] {cmd_prop['target_blueprint_key']} -> {cmd_prop['new_value']}")
                    self.c.bus.emit("用户指令", f"{cmd_prop['target_blueprint_key']} → {cmd_prop['new_value']}")

            # ── V5: Tracking Error + Meta-Adapt Trigger ──
            from core.adapters.tracking_error import compute_error_signal
            import time as _time
            now = _time.time()
            interval = (now - self._last_interaction_time) if self._last_interaction_time else 300.0
            self._last_interaction_time = now

            # Compute error signal from user behavior (not dim/score — actual behavior)
            error_raw, sig_type = compute_error_signal(
                user, response_delay_sec=interval,
                previous_error=self.c.tracking_error.value,
            )
            e_t = self.c.tracking_error.update(error_raw, interval)

            # ── V5: Selection pressure (trust EMA + Bayesian variance) ──
            self.c.selection_pressure.record_trust(trust)
            self.c.selection_pressure.bayesian_update("trust", trust)
            trust_var = self.c.selection_pressure.get_variance("trust")
            pressure_on, dyn_thresh = self.c.meta_adapt.feed_pressure(trust_var)

            # Meta-adapt: check if tracking error persists OR pressure spikes
            current_sel = self.c.meta_adapt.default_threshold
            new_sel, action = self.c.meta_adapt.maybe_relax(e_t, current_sel)
            if action != "hold":
                trigger_reason = "e(t)" if not pressure_on else "pressure"
                self.c.bus.emit(
                    "元适应",
                    f"e(t)={e_t:.2f} var={trust_var:.3f} -> {action} [{trigger_reason}] (thresh={new_sel:.2f})",
                )
            if pressure_on:
                self.c.bus.emit(
                    "选择压力",
                    f"variance spike var={trust_var:.3f} > mu+2sigma={dyn_thresh:.3f}",
                )
            if sig_type != "neutral":
                self.c.bus.emit(
                    "追踪误差",
                    f"e(t)={e_t:.2f} [{sig_type}] interval={interval:.0f}s",
                )

            # ── V7.2: Pseudo mode — all steps as PSEUDOCODE, skip physical verification ──
            if self.c.cfg.pseudo:
                user = (
                    f"[PSEUDOCODE MODE] 以下请求只需要伪代码/架构展示，不需要可执行代码。"
                    f"所有步骤的 intent_type 必须是 PSEUDOCODE。"
                    f"不要写 test_cases。不要用 tool=sandbox_python。\n\n{user}"
                )

            # ── Auto-RAG: inject knowledge context when mode is on ──
            rag_context = ""
            if rag_mode and not cmd.startswith("/"):
                rag_context = self._do_rag(user, xray)
                if rag_context:
                    rag_context = f"\n\n[本地知识库检索结果]\n{rag_context}\n[/知识库]"

            # ── Build prompt + generate ──
            system = self._build_prompt(uid, xray)
            # Inject available tools so LLM can autonomously choose
            tools_section = self._build_tools_section()
            system = f"{system}\n\n{tools_section}" if tools_section else system
            self._update_live(xray, live)  # Flush events from _build_prompt
            full_prompt = f"{system}{rag_context}\n\nUser: {user}"

            # ── V5 Phase B: State-Feedback Route Controller ──
            route, reason = self._route_controller(e_t, trust_var, trust, user)
            self.c.bus.emit("路由决策",
                f"Track {route} ({reason}) "
                f"[V5: e(t)={e_t:.2f} sigma2={trust_var:.3f} trust={trust:.2f}]")
            if route == "C":
                # V7 Phase 1: Streaming synthesis — pause live, stream tokens
                if live:
                    live.stop()  # Release terminal for streaming
                import sys as _sys
                _sys.stdout.write('\n[agent] ')
                _sys.stdout.flush()
                # ── V7.9: Planning contract hint ──
                planning_hint = self._build_planning_contract_hint()
                full_response, cog_mult, track_snap = self._run_track_c(
                    user, system, xray, live,
                    trust=trust, e_t=e_t, raw_drift=raw_drift,
                    clarity=clarity, session_gain=session_gain,
                    explore_bias=explore_bias, compromise_bias=compromise_bias,
                    planning_hint=planning_hint,
                    stream_callback=lambda t: (_sys.stdout.write(t), _sys.stdout.flush()),
                )
                self._update_snapshot_after_track(track_snap)
                # V7.6: capture phys stats for selection pressure σ_competence
                self._last_phys_attempts = track_snap.get("physical_attempts", 0)
                self._last_phys_failures = track_snap.get("physical_failures", 0)
                _sys.stdout.write('\n')
                _sys.stdout.flush()
                if live:
                    live.start()
                # V6: Cognitive depth → dynamic output capacity
                if cog_mult > 1.0:
                    pl = self.c.output_pipeline
                    pl.char_limit_multiplier = max(pl.char_limit_multiplier, cog_mult)
                    pl.sentence_limit_multiplier = max(pl.sentence_limit_multiplier, cog_mult)
            else:
                # V7 Track A: FIR kernel — forget stale topics
                # V7.5 C1: clear DAG/physical from snapshot (Track A has none)
                self._update_snapshot_after_track({
                    "dangling_dag_count": 0,
                    "accumulated_e_t": e_t,
                    "budget_remaining_ratio": 1.0,
                })
                # Free dynamics with exponential decay: old context should NOT
                # cause the LLM to re-engage topics that the user has moved on from.
                decay_directive = (
                    "\n\n[SYSTEM] 前序对话仅供理解当前轮次的指代关系。"
                    "不要主动补充、重新解释或继续展开已结束的历史话题。"
                    "只回应当前轮次用户的直接请求。"
                )
                self.c.bus.emit_pending("内容生成", "⏳ 生成中...")
                self._update_live(xray, live)
                backend = route_decide(bp.snapshot, user, trust)
                if backend == "local":
                    full_response = self.c.local_llm.generate(
                        full_prompt + decay_directive,
                        grammar=build_gbnf(bp.snapshot))
                    self.c.bus.emit("路由决策", "本地 + GBNF 物理约束")
                else:
                    full_response = self.c.cloud_llm.generate(full_prompt + decay_directive)
                self.c.bus.emit("内容生成", f"生成 {len(full_response)} 字符")
                self._update_live(xray, live)

            # ── Output pipeline ──
            # V7 Phase 1: streaming mode skips truncation (LLM self-regulates)
            # Still apply markdown stripping + sycophancy detection
            if route == "C":
                orig_len = len(full_response)
                clean = self.c.output_pipeline._strip_markdown(full_response.strip())
                penalty = self.c.output_pipeline._detect_sycophancy(clean)
                full_response = clean
                if penalty:
                    trust = max(0.0, trust - penalty)
            else:
                orig_len = len(full_response)
                full_response, penalty = self.c.output_pipeline.process(full_response.strip())
                if penalty:
                    trust = max(0.0, trust - penalty)
            self.c.bus.emit("输出管道", f"截断/清洗: {orig_len}->{len(full_response)} 字符")

            # ── V5: Execution feedback (truncation ratio -> e(t) compensation) ──
            truncation_ratio = 1.0 - (len(full_response) / max(orig_len, 1))
            if truncation_ratio > 0.3:
                boost = min(0.15, truncation_ratio * 0.2)
                boosted_e = min(1.0, self.c.tracking_error.value + boost)
                self.c.tracking_error.update(boosted_e, interaction_interval_sec=1.0)
                self.c.bus.emit("执行反馈",
                    f"trunc={truncation_ratio:.0%} -> e(t)+{boost:.3f}")
            elif truncation_ratio > 0.1:
                self.c.bus.emit("执行反馈", f"mild trunc {truncation_ratio:.0%}")

            # ── V5 Path 3: Execution Constraint Reflex (spinal) ──
            EXEC_THRESH = 0.50
            EXEC_STREAK = 2
            EXEC_MULT = 1.5
            MAX_MULT = 2.0
            if truncation_ratio > EXEC_THRESH:
                self._exec_truncation_streak += 1
            else:
                self._exec_truncation_streak = 0
            pipeline = self.c.output_pipeline
            if self._exec_truncation_streak >= EXEC_STREAK:
                if not self._exec_reflex_active:
                    pipeline._base_char_multiplier = pipeline.char_limit_multiplier
                    pipeline._base_sentence_multiplier = pipeline.sentence_limit_multiplier
                    self._exec_reflex_active = True
                extra = self._exec_truncation_streak - EXEC_STREAK
                mult = min(EXEC_MULT + 0.5 * extra, MAX_MULT)
                pipeline.char_limit_multiplier = mult
                pipeline.sentence_limit_multiplier = mult
                self.c.bus.emit("EXEC_REFLEX",
                    f"SPINAL_REFLEX: limits x{mult:.1f} (streak={self._exec_truncation_streak})")
            elif self._exec_truncation_streak == 0 and self._exec_reflex_active:
                pipeline.char_limit_multiplier = pipeline._base_char_multiplier
                pipeline.sentence_limit_multiplier = pipeline._base_sentence_multiplier
                self._exec_reflex_active = False
                self.c.bus.emit("EXEC_REFLEX", "SPINAL_REFLEX released: limits restored")

            self._update_live(xray, live)

            # ── FSM intercept ──
            self.c.action_pipeline.trust = trust
            for token in full_response:
                self.c.fsm.feed(token)
            if self.c.fsm.state == FSMState.BUFFERING:
                self.c.fsm.force_complete()
            if self.c.fsm.state == FSMState.VALIDATING:
                tool_name = self.c.fsm._last_buffer and self.c.fsm._extract_tool_name(self.c.fsm._last_buffer) or "unknown"
                check = self.c.action_pipeline.check(tool_name)
                if check["allowed"]:
                    self.c.fsm.accept()
                else:
                    self.c.fsm.reject(check["reason"])
                    full_response = f"[契约拦截 {tool_name}: {check['reason']}]"

            # Final Live update with all events, then stop
            if live:
                xray.render_live(live)
                live.stop()

            # ── V5: Cognitive honesty marker ──
            cognition = self.c.meta_adapt.cognition
            if cognition:
                full_response = f"{full_response} {cognition}"
                self.c.bus.emit("认知标记", "exploring: high uncertainty, broadening search")
            elif truncation_ratio > 0.5:
                exec_gap_mark = (
                    "[execution_constrained: output truncated by pipeline, "
                    "user requested more content than current mode allows]"
                )
                full_response = f"{full_response} {exec_gap_mark}"
                self.c.bus.emit("认知标记", f"exec_constraint: trunc={truncation_ratio:.0%}")

            # V7 Phase 1: skip print if already streamed (route C)
            if route != "C":
                print(f"\n[agent] {full_response}")
            session_log.append(f"User: {user}\nAgent: {full_response}\n")

            # ── Feedback ──
            if self.prev_signal.get("dimension"):
                result = self.c.listener.on_user_input(user, self.prev_signal, self.prev_response_len)
                if result:
                    pass

            self.prev_response_len = len(full_response)
            self.prev_signal = {"dimension": dim, "score": score} if dim else {"dimension": None, "score": 0.0}

            # ── Post-check + audit ──
            rolled, reason = self.c.engine.post_check(bp, trust)
            if rolled:
                pass
            if self.c.auditor.should_audit(self.round_count):
                self.c.auditor.audit_async(
                    self.history[-20:], bp.snapshot, datetime.now().strftime("%H:%M"),
                    callback=lambda p: self.pending.append(p) if p else None,
                    schema=BLUEPRINT_SCHEMA, rejection_log=bp.rejection_log,
                )

            # ── Amendment ──
            current_v = bp.fields.get("response_verbose_level", "HIGH")
            if current_v != BLUEPRINT_SCHEMA["response_verbose_level"]["default"]:
                amendment = self.c.profile.propose_amendment("response_verbose_level", current_v)
                if amendment and amendment["target_blueprint_key"] not in self._amendments_shown:
                    self._amendments_shown.add(amendment["target_blueprint_key"])

            self.c.profile.save()
            self.history.append(f"User: {user}")
            self.history.append(f"Agent: {full_response[:200]}")
            if len(self.history) > 40:
                self.history = self.history[-40:]

            # ── V7.6: Selection pressure → trust breathing → contract gradient ──
            # Extract emotion signals from semantic observer
            _all_scores = sig.get("all_scores", {}) if sig else {}
            frustration_v = _all_scores.get("frustration", 0.0)
            gratitude_v = _all_scores.get("gratitude", 0.0)
            sarcasm_v = _all_scores.get("sarcasm", 0.0)
            self._prev_gratitude = gratitude_v
            self._prev_sarcasm = sarcasm_v

            # σ_competence: all physical ops passed this round
            _phys_a = getattr(self, '_last_phys_attempts', 0)
            _phys_f = getattr(self, '_last_phys_failures', 0)
            phys_pass = (_phys_a > 0 and _phys_f == 0)

            # ── Capture per-round trust penalties (sycophancy, etc.) ──
            old_trust = self.trust
            self.trust = trust  # trust-local may have been penalized this round

            # ── σ: selection pressure scalar field ──
            sigma = self._compute_selection_pressure(
                clarity, frustration_v, dim, score, phys_pass)

            # T(t) = T(t-1) + Δt_penalty + σ(r_t) — additive on penalized base
            self.trust = self._trust_breathe(sigma)
            trust = self.trust  # Sync local variable for next round's X-Ray display
            # ── V8.0: Continuous trust-driven output attenuation ──
            self.c.output_pipeline.set_trust_attenuation(self.trust)
            delta = self.trust - old_trust
            if abs(delta) > 0.001:
                self.c.profile.record_trust_delta(delta, self.c.profile.session_count)

            # c' = c - η·∇V — contract gradient descent (sensors → contract)
            self._contract_adapt(clarity, frustration_v)

            # Persist streak counters for cross-session survival
            self._persist_streaks()

            # Phase 7-8: self-repair + recovery — health check every 5 rounds or acute crisis
            failures_this_round = sum(self.c.action_pipeline._failure_counts.values())
            if self.round_count % 5 == 0 or failures_this_round >= 2:
                report = self.c.kernel_evaluate_health()

                # Track consecutive healthy rounds (Phase 8)
                if report["overall_status"] == "healthy" and failures_this_round == 0:
                    self.healthy_rounds += 1
                    if self.healthy_rounds == 3:
                        self.c.bus.emit("合同恢复", "提议恢复自主权限 → HIGH")
                else:
                    self.healthy_rounds = 0
                report["healthy_rounds"] = self.healthy_rounds

                if report["overall_status"] != "healthy":
                    actions = self.c.kernel_decide_repair(report)
                    if actions:
                        # Phase 9: split auto vs negotiated
                        consent_actions = [a for a in actions
                                          if a["action"] in ("lower_autonomy", "raise_autonomy")]
                        auto_actions = [a for a in actions if a not in consent_actions]

                        if auto_actions:
                            self.c.kernel_execute_repairs(auto_actions)

                        for a in consent_actions:
                            # Phase 10: suppress if user has repeatedly rejected this
                            if self.c.profile.should_suppress_proposal(a["action"]):
                                self.c.bus.emit("合同协商",
                                    f"[抑制] {a['action']} — 历史拒绝次数过多, 跳过提案")
                                continue
                            direction = "降低" if a["action"] == "lower_autonomy" else "恢复"
                            self.c.bus.emit("合同协商",
                                f"[提议] {direction}自主权限 → {a['target']} ({a.get('reason','健康评估')})")
                            self.pending_consent.append(a)
                elif report["healthy_rounds"] >= max(1, 3 - self.c.profile.get_acceleration("raise_autonomy")):
                    # Phase 8: recovery — try to raise autonomy
                    actions = self.c.kernel_decide_repair(report)
                    if actions:
                        for a in actions:
                            a["healthy_rounds"] = self.healthy_rounds
                        consent_actions = [a for a in actions
                                          if a["action"] in ("lower_autonomy", "raise_autonomy")]
                        auto_actions = [a for a in actions if a not in consent_actions]

                        if auto_actions:
                            self.c.kernel_execute_repairs(auto_actions)

                        for a in consent_actions:
                            if self.c.profile.should_suppress_proposal(a["action"]):
                                self.c.bus.emit("合同协商",
                                    f"[抑制] {a['action']} — 历史拒绝次数过多, 跳过提案")
                                continue
                            direction = "恢复" if a["action"] == "raise_autonomy" else "降低"
                            self.c.bus.emit("合同协商",
                                f"[提议] {direction}自主权限 → {a['target']} (连续健康 {self.healthy_rounds} 轮)")
                            self.pending_consent.append(a)

            print(f"  [trust={trust:.2f} | verbose={bp.fields.get('response_verbose_level', '?')} | round={self.round_count}]")

        print(f"\n{'='*50}")
        print(f"结束。{self.round_count} 轮。")
        # Save session log
        if session_log:
            log_file = f"session_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== Session: {uid} | {datetime.now().isoformat()} | {self.round_count} rounds ===\n\n")
                cleaned = "\n".join(session_log).encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
                f.write(cleaned)
            print(f"日志已保存: {log_file}")

        # V7.4: Evolve identity at session end (before blueprint snapshot)
        self._evolve_identity()
        # V7.5: Persist kernel snapshot for next session's entropy check
        self._persist_snapshot()

        # Phase 7-8b: save full contract state for cross-session persistence
        try:
            snap = dict(self.c.bp.snapshot)
            snap["_trust_baseline"] = self.trust
            snap["_thresholds"] = self.c.learner.get_all_thresholds()
            self.c.profile.save_blueprint_snapshot(snap)
        except Exception:
            pass

        # Cleanup: close SQLite connections
        try:
            self.c.learner.close()
        except Exception:
            pass
