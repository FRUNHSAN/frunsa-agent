"""
V9 Adapter — 适配层 (CPU 插座)

硬件对标: CPU 插座的引脚定义 (LGA 1700)
职责: Observer 信号语言 → 内核向量语言（10 标量 → 16 维 + RouteSignals + 透传事件）

数学: 纯函数映射。唯一的状态是两个滑动窗口 — 统计量维护，不是决策状态。

协议对齐:
  输入:  Harness 拆分 Observer 输出后的标量
  输出:  StateVector (16 维) + RouteSignals + discrete_events (透传) + AdapterState

分层边界:
  - 不 import KernelEvent — 事件翻译由 Harness 负责
  - 不 import EventBridge — 适配层不知道总线的存在
  - 所有映射公式连续 — 铁律 2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

STATE_DIMENSION = 16
MAX_DT_WINDOW = 10
MAX_TRUST_WINDOW = 20


# ═══════════════════════════════════════════════════════════════
# 协议类型（占位 — 最终需移到 protocol/v9_types.py）
# ═══════════════════════════════════════════════════════════════

class StateVector:
    """16 维实向量。绝对不可变。"""
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


class RouteSignals:
    """外部信号摘要。绝对不可变。"""
    __slots__ = ("is_social_signal", "meta_escalated", "meta_is_relaxed", "trust_var")

    def __init__(
        self, is_social_signal: bool = False,
        meta_escalated: bool = False, meta_is_relaxed: bool = False,
        trust_var: float = 0.0,
    ) -> None:
        object.__setattr__(self, "is_social_signal", is_social_signal)
        object.__setattr__(self, "meta_escalated", meta_escalated)
        object.__setattr__(self, "meta_is_relaxed", meta_is_relaxed)
        object.__setattr__(self, "trust_var", trust_var)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("RouteSignals is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("RouteSignals is frozen")


# ═══════════════════════════════════════════════════════════════
# AdapterState — 适配层内部状态
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AdapterState:
    """适配层内部状态。纯统计量 — 无决策、无对话历史。"""
    last_timestamp: float = 0.0
    dt_window: tuple[float, ...] = ()
    trust_window: tuple[float, ...] = ()
    last_actual_latency_ms: float = 1000.0


# ═══════════════════════════════════════════════════════════════
# 辅助纯函数
# ═══════════════════════════════════════════════════════════════

def _update_fifo(old: tuple[float, ...], new: float, capacity: int) -> tuple[float, ...]:
    """纯函数 FIFO。零分配 — tuple 拼接。"""
    return (new,) + old[:capacity - 1]


def _compute_variance(window: tuple[float, ...]) -> float:
    """滑动窗口方差。"""
    if not window:
        return 0.0
    mu = sum(window) / len(window)
    return sum((x - mu) ** 2 for x in window) / len(window)


# ═══════════════════════════════════════════════════════════════
# Adapter 单步纯函数
# ═══════════════════════════════════════════════════════════════

def adapter_step(
    adapter_state: AdapterState,
    confidence: float,
    text_tokens: tuple[str, ...],
    is_social: bool,
    escalated: bool,
    relaxed: bool,
    discrete_events: tuple,       # tuple[ObservedEvent, ...] — 透传给 Harness
    prev_raw_trust: float,
    prev_raw_e_t: float,
    current_timestamp: float,
    expected_latency_ms: float,
    base_lamport: int,            # 暂未使用 — V11 事件 Lamport 分配
) -> tuple[StateVector, RouteSignals, tuple, AdapterState]:
    """V9 适配层单步映射。纯函数。零副作用。

    Returns:
        (StateVector, RouteSignals, discrete_events (透传), AdapterState)
    """
    dt_current = max(0.0, current_timestamp - adapter_state.last_timestamp)

    # ── [2] context_depth (PROXY: 1.0 − confidence) ──
    context_depth = 1.0 - confidence

    # ── [3] rhythm_ratio (Δt / MA — 冷启动默认 1.0) ──
    new_dt_window = _update_fifo(adapter_state.dt_window, dt_current, MAX_DT_WINDOW)
    if len(new_dt_window) < 2:
        rhythm_ratio = 1.0
    else:
        ma = sum(new_dt_window) / len(new_dt_window)
        rhythm_ratio = dt_current / max(ma, 0.1)

    # ── [4] cognitive_load (Guiraud's R + 贝叶斯平滑) ──
    # 分母 +2 = 两个伪计数 — 标准信息论平滑 prior
    # n=2: type/√4 → 连续。n=3: type/√5 → 连续。无阶跃。
    n_tokens = max(1, len(text_tokens))
    n_types = len(set(text_tokens))
    cognitive_load = min(1.0, n_types / math.sqrt(n_tokens + 2))

    # ── [6] latency_ratio ──
    latency_ratio = adapter_state.last_actual_latency_ms / max(expected_latency_ms, 1.0)

    # ── trust_var (raw track — 不被 Lipschitz 裁剪污染) ──
    new_trust_window = _update_fifo(adapter_state.trust_window, prev_raw_trust, MAX_TRUST_WINDOW)
    if len(new_trust_window) < 3:
        trust_var = 0.0
    else:
        trust_var = _compute_variance(new_trust_window)

    # ── 组装 16 维 StateVector ──
    sv = StateVector(data=(
        0.0,              # [0]  trust            — ODE 占位
        0.0,              # [1]  e_t              — ODE 占位
        context_depth,    # [2]  context_depth    — INSTANT, PROXY
        rhythm_ratio,     # [3]  rhythm_ratio     — INSTANT
        cognitive_load,   # [4]  cognitive_load   — INSTANT, PROXY
        0.0,              # [5]  tool_success_rate — ODE 占位
        latency_ratio,    # [6]  latency_ratio    — INSTANT
        0.0,              # [7]  safety_margin    — ODE 占位, RESERVED
        *[0.0] * 8,       # [8-15] DERIVED        — 内核 Step 2 填充
    ))

    # ── RouteSignals ──
    signals = RouteSignals(
        is_social_signal=is_social,
        meta_escalated=escalated,
        meta_is_relaxed=relaxed,
        trust_var=trust_var,
    )

    # ── 事件透传 — 不包装。Harness 负责翻译成 KernelEvent ──
    new_state = replace(
        adapter_state,
        last_timestamp=current_timestamp,
        dt_window=new_dt_window,
        trust_window=new_trust_window,
    )

    return sv, signals, discrete_events, new_state
