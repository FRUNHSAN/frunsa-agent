"""
V9 路由控制器 — 8 门优先级仲裁 + Pre-exit 模式退出

硬件对标: CPU 分支预测器 + 中断优先级编码器
职责: 16 维状态 + RouteSignals + KernelState → NextAction + DecisionTrace

数学:
  Bang-bang 控制 — Pontryagin 极大值原理: 线性 Hamiltonian 的最优控制在边界
  8 门优先级链 — 偏序集的全序化仲裁
  Schmitt 触发器 (P5/P6) — Galois 连接 U ⊣ D (2 升/3 降非对称)
  Pre-exit — 模式退出不参与门仲裁 (解除警报后才走战术决策)

设计决策:
  P1 不需要迟滞带 — trust 的 EMA 惯性 (τ=120s) 就是迟滞
  P4 上下文不足时 fallthrough — 不抢占低优先级门
  P0 危机模式下让出 — 社交信号不凌驾于系统生存
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Optional, Callable
from dataclasses import dataclass, field

from protocol.v9_types import (
    StateVector, KernelState, RouteSignals, NextAction, SystemMode, DecisionTrace,
)


# ═══════════════════════════════════════════════════════════════
# GateResult — 门触发后的标准化输出
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class GateResult:
    """门触发后的标准化输出 — 自描述、带审计探针。"""
    action: NextAction
    gate_id: str
    reason: str
    operands: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    next_mode: SystemMode | None = None  # None = 不改变模态


Gate = Callable[[StateVector, KernelState, RouteSignals], Optional[GateResult]]


# ═══════════════════════════════════════════════════════════════
# Pre-exit — 模式退出（不参与门仲裁）
# ═══════════════════════════════════════════════════════════════

def _check_mode_pre_exit(
    sv: StateVector,
    current_mode: SystemMode,
    signals: RouteSignals,
) -> SystemMode:
    """评估当前环境是否已脱离危机。在门仲裁之前运行。

    P1: trust < 0.10 进入 → trust ≥ 0.10 退出。
        无额外迟滞带 — EMA τ=120s 的惯性已提供迟滞。
    P7: trust_var > 0.35 进入 → trust_var ≤ 0.25 退出（迟滞带）。
    """
    if current_mode == SystemMode.TRUST_CRISIS:
        if sv[0] >= 0.10:
            return SystemMode.NORMAL
    elif current_mode == SystemMode.VARIANCE_CRISIS:
        if signals.trust_var <= 0.25:
            return SystemMode.NORMAL
    elif current_mode == SystemMode.ESCALATED:
        if not signals.meta_escalated:
            return SystemMode.NORMAL
    return current_mode


# ═══════════════════════════════════════════════════════════════
# 8 个门
# ═══════════════════════════════════════════════════════════════

def gate_p0_social(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P0: 社交信号 → 直接 GENERATE。

    紧急熔断: 危机模式或 escalation 下让出控制权。
    社交信号不凌驾于系统生存。
    """
    in_crisis = state.current_mode in (
        SystemMode.TRUST_CRISIS, SystemMode.VARIANCE_CRISIS, SystemMode.ESCALATED
    )
    if signals.is_social_signal and not in_crisis and not signals.meta_escalated:
        return GateResult(
            action=NextAction.GENERATE_RESPONSE,
            gate_id="P0_SOCIAL",
            reason="Social signal — direct response",
            operands=MappingProxyType({}),
            next_mode=None,
        )
    return None


def gate_p1_trust_crisis(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P1: trust < 0.10 → WAIT + TRUST_CRISIS。

    无迟滞带: EMA τ=120s 的惯性已提供足够的抗抖振能力。
    """
    trust = sv[0]
    if trust < 0.10:
        return GateResult(
            action=NextAction.WAIT,
            gate_id="P1_TRUST_CRISIS",
            reason=f"Trust critically low ({trust:.3f})",
            operands=MappingProxyType({"trust": trust, "threshold": 0.10}),
            next_mode=SystemMode.TRUST_CRISIS,
        )
    return None


def gate_p2_meta_escalated(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P2: 外部升级 → WAIT + ESCALATED。"""
    if signals.meta_escalated:
        return GateResult(
            action=NextAction.WAIT,
            gate_id="P2_META_ESCALATED",
            reason="External MetaAdapt escalation",
            operands=MappingProxyType({}),
            next_mode=SystemMode.ESCALATED,
        )
    return None


def gate_p3_meta_relaxed(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P3: 外部放松 → GENERATE + NORMAL。"""
    if signals.meta_is_relaxed:
        return GateResult(
            action=NextAction.GENERATE_RESPONSE,
            gate_id="P3_META_RELAXED",
            reason="External MetaAdapt relaxation",
            operands=MappingProxyType({}),
            next_mode=SystemMode.NORMAL,
        )
    return None


def gate_p4_cold_start(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P4: 模糊意图 → 工具调用。

    context_depth > 0.40 → TOOL (LLM 不确定 → 需要外部信息)。
    不再限制轮数 — Agent 终身具备工具调用能力。

    安全网: P0(社交) + P1(信任衰减) + context_depth 阈值
    防止工具滥用，无需额外的轮数限制。
    """
    context_depth = sv[2]  # [PROXY: clarity]
    if context_depth > 0.40:
        return GateResult(
            action=NextAction.EXECUTE_TOOL,
            gate_id="P4_COLD_START",
            reason=f"Round {state.round_count}: sufficient structure [PROXY]",
            operands=MappingProxyType({
                "round": state.round_count, "context_depth": context_depth,
            }),
            next_mode=SystemMode.NORMAL,
        )
    # fallthrough — 让 P5/P6/P7 有机会
    return None


def gate_p5_error_streak_up(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P5: e_t 连续上升 ≥ 2 且 e_t > 0.55 → TOOL (加资源)。

    RL BoundaryPolicy 影子模式接入 (E1): rl_rec 仅记录不改变硬阈值。
    V10 → 完整影子模式（所有门求值 → 收集 RL 推荐 → 不限于触发门）。
    """
    # SHADOW_MODE_LIMITATION (V10): rl_rec is only recorded when P5 triggers.
    # Non-trigger frames discard the RL recommendation — full shadow mode
    # requires route_controller to collect RL evals from ALL gates, not just
    # the first-triggered one. This is V10 gate-vector work.
    rl_rec = None
    boundary = state.slot_registry.get("boundary")
    if boundary is not None:
        try:
            rl_rec = boundary.evaluate(tuple(sv))  # StateVector → tuple[float,...]
        except Exception:
            rl_rec = None  # RL 故障 → 静默降级，不影响硬阈值逻辑

    e_t = sv[1]
    if state.e_inc_streak >= 2 and e_t > 0.55:
        operands = {
            "e_t": e_t, "threshold": 0.55,
            "inc_streak": state.e_inc_streak, "min_streak": 2,
        }
        if rl_rec is not None:
            operands["rl_boundary"] = rl_rec
        return GateResult(
            action=NextAction.EXECUTE_TOOL,
            gate_id="P5_ERROR_STREAK_UP",
            reason=f"e_t rising ×{state.e_inc_streak} — {e_t:.3f} > 0.55",
            operands=MappingProxyType(operands),
            next_mode=SystemMode.NORMAL,
        )
    return None


def gate_p6_error_streak_down(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P6: e_t 连续下降 ≥ 3 → GENERATE (恢复确认)。"""
    if state.e_dec_streak >= 3:
        return GateResult(
            action=NextAction.GENERATE_RESPONSE,
            gate_id="P6_ERROR_STREAK_DOWN",
            reason=f"e_t falling ×{state.e_dec_streak} — recovery confirmed",
            operands=MappingProxyType({
                "dec_streak": state.e_dec_streak, "min_streak": 3,
            }),
            next_mode=SystemMode.NORMAL,
        )
    return None


def gate_p7_variance_safety(
    sv: StateVector, state: KernelState, signals: RouteSignals,
) -> Optional[GateResult]:
    """P7: trust_var > 0.35 → WAIT + VARIANCE_CRISIS (带迟滞退出 0.25)。"""
    trust_var = signals.trust_var
    if trust_var > 0.35:
        return GateResult(
            action=NextAction.WAIT,
            gate_id="P7_VARIANCE_CRISIS",
            reason=f"trust_var ({trust_var:.3f}) > 0.35 — safety valve",
            operands=MappingProxyType({
                "trust_var": trust_var, "threshold_enter": 0.35,
            }),
            next_mode=SystemMode.VARIANCE_CRISIS,
        )
    return None


# ═══════════════════════════════════════════════════════════════
# 默认门元组 — 优先级顺序
# ═══════════════════════════════════════════════════════════════

DEFAULT_GATES: tuple[Gate, ...] = (
    gate_p0_social,
    gate_p1_trust_crisis,
    gate_p2_meta_escalated,
    gate_p3_meta_relaxed,
    gate_p4_cold_start,
    gate_p5_error_streak_up,
    gate_p6_error_streak_down,
    gate_p7_variance_safety,
)


# ═══════════════════════════════════════════════════════════════
# 路由控制器核心 — 纯函数
# ═══════════════════════════════════════════════════════════════

def route_controller(
    sv: StateVector,
    state: KernelState,
    signals: RouteSignals,
    gates: tuple[Gate, ...] = DEFAULT_GATES,
) -> tuple[NextAction, DecisionTrace, KernelState]:
    """V9 路由控制器 — 纯函数。零副作用。

    顺序:
      1. Streak 更新 — 比较本轮 e_t 与上轮 e_t（EPS=1e-4 防浮点抖动）
      2. Pre-exit — 模式退出，不参与门仲裁
      3. eval_state — streak 已更新，mode 已 pre-exit
      4. 门仲裁 — 优先级链。第一个返回非 None 的门胜出
      5. 默认 — GENERATE_RESPONSE
    """
    # ── Step 1: Streak 更新 ──
    current_e_t = sv[1]
    prev_e_t = state.prev_state_vector[1]
    EPSILON = 1e-4  # 足够过滤 EMA 衰减末期的浮点假阳性

    new_inc = state.e_inc_streak + 1 if current_e_t > prev_e_t + EPSILON else 0
    new_dec = state.e_dec_streak + 1 if current_e_t < prev_e_t - EPSILON else 0

    # ── Step 2: Pre-exit ──
    pre_exit_mode = _check_mode_pre_exit(sv, state.current_mode, signals)

    # ── Step 3: 构造 eval_state ──
    eval_state = KernelState(
        prev_state_vector=state.prev_state_vector,
        prev_raw_state_vector=state.prev_raw_state_vector,
        current_mode=pre_exit_mode,
        round_count=state.round_count,
        e_inc_streak=new_inc,
        e_dec_streak=new_dec,
        slot_registry=state.slot_registry,
    )

    # ── Step 4: 门仲裁 ──
    triggered: Optional[GateResult] = None
    for gate in gates:
        result = gate(sv, eval_state, signals)
        if result is not None:
            triggered = result
            break

    # ── Step 5: 默认 ──
    if triggered is None:
        action = NextAction.GENERATE_RESPONSE
        trace = DecisionTrace(
            gate_id="DEFAULT_FALLTHROUGH",
            reason="No gates triggered",
            operands=MappingProxyType({}),
        )
        final_mode = pre_exit_mode
    else:
        action = triggered.action
        trace = DecisionTrace(
            gate_id=triggered.gate_id,
            reason=triggered.reason,
            operands=triggered.operands,
        )
        final_mode = (
            triggered.next_mode
            if triggered.next_mode is not None
            else pre_exit_mode
        )

    # ── 组装新 KernelState ──
    new_state = KernelState(
        prev_state_vector=sv,
        prev_raw_state_vector=state.prev_raw_state_vector,
        current_mode=final_mode,
        round_count=state.round_count + 1,
        e_inc_streak=new_inc,
        e_dec_streak=new_dec,
        slot_registry=state.slot_registry,
    )

    return action, trace, new_state
