"""
V9 安全仲裁器 — 内核最后一道门

硬件对标: 硬件看门狗定时器 + 信号完整性校验器
职责: Lipschitz 约束 + 稀疏度鉴别 + 槽位溯源 + NaN 终检

数学:
  大小判别 — raw_delta ‖Δs‖₂ 三级降级
  结构判别 — Hoyer 稀疏度（前 8 独立维）
    高稀疏 → 单维尖峰 → 传感器故障 → 只标记不降级
    低稀疏 → 多维协同 → 真实剧变 → 降级或 WAIT

  三级降级矩阵:
    5× 超标 + 高稀疏 → 传感器故障（标记）
    5× 超标 + 低稀疏 → 真实剧变（强制 WAIT）
    2× 超标 + 高稀疏 → 传感器异常（标记）
    2× 超标 + 低稀疏 → 快速变化（TOOL → GENERATE）
    1× 超标           → 轻微超标（标记）
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Mapping
from protocol.v9_types import (
    ShieldFlag, NextAction, DecisionTrace, StateVector,
    MAX_GRADIENT_NORM,
)


# ═══════════════════════════════════════════════════════════════
# 稀疏度阈值
# ═══════════════════════════════════════════════════════════════

SPARSITY_SENSOR_FAULT = 0.80   # ⚠️ 未标定 — 高稀疏 → 单维尖峰 → 传感器故障
SPARSITY_ANOMALY = 0.60       # ⚠️ 未标定 — 中高稀疏 → 少数维异常


# ═══════════════════════════════════════════════════════════════
# Hoyer 稀疏度 — 前 8 独立维
# ═══════════════════════════════════════════════════════════════

def _hoyer_sparsity(delta_vec: tuple[float, ...]) -> float:
    """Hoyer 稀疏度 ∈ [0, 1]。只在独立维 [0:8] 上计算。

    后 8 维 (DERIVED) 是前 8 维的代数组合 — 不独立。

    1.0 = 单维尖峰（能量集中，低熵 — 传感器故障）
    0.0 = 全均匀 或 全零（能量分散 / 无变化 — 无法判断）
    """
    independent = delta_vec[:8]
    n = len(independent)
    l1 = sum(abs(x) for x in independent)
    l2 = math.sqrt(sum(x * x for x in independent))
    if l2 < 1e-10:
        return 0.0  # 全零 → 无变化 → 无稀疏概念
    return (math.sqrt(n) - l1 / l2) / (math.sqrt(n) - 1)


# ═══════════════════════════════════════════════════════════════
# 槽位溯源
# ═══════════════════════════════════════════════════════════════

def _resolve_slot_source(
    gate_id: str,
    slot_registry: Mapping[str, object],
) -> str:
    """检查被触发的门所属的策略领域是否有 RL 策略挂载。

    防御性属性访问 — RL 插件元数据可能不完整。
    """
    if gate_id in ("P1_TRUST_CRISIS", "P7_VARIANCE_CRISIS"):
        slot_name = "boundary"
    elif gate_id in ("P4_COLD_START", "P5_ERROR_STREAK_UP", "P6_ERROR_STREAK_DOWN"):
        slot_name = "cost"
    else:
        return "default_rule"

    policy = slot_registry.get(slot_name)
    if policy is not None:
        meta = getattr(policy, "metadata", None)
        if meta is not None and getattr(meta, "is_trainable", False):
            return getattr(meta, "source", "default_rule")
    return "default_rule"


# ═══════════════════════════════════════════════════════════════
# NaN/Inf 检测
# ═══════════════════════════════════════════════════════════════

def _has_nan_or_inf(data: tuple[float, ...] | float) -> bool:
    """检测 NaN 或 Inf。接受 tuple 或标量。"""
    if isinstance(data, float):
        return math.isnan(data) or math.isinf(data)
    return any(math.isnan(x) or math.isinf(x) for x in data)


# ═══════════════════════════════════════════════════════════════
# 安全仲裁器 — 纯函数
# ═══════════════════════════════════════════════════════════════

def safety_arbiter(
    action: NextAction,
    gate_id: str,
    route_trace: DecisionTrace,
    safe_sv: StateVector,
    raw_delta: float,
    raw_delta_vector: tuple[float, ...],
    slot_registry: Mapping[str, object],
) -> tuple[NextAction, DecisionTrace]:
    """V9 安全仲裁器 — 纯函数。零副作用。

    @chain:     2026-07-05-v9-kernel-architecture   — Lipschitz 梯度有界 + 三级降级矩阵
    @invariant: INV-006                     — ‖Δsv‖₂ ≤ MAX_GRADIENT_NORM (0.30)
    @verified:  2026-07-05

    Returns:
        (动作, 填充了 shield_flags 和 slot_source 的 DecisionTrace)
    """
    flags = ShieldFlag.NONE

    # raw_delta NaN 提前拦截 — 防御纵深
    if _has_nan_or_inf(raw_delta):
        return NextAction.WAIT, DecisionTrace(
            gate_id=gate_id,
            reason=route_trace.reason + " | NaN in raw_delta",
            operands=route_trace.operands,
            shield_flags=ShieldFlag.NAN_DETECTED | ShieldFlag.CRITICAL_CLAMP,
            slot_source="default_rule",
        )

    sparsity = _hoyer_sparsity(raw_delta_vector)

    # ═══════════════════════════════════════════════════════
    # 1. Lipschitz 三级降级（大小判别 + 结构判别）
    # ═══════════════════════════════════════════════════════

    if raw_delta > 5 * MAX_GRADIENT_NORM:
        if sparsity > SPARSITY_SENSOR_FAULT:
            flags |= ShieldFlag.LIPSCHITZ_CLIPPED
        else:
            action = NextAction.WAIT
            flags |= ShieldFlag.CRITICAL_CLAMP | ShieldFlag.ACTION_DOWNGRADED

    elif raw_delta > 3.5 * MAX_GRADIENT_NORM and action == NextAction.EXECUTE_TOOL:
        if sparsity > SPARSITY_ANOMALY:
            flags |= ShieldFlag.LIPSCHITZ_CLIPPED
        else:
            action = NextAction.GENERATE_RESPONSE
            flags |= ShieldFlag.ACTION_DOWNGRADED

    elif raw_delta > MAX_GRADIENT_NORM:
        flags |= ShieldFlag.LIPSCHITZ_CLIPPED

    # ═══════════════════════════════════════════════════════
    # 2. 槽位溯源
    # ═══════════════════════════════════════════════════════
    slot_source = _resolve_slot_source(gate_id, slot_registry)
    if slot_source != "default_rule":
        flags |= ShieldFlag.SLOT_RL_ACTIVE

    # ═══════════════════════════════════════════════════════
    # 3. NaN 终检 — StateVector
    # ═══════════════════════════════════════════════════════
    if _has_nan_or_inf(safe_sv.data):
        action = NextAction.WAIT
        flags |= ShieldFlag.NAN_DETECTED | ShieldFlag.CRITICAL_CLAMP

    # ═══════════════════════════════════════════════════════
    # 4. 组装审计 Trace — 追加仲裁数据
    # ═══════════════════════════════════════════════════════
    ops = dict(route_trace.operands) | {
        "raw_delta": raw_delta,
        "sparsity": sparsity,
        "max_norm": MAX_GRADIENT_NORM,
    }

    return action, DecisionTrace(
        gate_id=gate_id,
        reason=route_trace.reason,
        operands=MappingProxyType(ops),
        shield_flags=flags,
        slot_source=slot_source,
    )
