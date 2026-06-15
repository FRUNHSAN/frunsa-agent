"""
V9 Event Bridge — 事件总线桥接器 (NVIC 级)

硬件对标: NVIC (Nested Vectored Interrupt Controller) + 中断合并 (Interrupt Coalescing)
职责: 收集异步中断脉冲 → 合并去重 → 优先级排序 → drain() 注入内核

数学框架:
  事件 = 狄拉克 δ 脉冲 — ODE 积分器的瞬时冲击源
  优先级 = 偏序集 (Poset) — 0=最高 (NMI), 99=最低 (遥测)
  合并 = 等价类划分 — (type, tool_name) 相同 → count 累加
  drain() = 偏序集的全序化 — 按 (priority, lamport_ts) 确定性排序

协议依赖（全部冻结）:
  MAX_EVENTS_PER_STEP = 32

关键设计决策:
  - emit() 同步入队、非阻塞
  - 物理硬保留槽位: 普通事件 ≤ 28 个 (32−4), 高优事件 ≤ 4 个 (priority ≤ 1)
  - 优先级驱逐: 高优可踢普通
  - USER_ABORT 不可合并、不可丢弃 — NMI
  - Lamport 时钟内部严格单调: 每次 emit() 原子递增, 保证因果律
  - 等价类合并保留 count — 不丢失 "多少次" 的信息
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

MAX_EVENTS_PER_STEP = 32

@dataclass(frozen=True)
class EventBridgeConfig:
    """事件总线物理参数。"""
    max_buffer_size: int = 32                           # 缓冲区硬上限
    reserved_slots: int = 4                             # 物理预留 — 仅 priority ≤ 1
    merge_by: tuple[str, ...] = ("type", "tool_name")   # 等价类划分键
    enable_priority_eviction: bool = True               # 高优先级驱逐低优先级
    unmergeable_types: tuple[str, ...] = ("USER_ABORT",)# 不参与合并的事件类型


# ═══════════════════════════════════════════════════════════════
# 优先级表 — 偏序集 (Poset)
# 数值越小 → 优先级越高。0 = NMI（不可屏蔽中断）。
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 总线宪法 — 内置事件类型 (不可被覆盖)
# ═══════════════════════════════════════════════════════════════
# 优先级定义:
#   0     = NMI (不可屏蔽中断) — 硬保留槽位, 不可合并, 不可丢弃
#   1     = 总线致命故障 — 硬保留槽位
#   2     = 普通中断 — 可合并, 可驱逐
#   3-98  = 遥测级 — 最低优先级
#   99    = 未知/野事件 — 默认降级
#
# NMI 槽位 (0, 1) 是内核物理保留区。
# 任何 register_event_type() 调用若 priority <= 1 → ValueError。
# ═══════════════════════════════════════════════════════════════

_BUILTIN_EVENTS: dict[str, int] = {
    "USER_ABORT":        0,   # NMI
    "LLM_TIMEOUT":       1,   # 总线故障
    "LLM_API_ERROR":     1,
    "TOOL_FAILURE":      2,   # 工具失败
    "POLICY_VIOLATION":  2,   # 安全拦截
    "BRIDGE_OVERLOAD":   2,   # 总线过载
    "TOOL_SUCCESS":      3,   # 工具成功
    "TOOL_RETRYING":    99,   # 遥测 — V11
}

# NMI 阈值 — priority <= 此值的事件享有硬保留槽位保护
NMI_PRIORITY_THRESHOLD: int = 1

# 未知事件的默认优先级
DEFAULT_PRIORITY: int = 99

# 普通事件最多占据的物理槽位数
def _normal_capacity(cfg: EventBridgeConfig) -> int:
    return cfg.max_buffer_size - cfg.reserved_slots


# ═══════════════════════════════════════════════════════════════
# 事件载体 — 狄拉克 δ 脉冲
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KernelEvent:
    """内核事件 — 离散脉冲。进入事件总线的最小单元。

    合并后 count > 1 表示 "同源事件发生了 N 次"。
    内核 ODE 积分器消费时: trust += η × count × (target − trust)。
    """
    type: str                   # "TOOL_FAILURE" | "LLM_TIMEOUT" | ...
    priority: int               # 偏序集的秩 — 越小越高
    lamport_ts: int             # 严格单调递增 — emit() 原子分配
    tool_name: str = ""         # 工具事件专用 — 合并分组键
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    count: int = 1              # 合并计数 — 保留 "多少次" 的语义信息
    unmergeable: bool = False   # True → 不参与合并（如 USER_ABORT）


# ═══════════════════════════════════════════════════════════════
# Event Bridge
# ═══════════════════════════════════════════════════════════════

class EventBridge:
    """事件总线桥接器 — NVIC 级。

    三种操作:
      emit(type, payload) → 同步入队（非阻塞）
        每次 emit 原子递增 Lamport 时钟 — 保证因果律
        物理硬保留槽位 — 普通事件不能占满整个缓冲区

      drain() → list[KernelEvent]
        每轮 kernel_step() 前调用
        等价类合并 → 按 (priority, lamport_ts) 排序 → 清空缓冲区
    """

    def __init__(self, config: EventBridgeConfig = EventBridgeConfig()):
        self.cfg = config
        self._buffer: list[KernelEvent] = []
        self._lamport: int = 0
        self._is_frozen: bool = False

        # 加载宪法 — 内置事件优先级表
        self._priority_map: dict[str, int] = dict(_BUILTIN_EVENTS)

    # ── 制宪会议 — 受控注册 (仅 Boot 阶段) ─────────────

    def register_event_type(self, name: str, priority: int) -> None:
        """注册自定义事件类型。仅 Boot 阶段可用（freeze 前）。

        物理锁死:
          priority <= NMI_PRIORITY_THRESHOLD → ValueError
          NMI 槽位 (0, 1) 是内核保留区，严禁插件染指。
          防止优先级反转和中断风暴。

        同名覆盖: 警告但不拒绝（允许 Track 升级遥测事件的优先级）。
        """
        if self._is_frozen:
            raise RuntimeError(
                "EventBus is frozen. Cannot register new event types after boot."
            )

        if priority <= NMI_PRIORITY_THRESHOLD:
            raise ValueError(
                f"Kernel Panic: Priority {priority} is reserved for NMI. "
                f"(USER_ABORT / LLM_FAULT). Event '{name}' rejected."
            )

        if name in self._priority_map:
            old = self._priority_map[name]
            logger.warning(
                f"Event type '{name}' priority changed: {old} → {priority}"
            )

        self._priority_map[name] = priority
        logger.debug(f"Event registered: {name} (priority={priority})")

    def freeze(self) -> None:
        """锁死事件表。Bootloader 完成初始化后必须调用。"""
        if not self._is_frozen:
            self._is_frozen = True
            logger.info(
                f"EventBus frozen. {len(self._priority_map)} event types locked "
                f"(builtin: {len(_BUILTIN_EVENTS)}, "
                f"custom: {len(self._priority_map) - len(_BUILTIN_EVENTS)})"
            )

    @property
    def is_frozen(self) -> bool:
        return self._is_frozen

    # ── 注入 — 同步，非阻塞 ──────────────────────────

    def emit(self, event_type: str, payload: MappingProxyType) -> None:
        """发射中断脉冲。同步调用，非阻塞。

        每次 emit 原子递增 Lamport 时钟:
          如果事件 A 在时间上先于事件 B → L(A) < L(B)
          即使在同一轮内 → 因果律通过 Lamport 严格单调保证

        物理硬保留槽位:
          普通事件 (priority > 1) 最多占用 28 个槽位
          保留 4 个槽位给高优事件 (priority ≤ 1)
        """
        # 原子递增 — 保证因果律
        self._lamport += 1

        priority = self._priority_map.get(event_type, DEFAULT_PRIORITY)
        tool_name = payload.get("tool", "")
        unmergeable = event_type in self.cfg.unmergeable_types

        event = KernelEvent(
            type=event_type,
            priority=priority,
            lamport_ts=self._lamport,
            tool_name=tool_name,
            metadata=payload,
            count=1,
            unmergeable=unmergeable,
        )

        is_high_pri = priority <= NMI_PRIORITY_THRESHOLD
        normal_cap = _normal_capacity(self.cfg)

        # 物理硬保留 — 普通事件不能占满全缓冲
        if not is_high_pri:
            normal_count = sum(
                1 for e in self._buffer if e.priority > NMI_PRIORITY_THRESHOLD
            )
            if normal_count >= normal_cap:
                if self.cfg.enable_priority_eviction:
                    self._evict_normal(event)
                return

        if len(self._buffer) < self.cfg.max_buffer_size:
            self._buffer.append(event)
        elif self.cfg.enable_priority_eviction:
            self._evict_and_insert(event)

    # ── 排空 — 每轮 kernel_step() 前调用 ───────────────

    def drain(self) -> list[KernelEvent]:
        """排空事件缓冲。每轮调用一次。

        返回:
          等价类合并后 → 按 (priority, lamport_ts) 排序的全序列表
          同优先级按因果序 — 先发生的事件先被内核消费
        """
        if not self._buffer:
            return []

        merged = self._merge_equivalent(self._buffer)
        self._buffer.clear()
        # 同优先级按 Lamport 排序 — 因果律保留
        return sorted(merged, key=lambda e: (e.priority, e.lamport_ts))

    # ── Lamport 时钟查询 ──────────────────────────────

    def get_current_lamport(self) -> int:
        """Harness 读取权威时钟 — 供 Adapter 的离散事件分配 Lamport。"""
        return self._lamport

    # ── 内部：等价类合并 ──────────────────────────────

    def _merge_equivalent(self, events: list[KernelEvent]) -> list[KernelEvent]:
        """合并等价事件。

        等价关系 ~: (type, tool_name) 相同
          → 合并为一个事件，count = 原始事件数
          → lamport_ts 取最早的时间戳
          → 不可合并事件 (USER_ABORT) 保持独立

        内核 ODE 积分器消费时:
          trust += η × event.count × (target − trust)
        """
        groups: dict[tuple, KernelEvent] = {}

        for evt in events:
            if evt.unmergeable:
                key = (evt.type, evt.tool_name, evt.lamport_ts)  # 唯一键
                groups[key] = evt
            else:
                key = (evt.type, evt.tool_name)
                if key in groups:
                    merged = groups[key]
                    groups[key] = KernelEvent(
                        type=merged.type,
                        priority=merged.priority,
                        lamport_ts=min(merged.lamport_ts, evt.lamport_ts),
                        tool_name=merged.tool_name,
                        metadata=merged.metadata,
                        count=merged.count + evt.count,
                        unmergeable=False,
                    )
                else:
                    groups[key] = evt

        return list(groups.values())

    # ── 内部：优先级驱逐 ──────────────────────────────

    def _evict_normal(self, event: KernelEvent) -> None:
        """在普通事件槽位已满时尝试驱逐另一个普通事件。

        只驱逐 priority > 1 的事件。
        不碰硬保留槽位。
        """
        candidates = [
            (i, e) for i, e in enumerate(self._buffer)
            if e.priority > NMI_PRIORITY_THRESHOLD
        ]
        if not candidates:
            return  # 无普通事件可驱逐

        min_idx, min_evt = max(candidates, key=lambda x: x[1].priority)

        if event.priority < min_evt.priority:
            self._buffer[min_idx] = event

    def _evict_and_insert(self, event: KernelEvent) -> None:
        """全缓冲区驱逐 — 可踢任何可驱逐的事件。

        硬保留槽位内的高优事件 (priority ≤ 1) 不可被踢。
        """
        candidates = [
            (i, e) for i, e in enumerate(self._buffer)
            if e.priority > NMI_PRIORITY_THRESHOLD
        ]
        if not candidates:
            return  # 全部是高优事件 — 无法驱逐，丢弃新事件

        min_idx, min_evt = max(candidates, key=lambda x: x[1].priority)

        if event.priority < min_evt.priority:
            self._buffer[min_idx] = event
