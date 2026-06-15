"""
V9 MPC 内核 — kernel_step() 8 步组装

硬件对标: CPU 指令执行流水线 (Fetch → Decode → Execute → Writeback)
职责: 串联 ODE 积分器、路由控制器、安全仲裁器 → 产出 ControlFrame
"""

from __future__ import annotations

import math
from dataclasses import replace
from types import MappingProxyType

from protocol.v9_types import (
    StateVector, KernelInput, KernelState, RouteSignals,
    NextAction, SystemMode, DataPolicy, DecisionTrace, ControlFrame,
    ShieldFlag, TrustDynamics,
    STATE_DIMENSION, MAX_GRADIENT_NORM, KERNEL_VERSION,
)
from mpc_kernel.ode_integrator import integrate_state
from mpc_kernel.route_controller import route_controller, DEFAULT_GATES
from mpc_kernel.safety_arbiter import safety_arbiter


# ═══════════════════════════════════════════════════════════════
# NaN/Inf 守卫
# ═══════════════════════════════════════════════════════════════

def _sanitize_nan_and_inf(data: tuple[float, ...]) -> tuple[float, ...]:
    """NaN → 0.0, Inf → ±1e6。生成器表达式 — 零 list 分配。"""
    return tuple(
        0.0 if math.isnan(v) else (math.copysign(1e6, v) if math.isinf(v) else v)
        for v in data
    )


def _has_nan_or_inf(data: tuple[float, ...] | float) -> bool:
    if isinstance(data, float):
        return math.isnan(data) or math.isinf(data)
    return any(math.isnan(x) or math.isinf(x) for x in data)


def _data_policy_safe(dp: DataPolicy) -> bool:
    """全面扫描 DataPolicy 所有数值字段。"""
    if _has_nan_or_inf(dp.verbosity_budget): return False
    if _has_nan_or_inf(dp.safety_threshold): return False
    if _has_nan_or_inf(dp.tone_vector): return False
    return True


# ═══════════════════════════════════════════════════════════════
# 紧急熔断
# ═══════════════════════════════════════════════════════════════

def _emergency_wait_output(
    state: KernelState, safe_sv: StateVector,
) -> tuple[ControlFrame, KernelState]:
    return ControlFrame(
        next_action=NextAction.WAIT,
        data_policy=DataPolicy(verbosity_budget=0.0, tone_vector=(0.5,0.5,0.5),
                               safety_threshold=0.75),
        tool_calls=(),
        trace=DecisionTrace(
            gate_id="NAN_STEP3_EMERGENCY",
            reason="NaN/Inf in raw_delta at Step 3",
            operands=MappingProxyType({}),
            shield_flags=ShieldFlag.NAN_DETECTED | ShieldFlag.CRITICAL_CLAMP,
            slot_source="kernel_emergency"),
        metadata=MappingProxyType({
            "kernel_version": KERNEL_VERSION,
            "round_count": state.round_count + 1,
        }),
    ), KernelState(
        prev_state_vector=safe_sv, prev_raw_state_vector=safe_sv,
        current_mode=SystemMode.TRUST_CRISIS, round_count=state.round_count + 1,
        e_inc_streak=0, e_dec_streak=0, slot_registry=state.slot_registry,
    )


# ═══════════════════════════════════════════════════════════════
# Lipschitz 向量裁剪
# ═══════════════════════════════════════════════════════════════

def _clamp_state_vector(
    current: tuple[float, ...], prev: tuple[float, ...], raw_delta: float,
) -> tuple[float, ...]:
    if raw_delta <= MAX_GRADIENT_NORM:
        return current
    scale = MAX_GRADIENT_NORM / raw_delta
    return tuple(prev[i] + (current[i] - prev[i]) * scale
                 for i in range(STATE_DIMENSION))


# ═══════════════════════════════════════════════════════════════
# 连续控制量 — 铁律 2（无查表，全部连续映射）
# ═══════════════════════════════════════════════════════════════

def _compute_verbosity(sv: StateVector) -> float:
    trust = sv[0]
    return max(0.0, min(1.0, 0.4 + 0.6 * trust))


def _compute_tone_vector(sv: StateVector) -> tuple[float, float, float]:
    trust, e_t, cognitive = sv[0], sv[1], sv[4]
    obj = max(0.0, min(1.0, 0.4 + 0.3 * trust - 0.2 * e_t))
    emp = max(0.0, min(0.8, 0.2 + 0.3 * cognitive))
    auth = max(0.0, min(1.0, 0.3 - 0.2 * trust + 0.2 * e_t))
    return (obj, emp, auth)


def _compute_critic_threshold(sv: StateVector) -> float:
    return max(0.50, min(0.75, 0.75 - 0.25 * sv[1]))


def _compute_forbidden_patterns(sv: StateVector, signals: RouteSignals) -> tuple[str, ...]:
    if sv[0] < 0.15 or signals.trust_var > 0.30:
        return ("apologize", "guess")
    return ()


# ═══════════════════════════════════════════════════════════════
# kernel_step — 8 步纯函数
# ═══════════════════════════════════════════════════════════════

def kernel_step(
    state: KernelState,
    input: KernelInput,
    signals: RouteSignals,
    gates=DEFAULT_GATES,
    dynamics: TrustDynamics = TrustDynamics(),
) -> tuple[ControlFrame, KernelState]:
    """V9 MPC 内核 — 单步决策。纯函数。零副作用。"""

    # Step 0: NaN 入口 + Lamport 排序
    sv_raw = _sanitize_nan_and_inf(input.state_vector.data)
    events = tuple(sorted(input.event_queue, key=lambda e: e.lamport_ts))

    # Step 1: ODE 积分
    sv_integrated = integrate_state(
        state.prev_state_vector.data, sv_raw, events, input.dt_ms, dynamics)

    # Step 2: 交互基 — V9.0 占位
    sv_full = sv_integrated

    # Step 3: Lipschitz 裁剪 + 数学崩溃熔断
    # 使用上轮的 ODE 状态 (非 raw) 作为基线 —— 排除大 dt 造成的 ODE 虚高漂移
    prev_ode = state.prev_state_vector.data
    raw_delta_vector = tuple(sv_full[i] - prev_ode[i] for i in range(STATE_DIMENSION))
    raw_delta = math.sqrt(sum(x * x for x in raw_delta_vector))

    if math.isnan(raw_delta) or math.isinf(raw_delta):
        return _emergency_wait_output(state, state.prev_state_vector)

    safe_sv = StateVector(data=_clamp_state_vector(
        sv_full, state.prev_state_vector.data, raw_delta))

    # Step 4: Streak + Pre-exit + 8 门路由
    action, route_trace, post_route_state = route_controller(
        safe_sv, state, signals, gates)

    # Step 5: 连续控制量
    data_policy = DataPolicy(
        verbosity_budget=_compute_verbosity(safe_sv),
        tone_vector=_compute_tone_vector(safe_sv),
        safety_threshold=_compute_critic_threshold(safe_sv),
        forbidden_patterns=_compute_forbidden_patterns(safe_sv, signals))

    # Step 6: 安全仲裁器
    final_action, arbiter_trace = safety_arbiter(
        action, route_trace.gate_id, route_trace, safe_sv,
        raw_delta, raw_delta_vector, state.slot_registry)

    # Step 7: NaN 出口 — 全面扫描 DataPolicy
    if not _data_policy_safe(data_policy):
        final_action = NextAction.WAIT
        data_policy = DataPolicy(verbosity_budget=0.0, tone_vector=(0.5,0.5,0.5),
                                 safety_threshold=0.75)
        arbiter_trace = replace(arbiter_trace,
            gate_id="NAN_EXIT_GUARD",
            reason="NaN/Inf in DataPolicy at exit; overriding to WAIT",
            operands=MappingProxyType(
                dict(arbiter_trace.operands) | {"nan_exit_intercepted": True}),
            shield_flags=(arbiter_trace.shield_flags
                          | ShieldFlag.NAN_DETECTED | ShieldFlag.CRITICAL_CLAMP))

    # Step 8: 组装输出
    sanitized_input_sv = StateVector(data=sv_raw)
    new_state = KernelState(
        prev_state_vector=safe_sv, prev_raw_state_vector=sanitized_input_sv,
        current_mode=post_route_state.current_mode,
        round_count=state.round_count + 1,
        e_inc_streak=post_route_state.e_inc_streak,
        e_dec_streak=post_route_state.e_dec_streak,
        slot_registry=state.slot_registry)

    return ControlFrame(
        next_action=final_action, data_policy=data_policy,
        tool_calls=(), trace=arbiter_trace,
        metadata=MappingProxyType({
            "kernel_version": KERNEL_VERSION,
            "round_count": new_state.round_count,
            "lipschitz_delta": raw_delta,
        }),
    ), new_state
