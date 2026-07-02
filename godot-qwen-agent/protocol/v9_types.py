"""
V9 内核协议类型 — 跨层共享的冻结 ABI

硬件对标: Linux <linux/sched.h> 和系统调用 ABI
职责: 定义内核与 Harness 之间交互的绝对契约
      所有类型必须 frozen、不可变、零自然语言

铁律:
  1. 纯函数边界 — 类型不可变
  2. 连续控制 — DataPolicy 字段是连续量，无查表
  3. 零自然语言 — 内核输入输出不含任何文本字符串 (枚举标签除外)
  5. 零动态分配 — tuple 取代 list, MappingProxyType 取代 dict
  7. 可审计 — DecisionTrace 携带完整决策路径
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntFlag
from types import MappingProxyType
from typing import Any, Iterator, Mapping


# ═══════════════════════════════════════════════════════════════
# 协议常量
# ═══════════════════════════════════════════════════════════════

STATE_DIMENSION: int = 16
MAX_EVENTS_PER_STEP: int = 32
MAX_GRADIENT_NORM: float = 0.30
KERNEL_VERSION: str = "V9.0.0"


# ═══════════════════════════════════════════════════════════════
# 枚举 — 严格封闭，字符串值
# ═══════════════════════════════════════════════════════════════

class NextAction(Enum):
    """内核输出的离散模态。3 值 — 不扩展。"""
    GENERATE_RESPONSE = "GENERATE"
    EXECUTE_TOOL = "TOOL"
    WAIT = "WAIT"


class SystemMode(Enum):
    """系统当前模态。状态分区 — 每种危机的退出条件不同。"""
    NORMAL = "NORMAL"
    TRUST_CRISIS = "TRUST_CRISIS"           # P1 — trust ≥ 0.10 时 pre-exit
    VARIANCE_CRISIS = "VARIANCE_CRISIS"     # P7 — trust_var ≤ 0.25 时 pre-exit
    ESCALATED = "ESCALATED"                 # P2 — meta_escalated=False 时 pre-exit


class ShieldFlag(IntFlag):
    """安全仲裁器位掩码。"""
    NONE = 0
    LIPSCHITZ_CLIPPED = 1 << 0    # 状态跳跃被裁剪
    ACTION_DOWNGRADED = 1 << 1    # 动作被降级
    SLOT_RL_ACTIVE = 1 << 2       # RL 策略槽位主导
    NAN_DETECTED = 1 << 3         # 发现 NaN/Inf
    CRITICAL_CLAMP = 1 << 4       # 5× 超标 — 强制 WAIT


# ═══════════════════════════════════════════════════════════════
# 16 维状态向量
# ═══════════════════════════════════════════════════════════════

class StateVector:
    """16 维实向量 ℝ¹⁶。绝对不可变。

    前 8 维 — PHYSICAL + INSTANT:
      [0] trust               [0,1]   ODE     ACTIVE
      [1] e_t                 [0,1]   ODE     ACTIVE
      [2] context_depth       [0,1]   INSTANT PROXY
      [3] rhythm_ratio        [0,∞)   INSTANT ACTIVE
      [4] cognitive_load      [0,1]   INSTANT PROXY
      [5] tool_success_rate   [0,1]   ODE     ACTIVE
      [6] latency_ratio       [0,∞)   INSTANT ACTIVE
      [7] safety_margin       [0,1]   ODE     RESERVED

    后 8 维 — DERIVED (内核 Step 2):
      [8]  drift × e_t              [9]  trust × (1−confidence)
      [10] rhythm × edit            [11] cognitive × latency
      [12] tool_success × (1−trust) [13] safety_margin × e_t
      [14] Δtrust/Δt                [15] Δe_t/Δt
    """
    __slots__ = ("data",)

    def __init__(self, data: tuple[float, ...]) -> None:
        if len(data) != STATE_DIMENSION:
            raise ValueError(f"StateVector: expected {STATE_DIMENSION}, got {len(data)}")
        for i, v in enumerate(data):
            if math.isnan(v) or math.isinf(v):
                raise ValueError(f"StateVector[{i}]: NaN/Inf")
        object.__setattr__(self, "data", data)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("StateVector is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("StateVector is frozen")

    def __getitem__(self, idx: int) -> float:
        return self.data[idx]

    def __iter__(self) -> Iterator[float]:
        return iter(self.data)

    def __len__(self) -> int:
        return STATE_DIMENSION

    def __repr__(self) -> str:
        return f"StateVector({list(self.data)})"


# ═══════════════════════════════════════════════════════════════
# 事件 — 狄拉克 δ 脉冲
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KernelEvent:
    """离散事件脉冲。进入 EventBridge 和内核 ODE 积分器。"""
    event_type: str
    priority: int
    lamport_ts: int
    tool_name: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    count: int = 1
    unmergeable: bool = False


# ═══════════════════════════════════════════════════════════════
# 内核输入
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KernelInput:
    """内核的外部输入。Harness 组装。"""
    state_vector: StateVector
    event_queue: tuple[KernelEvent, ...] = ()
    dt_ms: float = 0.0

    def __post_init__(self) -> None:
        if len(self.event_queue) > MAX_EVENTS_PER_STEP:
            raise ValueError(f"Event queue overflow: max {MAX_EVENTS_PER_STEP}")
        if math.isnan(self.dt_ms) or math.isinf(self.dt_ms) or self.dt_ms < 0:
            raise ValueError(f"Invalid dt_ms: {self.dt_ms}")


# ═══════════════════════════════════════════════════════════════
# 路由信号 — Harness/Adapter → 内核
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RouteSignals:
    """外部状态机与 Observer 的信号摘要。"""
    is_social_signal: bool = False
    meta_escalated: bool = False
    meta_is_relaxed: bool = False
    trust_var: float = 0.0

    def __post_init__(self) -> None:
        if math.isnan(self.trust_var) or math.isinf(self.trust_var):
            raise ValueError("RouteSignals: NaN/Inf")


# ═══════════════════════════════════════════════════════════════
# 内核内部状态
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KernelState:
    """内核的完整跨轮次记忆。纯函数 — 每轮返回新实例。"""
    prev_state_vector: StateVector
    prev_raw_state_vector: StateVector
    current_mode: SystemMode = SystemMode.NORMAL
    round_count: int = 0
    e_inc_streak: int = 0
    e_dec_streak: int = 0
    slot_registry: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        # slot_registry 来自启动注入 — 防御性地包装一次
        if not isinstance(self.slot_registry, MappingProxyType):
            object.__setattr__(self, "slot_registry",
                               MappingProxyType(self.slot_registry))


# ═══════════════════════════════════════════════════════════════
# DataPolicy — 内核产出的约束张量
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DataPolicy:
    """内核产出的约束张量。绝对不含自然语言。

    全部连续量 — 铁律 2:
      verbosity_budget  [0,1] — Harness × base_tokens → MAX_TOKENS
      tone_vector       [客观, 共情, 威严] — LLM Bridge → temperature
      safety_threshold  θ ∈ [0.50, 0.75] — Critic 裁决基准
      forbidden_patterns — 安全拦截词
    """
    verbosity_budget: float = 0.5
    tone_vector: tuple[float, float, float] = (0.5, 0.5, 0.5)
    safety_threshold: float = 0.65
    forbidden_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (0.0 <= self.verbosity_budget <= 1.0):
            raise ValueError(f"verbosity_budget out of [0,1]: {self.verbosity_budget}")
        if not (0.50 <= self.safety_threshold <= 0.75):
            raise ValueError(f"safety_threshold out of [0.50,0.75]: {self.safety_threshold}")
        for i, v in enumerate(self.tone_vector):
            if math.isnan(v) or math.isinf(v):
                raise ValueError(f"tone_vector[{i}]: NaN/Inf")
        if math.isnan(self.verbosity_budget) or math.isinf(self.verbosity_budget):
            raise ValueError("verbosity_budget: NaN/Inf")
        if math.isnan(self.safety_threshold) or math.isinf(self.safety_threshold):
            raise ValueError("safety_threshold: NaN/Inf")
        for p in self.forbidden_patterns:
            if not isinstance(p, str):
                raise TypeError(f"forbidden_patterns item must be str, got {type(p)}")


# ═══════════════════════════════════════════════════════════════
# 审计探针 — 100% 可重放
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DecisionTrace:
    """内核决策的完整审计链。"""
    gate_id: str = ""
    reason: str = ""
    operands: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    shield_flags: int = 0
    slot_source: str = ""


# ═══════════════════════════════════════════════════════════════
# ControlFrame — 内核的唯一输出
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ControlFrame:
    """内核产出的控制帧。Harness 执行。"""
    next_action: NextAction = NextAction.GENERATE_RESPONSE
    data_policy: DataPolicy = field(default_factory=DataPolicy)
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    trace: DecisionTrace = field(default_factory=DecisionTrace)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


# ═══════════════════════════════════════════════════════════════
# ODE 动力学参数
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TrustDynamics:
    """信任动力学参数。⚠️ V9.0 全部默认值未经经验标定。"""
    tau_decay: float = 120.0
    tau_build: float = 600.0
    tau_error: float = 30.0
    tau_tsr: float = 300.0
    tau_recovery: float = 200.0   # B2: 恢复区独立时间常数（原与 tau_decay 耦合）

    eta_trust_fail: float = -0.30
    eta_trust_adopt: float = 0.10
    eta_tsr_fail: float = -0.20
    eta_tsr_success: float = 0.20

    trust_floor: float = 0.05

    crisis_threshold: float = 0.15
    crisis_baseline: float = 0.30
    recovery_threshold: float = 0.50
    recovery_baseline: float = 0.50
    healthy_baseline: float = 1.0

    def __post_init__(self) -> None:
        """B1: τ_eff 安全守卫 — 防止恢复区隐式时间常数爆炸。

        ode_integrator 恢复区: baseline 从 crisis_baseline 线性滑到
        recovery_baseline。有效时间常数 τ_eff = tau_recovery / (1-a)，
        其中 a = (recovery_baseline - crisis_baseline) / denom。
        要求 τ_eff < 10 × tau_recovery → a < 0.9。
        """
        denom = self.recovery_threshold - self.crisis_threshold
        if denom <= 0:
            raise ValueError(
                f"recovery_threshold ({self.recovery_threshold}) must "
                f"exceed crisis_threshold ({self.crisis_threshold})"
            )
        a = (self.recovery_baseline - self.crisis_baseline) / denom
        if a >= 0.90:
            raise ValueError(
                f"Recovery zone too steep: a = ({self.recovery_baseline} - "
                f"{self.crisis_baseline}) / {denom} = {a:.3f} ≥ 0.90. "
                f"τ_eff would exceed 10× tau_recovery. "
                f"Reduce recovery_baseline or increase crisis_baseline."
            )
