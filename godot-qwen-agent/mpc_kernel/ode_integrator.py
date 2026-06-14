"""
V9 ODE 积分器 — 连续状态演化引擎

硬件对标: CPU ALU 中的浮点乘加单元 (FMA)
职责: 事件脉冲 (Dirac δ × count) + 连续松弛 (帧率无关 EMA) → 更新 ODE 维

数学:
  脉冲:  trust += η × (target − trust) × count  — 瞬时跳跃 (事件合并质量守恒)
  松弛:  trust += (1 − e^(−dt/τ)) × (baseline − trust)  — 连续衰减

  顺序: 先脉冲（事件驱动），后松弛（时间流逝）
        帧率无关 — 1−e^(−dt/τ) 在任何 dt 下不超调
"""

from __future__ import annotations

import math
from protocol.v9_types import TrustDynamics, KernelEvent, STATE_DIMENSION


# ═══════════════════════════════════════════════════════════════
# 帧率无关 EMA
# ═══════════════════════════════════════════════════════════════

def _safe_ema(current: float, target: float, dt_sec: float, tau: float) -> float:
    """指数移动平均 — 帧率无关。"""
    if tau <= 0.0 or math.isinf(tau):
        return current
    lam = 1.0 - math.exp(-dt_sec / tau)
    return current + lam * (target - current)


def _lerp(a: float, b: float, t: float) -> float:
    """线性插值 — t ∈ [0, 1]."""
    t = max(0.0, min(1.0, t))
    return a + t * (b - a)


# ═══════════════════════════════════════════════════════════════
# ODE 积分器 — 纯函数
# ═══════════════════════════════════════════════════════════════

def integrate_state(
    prev_state_vector: tuple[float, ...],   # 上轮裁剪后的 16 维完整状态
    input_raw_vector: tuple[float, ...],    # 当前 16 维观测
    events: tuple[KernelEvent, ...],
    dt_ms: float,
    dynamics: TrustDynamics,
) -> tuple[float, ...]:
    """ODE 积分器 — 纯函数。零副作用。

    Args:
        prev_state_vector: 上轮裁剪后的 16 维 — ODE 维从此起步
        input_raw_vector:  当前 16 维观测 — INSTANT 维直传
        events:            本轮事件队列（含 EventBridge 合并后的 count）
        dt_ms:             物理时间步长
        dynamics:          动力学参数

    Returns:
        新 16 维 tuple — ODE 维已更新，INSTANT 维直传，DERIVED 维留空

    顺序: 先脉冲（事件 × count），后松弛（时间流逝 × EMA）
    """
    dt_sec = dt_ms / 1000.0

    # 提取上轮 ODE 维
    trust = prev_state_vector[0]
    e_t   = prev_state_vector[1]
    tsr   = prev_state_vector[5]
    sm    = prev_state_vector[7]

    # ═══════════════════════════════════════════════════
    # Phase 1: 脉冲响应 — 事件驱动的瞬时跃变
    # 每个脉冲的能量 = η × (target − value) × count
    # count > 1 → EventBridge 合并了同源事件 → 质量守恒
    # ═══════════════════════════════════════════════════
    for evt in events:
        mass = max(evt.count, 1)

        if evt.event_type == "TOOL_EXECUTION_FAILURE":
            trust += dynamics.eta_trust_fail * trust * mass
            e_t = 1.0
            tsr   += dynamics.eta_tsr_fail * tsr * mass

        elif evt.event_type == "TOOL_EXECUTION_SUCCESS":
            trust += dynamics.eta_trust_adopt * (1.0 - trust) * mass
            tsr   += dynamics.eta_tsr_success * (1.0 - tsr) * mass

        elif evt.event_type == "LLM_TIMEOUT":
            e_t = 1.0
            trust += dynamics.eta_trust_fail * 0.5 * trust * mass

        elif evt.event_type == "USER_ABORT":
            trust += dynamics.eta_trust_fail * trust * mass
            e_t = 1.0

    # Phase 1 边界防御 — 确保进入 EMA 的值合法
    trust = max(dynamics.trust_floor, min(1.0, trust))
    e_t   = max(0.0, min(1.0, e_t))
    tsr   = max(0.0, min(1.0, tsr))

    # ═══════════════════════════════════════════════════
    # Phase 2: 连续松弛 — 时间流逝驱动的向基线恢复
    # ═══════════════════════════════════════════════════

    # e_t → 0（无新错误时迅速遗忘）
    e_t = _safe_ema(e_t, 0.0, dt_sec, dynamics.tau_error)

    # tsr → 1（持续无失败 → 工具默认可靠）
    tsr = _safe_ema(tsr, 1.0, dt_sec, dynamics.tau_tsr)

    # trust — 三段式非对称松弛 + 恢复区 Lerp 连续化
    if trust < dynamics.crisis_threshold:
        baseline = dynamics.crisis_baseline
        tau = dynamics.tau_decay
    elif trust < dynamics.recovery_threshold:
        # 恢复区: baseline 从 crisis_baseline 线性滑到 recovery_baseline
        t = ((trust - dynamics.crisis_threshold) /
             (dynamics.recovery_threshold - dynamics.crisis_threshold))
        baseline = _lerp(dynamics.crisis_baseline, dynamics.recovery_baseline, t)
        tau = dynamics.tau_decay
    else:
        # 健康区: baseline → 1.0，慢建立
        baseline = dynamics.healthy_baseline
        tau = dynamics.tau_build

    trust = _safe_ema(trust, baseline, dt_sec, tau)

    # sm — V9 RESERVED
    sm = 1.0

    # ═══════════════════════════════════════════════════
    # 组装 16 维 — ODE 维覆写，INSTANT 维直传
    # ═══════════════════════════════════════════════════
    result = list(input_raw_vector)

    result[0] = max(dynamics.trust_floor, min(1.0, trust))
    result[1] = max(0.0, min(1.0, e_t))
    result[5] = max(0.0, min(1.0, tsr))
    result[7] = sm

    return tuple(result)
