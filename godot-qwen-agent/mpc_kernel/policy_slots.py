"""
V9 策略槽位 — RL 挂载点与默认实现

硬件对标: CPU 微码更新接口 + eBPF 验证器
职责: 定义策略 Protocol + 默认规则 + 挂载时签名校验

三个槽位:
  1. BoundaryPolicy  — P(A) ∈ [0,1]。默认: HardThreshold(0.10)
  2. CostPolicy      — cost ∈ [-1,1]。默认: streak 连续函数
  3. ValuePolicy     — V ∈ [-1,1]。默认: ZeroPadding
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Protocol, runtime_checkable, Any
from protocol.v9_types import NextAction


# ═══════════════════════════════════════════════════════════════
# PolicyMetadata
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PolicyMetadata:
    source: str
    version: str = "9.0.0"
    budget_us: int = 1
    is_trainable: bool = False


# ═══════════════════════════════════════════════════════════════
# 策略 Protocols
# ═══════════════════════════════════════════════════════════════

@runtime_checkable
class BoundaryPolicy(Protocol):
    """槽位 1: 边界层 → P(A) ∈ [0, 1]。"""
    metadata: PolicyMetadata
    def evaluate(self, state_vector: tuple[float, ...]) -> float: ...


@runtime_checkable
class CostPolicy(Protocol):
    """槽位 2: 代价函数 → [-1, 1]。

    streak 参数显式注入 — 解决马尔可夫性:
      e_inc_streak, e_dec_streak 在 16 维向量之外（存于 KernelState）。
    """
    metadata: PolicyMetadata
    def cost(
        self,
        state_vector: tuple[float, ...],
        action: NextAction,
        e_inc_streak: int,
        e_dec_streak: int,
    ) -> float: ...


@runtime_checkable
class ValuePolicy(Protocol):
    """槽位 3: 终端价值 → [-1, 1]。"""
    metadata: PolicyMetadata
    def estimate(self, state_vector: tuple[float, ...], horizon: int) -> float: ...


# ═══════════════════════════════════════════════════════════════
# 挂载时签名校验 — runtime_checkable 盲区防御
# ═══════════════════════════════════════════════════════════════

def validate_slot(slot_name: str, policy: Any, protocol_cls: type) -> None:
    """在 Harness 挂载策略时校验方法签名。

    runtime_checkable 只检查属性存在 — 不检查参数签名。
    此函数用 inspect 确保 evaluate/cost/estimate 的参数完全匹配。
    """
    if not isinstance(policy, protocol_cls):
        raise TypeError(
            f"Slot '{slot_name}' does not implement {protocol_cls.__name__}"
        )

    if protocol_cls is BoundaryPolicy:
        method_name = "evaluate"
    elif protocol_cls is CostPolicy:
        method_name = "cost"
    elif protocol_cls is ValuePolicy:
        method_name = "estimate"
    else:
        return

    proto_sig = inspect.signature(getattr(protocol_cls, method_name))
    impl_sig = inspect.signature(getattr(policy, method_name))

    proto_params = list(proto_sig.parameters.keys())[1:]  # skip self
    impl_params = list(impl_sig.parameters.keys())[1:]

    if proto_params != impl_params:
        raise TypeError(
            f"Slot '{slot_name}' signature mismatch!\n"
            f"Expected: {method_name}{proto_sig}\n"
            f"Got:      {method_name}{impl_sig}"
        )


# ═══════════════════════════════════════════════════════════════
# 默认规则
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HardThresholdBoundary:
    """默认边界层 — 硬阈值。V10 RL → LearnedSigmoid。"""
    threshold: float = 0.10
    metadata: PolicyMetadata = PolicyMetadata(
        source="hard_threshold_v9", is_trainable=False,
    )

    def evaluate(self, state_vector: tuple[float, ...]) -> float:
        trust = state_vector[0]
        return 1.0 if trust < self.threshold else 0.0


@dataclass(frozen=True)
class SchmittTriggerCost:
    """默认代价函数 — streak 驱动的连续代价。

    GENERATE = 0.0 (中性基线)
    TOOL:    inc_streak 越高 → cost 越低 (鼓励加资源)
    WAIT:    dec_streak 越高 → cost 越低 (鼓励冷却)

    全部连续 — 铁律 2。无 if/else 阈值判断。
    """
    metadata: PolicyMetadata = PolicyMetadata(
        source="schmitt_trigger_v9", is_trainable=False,
    )

    def cost(
        self,
        state_vector: tuple[float, ...],
        action: NextAction,
        e_inc_streak: int,
        e_dec_streak: int,
    ) -> float:
        e_t = state_vector[1]

        if action == NextAction.GENERATE_RESPONSE:
            return 0.0

        # streak → cost 的连续映射（铁律 2 — 无 if/else 阈值）
        inc_factor = min(1.0, e_inc_streak / 3.0)   # 0..1
        dec_factor = min(1.0, e_dec_streak / 4.0)   # 0..1

        if action == NextAction.EXECUTE_TOOL:
            # inc_streak 高 → TOOL 便宜（鼓励探索）
            # dec_streak 高 → TOOL 贵（该冷却了）
            base = 1.0 - e_t        # e_t 高 → TOOL 便宜
            cost = base - 0.3 * inc_factor + 0.3 * dec_factor

        elif action == NextAction.WAIT:
            # inc_streak 高 → WAIT 贵（需要行动）
            # dec_streak 高 → WAIT 便宜（该冷却）
            cost = e_t + 0.3 * inc_factor - 0.3 * dec_factor

        else:
            return 0.0

        return max(-1.0, min(1.0, cost))


@dataclass(frozen=True)
class ZeroPaddingValue:
    """默认终端价值 — 零填充。V10 RL → learned value head。"""
    metadata: PolicyMetadata = PolicyMetadata(
        source="zero_padding_v9", is_trainable=False,
    )

    def estimate(self, state_vector: tuple[float, ...], horizon: int) -> float:
        return 0.0
