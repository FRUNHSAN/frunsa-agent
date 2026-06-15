"""V9 集成测试 — Observer → Adapter → Kernel 纯决策管道。"""
import asyncio
import math
import time
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from protocol.v9_types import (
    StateVector, KernelInput, KernelState, RouteSignals,
    NextAction, SystemMode, DataPolicy, DecisionTrace, ControlFrame,
    ShieldFlag, TrustDynamics, KernelEvent,
    STATE_DIMENSION, MAX_GRADIENT_NORM,
)
from mpc_kernel.ode_integrator import integrate_state, _safe_ema
from mpc_kernel.route_controller import (
    route_controller, DEFAULT_GATES,
    gate_p0_social, gate_p1_trust_crisis, gate_p2_meta_escalated,
    gate_p4_cold_start, gate_p5_error_streak_up, gate_p6_error_streak_down,
    gate_p7_variance_safety,
    _check_mode_pre_exit,
)
from mpc_kernel.safety_arbiter import safety_arbiter, _hoyer_sparsity
from mpc_kernel.kernel import kernel_step, _clamp_state_vector, _sanitize_nan_and_inf
from observer.observer import SemanticTrustObserver, ObservationResult, ObservedEvent
from mainboard.cpu.adapter import adapter_step, AdapterState


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

def _make_state_vector(trust=0.30, e_t=0.10, context_depth=0.50,
                        rhythm_ratio=1.0, cognitive_load=0.50,
                        tool_success_rate=0.50, latency_ratio=1.0,
                        safety_margin=1.0,
                        **extras) -> StateVector:
    """构建 16 维状态向量。"""
    data = [
        trust, e_t, context_depth, rhythm_ratio,
        cognitive_load, tool_success_rate, latency_ratio, safety_margin,
    ]
    data += [extras.get(i, 0.0) for i in range(8, 16)]
    return StateVector(data=tuple(data))


def _default_kernel_state(trust=0.30, e_t=0.10) -> KernelState:
    sv = _make_state_vector(trust=trust)
    return KernelState(
        prev_state_vector=sv,
        prev_raw_state_vector=sv,
        current_mode=SystemMode.NORMAL,
        round_count=0,
    )


def _default_signals() -> RouteSignals:
    return RouteSignals(trust_var=0.01)


# ═══════════════════════════════════════════════════════════════
# 单元: ODE 积分器
# ═══════════════════════════════════════════════════════════════

class TestODEIntegrator:
    def test_safe_ema_no_overshoot(self):
        """EMA 在任何 dt 下不超调。"""
        # dt=30s: 极大 time step
        result = _safe_ema(0.50, 1.0, 30.0, 600.0)
        assert 0.0 <= result <= 1.0
        # dt=0.001s: 极小 time step
        result = _safe_ema(0.50, 1.0, 0.001, 600.0)
        assert 0.0 <= result <= 1.0

    def test_tool_failure_never_breaks_floor(self):
        """100 次工具失败 → trust ≥ floor。"""
        dynamics = TrustDynamics()
        sv_prev = _make_state_vector(trust=0.50).data
        sv_raw = sv_prev

        for _ in range(100):
            events = (KernelEvent(
                event_type="TOOL_FAILURE",
                priority=2, lamport_ts=0, count=1,
            ),)
            sv_prev = integrate_state(sv_prev, sv_raw, events, 1000, dynamics)
            assert sv_prev[0] >= dynamics.trust_floor

    def test_success_grows_trust(self):
        """工具成功 → trust 上升。"""
        dynamics = TrustDynamics()
        sv_prev = (0.30, 0.0, 0.0, 0.0, 0.0, 0.50, 0.0, 0.0, *[0.0]*8)
        events = (KernelEvent(
            event_type="TOOL_SUCCESS",
            priority=3, lamport_ts=0, count=1,
        ),)
        result = integrate_state(sv_prev, sv_prev, events, 1000, dynamics)
        assert result[0] > 0.30

    def test_count_multiplier(self):
        """count=5 的脉冲是 count=1 的 5 倍。"""
        dynamics = TrustDynamics()
        sv = (0.50, 0.0, 0.0, 0.0, 0.0, 0.50, 0.0, 0.0, *[0.0]*8)

        r1 = integrate_state(sv, sv, (
            KernelEvent(event_type="TOOL_FAILURE", priority=2, lamport_ts=0, count=1),
        ), 1000, dynamics)

        r5 = integrate_state(sv, sv, (
            KernelEvent(event_type="TOOL_FAILURE", priority=2, lamport_ts=0, count=5),
        ), 1000, dynamics)

        assert r5[0] < r1[0]  # 5 次失败 → trust 更低


# ═══════════════════════════════════════════════════════════════
# 单元: 路由控制器
# ═══════════════════════════════════════════════════════════════

class TestRouteController:
    def test_default_fallthrough(self):
        """无信号 → DEFAULT_FALLTHROUGH → GENERATE。"""
        sv = _make_state_vector(context_depth=0.30)  # < 0.40 → P4 不触发
        state = _default_kernel_state()
        state = KernelState(
            prev_state_vector=sv, prev_raw_state_vector=sv,
            current_mode=SystemMode.NORMAL, round_count=5,
        )
        signals = _default_signals()
        action, trace, new_state = route_controller(sv, state, signals)
        assert action == NextAction.GENERATE_RESPONSE
        assert trace.gate_id == "DEFAULT_FALLTHROUGH"

    def test_p1_trust_crisis(self):
        """trust < 0.10 → WAIT + TRUST_CRISIS。"""
        sv = _make_state_vector(trust=0.08)  # trust=0.08
        state = _default_kernel_state(trust=0.08)
        signals = _default_signals()
        action, trace, new_state = route_controller(sv, state, signals)
        assert action == NextAction.WAIT
        assert trace.gate_id == "P1_TRUST_CRISIS"
        assert new_state.current_mode == SystemMode.TRUST_CRISIS

    def test_p1_exits_via_preexit(self):
        """trust 回到 0.10+ → pre-exit 解除 TRUST_CRISIS。"""
        sv = _make_state_vector(trust=0.12, context_depth=0.30)  # < 0.40 → P4 不触发
        state = KernelState(
            prev_state_vector=sv,
            prev_raw_state_vector=sv,
            current_mode=SystemMode.TRUST_CRISIS,
            round_count=5,
        )
        signals = _default_signals()
        action, trace, new_state = route_controller(sv, state, signals)
        assert action == NextAction.GENERATE_RESPONSE  # pre-exit 放行，无门触发
        assert new_state.current_mode == SystemMode.NORMAL

    def test_p0_social(self):
        """社交信号 → GENERATE。"""
        sv = _make_state_vector()
        state = _default_kernel_state()
        signals = RouteSignals(is_social_signal=True, trust_var=0.01)
        action, trace, _ = route_controller(sv, state, signals)
        assert action == NextAction.GENERATE_RESPONSE
        assert trace.gate_id == "P0_SOCIAL"

    def test_p0_blocked_in_crisis(self):
        """危机模式 + 社交信号 → P0 让出，P1 触发。"""
        sv = _make_state_vector(trust=0.08)
        state = KernelState(
            prev_state_vector=sv,
            prev_raw_state_vector=sv,
            current_mode=SystemMode.TRUST_CRISIS,
            round_count=5,
        )
        signals = RouteSignals(is_social_signal=True, trust_var=0.01)
        action, trace, _ = route_controller(sv, state, signals)
        assert trace.gate_id == "P1_TRUST_CRISIS"

    def test_streak_counter(self):
        """连续两轮 e_t 上升 → inc_streak 递增。"""
        sv_a = _make_state_vector(e_t=0.10)  # e_t=0.10
        sv_b = _make_state_vector(e_t=0.12)  # e_t=0.12
        state = KernelState(
            prev_state_vector=sv_a,
            prev_raw_state_vector=sv_a,
            e_inc_streak=1,
            e_dec_streak=0,
        )
        signals = _default_signals()
        _, _, new_state = route_controller(sv_b, state, signals)
        assert new_state.e_inc_streak == 2
        assert new_state.e_dec_streak == 0


# ═══════════════════════════════════════════════════════════════
# 单元: 安全仲裁器
# ═══════════════════════════════════════════════════════════════

class TestSafetyArbiter:
    def test_lipschitz_clip(self):
        """1× 超标 → 只标记，不降级。"""
        sv = _make_state_vector()
        raw_delta_vec = tuple(0.18 if i < 4 else 0.0 for i in range(16))
        raw_delta = math.sqrt(sum(x*x for x in raw_delta_vec))
        assert raw_delta > MAX_GRADIENT_NORM
        route_trace = DecisionTrace(gate_id="DEFAULT_FALLTHROUGH", reason="test",
                                    operands=MappingProxyType({}))
        action, trace = safety_arbiter(
            NextAction.GENERATE_RESPONSE, "DEFAULT_FALLTHROUGH",
            route_trace, sv, raw_delta, raw_delta_vec, {},
        )
        assert action == NextAction.GENERATE_RESPONSE
        assert trace.shield_flags & ShieldFlag.LIPSCHITZ_CLIPPED

    def test_hoyer_sparsity(self):
        """单维尖峰 → 高稀疏度。多维均匀 → 低稀疏度。"""
        spike = tuple([1.0] + [0.0]*15)
        uniform = tuple([0.25]*16)
        assert _hoyer_sparsity(spike) > 0.8
        assert _hoyer_sparsity(uniform) < 0.5

    def test_nan_detection(self):
        """NaN → WAIT。"""
        from protocol.v9_types import DecisionTrace
        sv = _make_state_vector()
        route_trace = DecisionTrace(gate_id="test", reason="test",
                                    operands=MappingProxyType({}))
        action, trace = safety_arbiter(
            NextAction.EXECUTE_TOOL, "P5_ERROR_STREAK_UP",
            route_trace, sv, float('nan'), tuple([0.0]*16), {},
        )
        assert action == NextAction.WAIT
        assert trace.shield_flags & ShieldFlag.NAN_DETECTED


# ═══════════════════════════════════════════════════════════════
# 单元: 策略槽位
# ═══════════════════════════════════════════════════════════════

class TestPolicySlots:
    def test_hard_threshold(self):
        from mpc_kernel.slots.policy_slots import HardThresholdBoundary
        p = HardThresholdBoundary(threshold=0.10)
        sv_bad = _make_state_vector(trust=0.08).data
        sv_ok = _make_state_vector(trust=0.30).data
        assert p.evaluate(sv_bad) == 1.0
        assert p.evaluate(sv_ok) == 0.0

    def test_schmitt_cost_continuous(self):
        from mpc_kernel.slots.policy_slots import SchmittTriggerCost
        p = SchmittTriggerCost()
        sv = _make_state_vector(e_t=0.60).data
        cost_tool = p.cost(sv, NextAction.EXECUTE_TOOL, 3, 0)
        cost_gen = p.cost(sv, NextAction.GENERATE_RESPONSE, 3, 0)
        assert -1.0 <= cost_tool <= 1.0
        assert cost_gen == 0.0

    def test_validate_slot_ok(self):
        from mpc_kernel.slots.policy_slots import (
            HardThresholdBoundary, BoundaryPolicy, validate_slot,
        )
        policy = HardThresholdBoundary()
        validate_slot("boundary", policy, BoundaryPolicy)  # 不应抛异常

    def test_validate_slot_bad(self):
        """签名不匹配 → TypeError。"""
        from mpc_kernel.slots.policy_slots import BoundaryPolicy, validate_slot

        class BadPolicy:
            metadata = None
            def evaluate(self):  # 漏了 state_vector 参数
                return 0.5

        with pytest.raises(TypeError):
            validate_slot("boundary", BadPolicy(), BoundaryPolicy)


# ═══════════════════════════════════════════════════════════════
# 集成: Observer → Adapter → Kernel
# ═══════════════════════════════════════════════════════════════

class TestObserverAdapterKernel:
    def test_cold_start_pipeline(self):
        """无 ML 引擎 → 关键词回退 → Adapter → Kernel。"""
        observer = SemanticTrustObserver(semantic_engine=None)

        async def run():
            obs = await observer.observe("你好")
            assert obs.is_social_query or obs.confidence == 0.5

            adapter_state = AdapterState()
            sv, signals, events, new_adapter_state = adapter_step(
                adapter_state, obs.confidence, obs.text_tokens,
                obs.is_social_query, obs.escalation_flag, obs.relaxation_flag,
                obs.discrete_events, prev_raw_trust=0.30, prev_raw_e_t=0.0,
                current_timestamp=time.time(), expected_latency_ms=2000.0,
                base_lamport=0,
            )
            assert len(sv.data) == 16

            kernel_state = _default_kernel_state()
            kernel_input = KernelInput(state_vector=sv, event_queue=events, dt_ms=500.0)
            signals_in = _default_signals()

            frame, new_state = kernel_step(kernel_state, kernel_input, signals_in)
            assert frame.next_action in (
                NextAction.GENERATE_RESPONSE, NextAction.EXECUTE_TOOL, NextAction.WAIT,
            )
            assert frame.trace.gate_id != ""

            return frame, new_state

        frame, new_state = asyncio.run(run())
        print(f"  [{frame.trace.gate_id}] → {frame.next_action.value}")

    def test_trust_crisis_triggered(self):
        """低 trust → P1 触发。"""
        sv = _make_state_vector(trust=0.08)
        state = _default_kernel_state(trust=0.08)
        state = KernelState(
            prev_state_vector=sv, prev_raw_state_vector=sv,
            current_mode=SystemMode.NORMAL, round_count=5,
        )
        signals = _default_signals()

        kernel_input = KernelInput(
            state_vector=sv, event_queue=(), dt_ms=1000.0,
        )
        frame, new_state = kernel_step(state, kernel_input, signals)
        assert frame.next_action == NextAction.WAIT
        assert frame.trace.gate_id == "P1_TRUST_CRISIS"
        assert new_state.current_mode == SystemMode.TRUST_CRISIS

    def test_p5_triggers_at_route_level(self):
        """e_t 连续上升 → P5 → TOOL（路由控制器级别）。"""
        sv_curr = _make_state_vector(e_t=0.60, context_depth=0.30)  # < 0.40 → P4 不触发
        sv_prev = _make_state_vector(e_t=0.50, context_depth=0.30)
        state = KernelState(
            prev_state_vector=sv_prev, prev_raw_state_vector=sv_prev,
            current_mode=SystemMode.NORMAL, round_count=5,
            e_inc_streak=2, e_dec_streak=0,
        )
        action, trace, _ = route_controller(sv_curr, state, _default_signals())
        assert action == NextAction.EXECUTE_TOOL
        assert trace.gate_id == "P5_ERROR_STREAK_UP"


# ═══════════════════════════════════════════════════════════════
# 边界: Lipschitz + NaN
# ═══════════════════════════════════════════════════════════════

class TestBoundaryConditions:
    def test_lipschitz_clamps_vector(self):
        """大跳跃 → 被裁剪。"""
        prev = tuple([0.5]*16)
        curr = tuple([0.1]*16)
        raw_delta = math.sqrt(sum((curr[i]-prev[i])**2 for i in range(16)))
        clamped = _clamp_state_vector(curr, prev, raw_delta)
        new_delta = math.sqrt(sum((clamped[i]-prev[i])**2 for i in range(16)))
        assert new_delta <= MAX_GRADIENT_NORM + 1e-10

    def test_lipschitz_passes_through_small_change(self):
        """小跳跃 → 不裁剪。"""
        prev = tuple([0.30]*16)
        curr = tuple([0.31]*16)
        raw_delta = math.sqrt(sum((curr[i]-prev[i])**2 for i in range(16)))
        clamped = _clamp_state_vector(curr, prev, raw_delta)
        assert clamped == curr

    def test_sanitize_removes_nan(self):
        """NaN → 0.0。"""
        data = (float('nan'), 1.0) + tuple([0.0]*14)
        cleaned = _sanitize_nan_and_inf(data)
        assert cleaned[0] == 0.0
        assert cleaned[1] == 1.0

    def test_sanitize_clamps_inf(self):
        """Inf → ±1e6。"""
        data = (float('inf'), float('-inf')) + tuple([0.0]*14)
        cleaned = _sanitize_nan_and_inf(data)
        assert cleaned[0] == 1e6
        assert cleaned[1] == -1e6

    def test_emergency_fuse_on_nan_delta(self):
        """raw_delta = NaN → 紧急熔断 → WAIT + CRISIS。"""
        sv = _make_state_vector()
        # 绕过 __init__ 的 NaN 守卫来测试熔断路径
        corrupted = object.__new__(StateVector)
        object.__setattr__(corrupted, "data", tuple([float('nan')]*16))
        state = KernelState(
            prev_state_vector=corrupted, prev_raw_state_vector=sv,
            current_mode=SystemMode.NORMAL, round_count=5,
        )
        kernel_input = KernelInput(state_vector=sv, event_queue=(), dt_ms=500.0)
        frame, new_state = kernel_step(state, kernel_input, _default_signals())
        assert frame.next_action == NextAction.WAIT
        assert new_state.current_mode == SystemMode.TRUST_CRISIS


# ═══════════════════════════════════════════════════════════════
# 数据完整性
# ═══════════════════════════════════════════════════════════════

class TestDataIntegrity:
    def test_state_vector_freezing(self):
        """StateVector 不可修改。"""
        sv = _make_state_vector()
        with pytest.raises(AttributeError):
            sv.data = tuple([0.0]*16)
        with pytest.raises(TypeError):
            sv[0] = 999.0  # __setitem__ not implemented

    def test_decision_trace_has_operands(self):
        """每个 kernel_step 产出有 operands 的 DecisionTrace。"""
        sv = _make_state_vector()
        state = _default_kernel_state()
        signals = _default_signals()
        kernel_input = KernelInput(state_vector=sv, event_queue=(), dt_ms=500.0)
        frame, _ = kernel_step(state, kernel_input, signals)
        assert frame.trace.gate_id != ""
        assert isinstance(frame.trace.operands, MappingProxyType)

    def test_data_policy_bounds(self):
        """DataPolicy 值域校验。"""
        with pytest.raises(ValueError):
            DataPolicy(verbosity_budget=2.0)  # >1
        with pytest.raises(ValueError):
            DataPolicy(safety_threshold=0.30)  # <0.50
        with pytest.raises(ValueError):
            DataPolicy(tone_vector=(float('nan'), 0.5, 0.5))


# ═══════════════════════════════════════════════════════════════
# 适配层
# ═══════════════════════════════════════════════════════════════

class TestAdapter:
    def test_adapter_output_dimensions(self):
        """适配层产出 16 维。"""
        state = AdapterState()
        sv, signals, events, new_state = adapter_step(
            state, confidence=0.72, text_tokens=("帮","我","写","Python","脚本"),
            is_social=False, escalated=False, relaxed=False,
            discrete_events=(),
            prev_raw_trust=0.30, prev_raw_e_t=0.0,
            current_timestamp=time.time(), expected_latency_ms=2000.0,
            base_lamport=0,
        )
        assert len(sv.data) == 16
        # INSTANT 维非零
        assert sv[2] > 0.0  # context_depth = 1.0 − confidence
        assert sv[4] > 0.0  # cognitive_load (Guiraud's R)
        # ODE 维 = 0.0 占位
        assert sv[0] == 0.0
        assert sv[1] == 0.0

    def test_adapter_trust_var(self):
        """trust_var 从滑动窗口计算。"""
        state = AdapterState()
        # 第一轮 — 数据不足
        sv, signals, _, new_state = adapter_step(
            state, 0.5, ("a",), False, False, False, (),
            prev_raw_trust=0.30, prev_raw_e_t=0.0,
            current_timestamp=time.time(), expected_latency_ms=2000.0,
            base_lamport=0,
        )
        assert signals.trust_var == 0.0  # 数据不足 → 0
