"""
V9 Telemetry Bus — 遥测总线 (CoreSight 级)

硬件对标: ARM CoreSight ATB (Advanced Trace Bus) + TPIU (Trace Port Interface Unit)
职责: 收集内核决策轨迹 + Harness 反馈 → 异步落盘 → RL 离线训练数据源

数学框架:
  信息论 — (s, a, r) 三元组 = 决策景观的采样点
  RL 训练 = 从采样点重建价值函数 V(s) 和策略 π(a|s)

协议依赖（全部冻结）:
  TraceRecord — (state_vector, decision_trace, action, feedback) 四元组
  TelemetryConfig — 队列深度、落盘频率、存储路径

关键设计决策:
  - log() 非阻塞入队 + 深拷贝快照 — Trace 丢好过 System Halt
  - 全链路离线 — 序列化(CPU) + 落盘(I/O) 全在线程池
  - 文件级 threading.Lock — 单进程线程池互斥
  - 多进程互斥 — V13 用 filelock 库（跨平台），非 V9 的 fcntl
  - JSONL 格式 — RL 脚本直接消费
  - 内核不感知 — 遥测总线的存在对 kernel_step() 透明
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import threading
from dataclasses import dataclass, field
from types import MappingProxyType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TelemetryConfig:
    """遥测总线物理参数。"""
    queue_depth: int = 1000
    flush_interval_ms: int = 100
    batch_size: int = 50                    # 攒够就刷新
    storage_path: str = "./telemetry/traces.jsonl"


# ═══════════════════════════════════════════════════════════════
# Trace Record — (s, a, r) 三元组 + 审计元数据
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TraceRecord:
    """单轮决策轨迹 — RL 训练的最小数据单元。

    s (state):  state_vector (16 维 float) — 内核决策前的状态
    a (action): next_action + gate_id
    r (reward): 用户反馈信号 — Harness 自动计算
    """
    round_count: int
    timestamp: float
    kernel_version: str = "V9.0.0"

    # s — 状态
    state_vector: tuple[float, ...] = ()

    # a — 动作
    next_action: str = ""
    gate_triggered: str = ""
    decision_trace: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    # r — 奖励（自动标注）
    reward: float = 0.0
    reward_source: str = ""
    user_edit_distance: float = 0.0
    user_continued: bool = False
    code_copied: bool = False

    # 总线摘要
    llm_calls: int = 0
    llm_total_latency_ms: float = 0.0
    tool_calls: int = 0
    tool_failures: int = 0
    total_latency_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════
# Telemetry Bus
# ═══════════════════════════════════════════════════════════════

class TelemetryBus:
    """遥测总线 — ARM CoreSight 级。

    log() → 队列 → 后台协程 → 线程池(序列化+落盘) → JSONL
    内核不感知。
    """

    def __init__(self, config: TelemetryConfig = TelemetryConfig()):
        self.cfg = config
        self._queue: asyncio.Queue[TraceRecord | None] = asyncio.Queue(
            maxsize=config.queue_depth
        )
        self._write_lock = threading.Lock()  # 线程池内互斥
        self._writer_task: asyncio.Task | None = None
        self._started = False

    # ── 生命周期 ──────────────────────────────────────

    async def start(self) -> None:
        """启动后台落盘协程。Harness 初始化时调用。"""
        if self._started:
            return
        self._started = True
        self._writer_task = asyncio.create_task(self._background_writer())
        logger.info(f"Telemetry Bus 已启动 — {self.cfg.storage_path}")

    async def stop(self) -> None:
        """停止后台协程。等待最后的批次落盘。"""
        if not self._started:
            return
        self._started = False
        await self._queue.put(None)  # 哨兵
        if self._writer_task:
            await self._writer_task
        logger.info("Telemetry Bus 已停止")

    # ── 记录 — 同步，非阻塞 ──────────────────────────

    def log(self, record: TraceRecord) -> None:
        """记录单轮决策轨迹。非阻塞入队。

        深拷贝 decision_trace — 切断与内核可变对象的引用。
        队列满 → 丢弃。ARM CoreSight 同策略。
        """
        # 深拷贝 — 防止内核/RL 后续修改嵌套对象
        frozen_trace = MappingProxyType(
            copy.deepcopy(dict(record.decision_trace))
        )
        record = TraceRecord(
            round_count=record.round_count,
            timestamp=record.timestamp,
            kernel_version=record.kernel_version,
            state_vector=record.state_vector,
            next_action=record.next_action,
            gate_triggered=record.gate_triggered,
            decision_trace=frozen_trace,
            reward=record.reward,
            reward_source=record.reward_source,
            user_edit_distance=record.user_edit_distance,
            user_continued=record.user_continued,
            code_copied=record.code_copied,
            llm_calls=record.llm_calls,
            llm_total_latency_ms=record.llm_total_latency_ms,
            tool_calls=record.tool_calls,
            tool_failures=record.tool_failures,
            total_latency_ms=record.total_latency_ms,
        )

        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            logger.warning("Telemetry queue full — trace dropped")

    # ── 后台协程 ─────────────────────────────────────

    async def _background_writer(self) -> None:
        """批量消费队列 + 全链路线程池落盘。"""
        batch: list[TraceRecord] = []

        while True:
            try:
                record = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self.cfg.flush_interval_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                if batch:
                    await self._flush(batch)
                    batch = []
                continue

            if record is None:
                if batch:
                    await self._flush(batch)
                return

            batch.append(record)

            if len(batch) >= self.cfg.batch_size:
                await self._flush(batch)
                batch = []

    async def _flush(self, batch: list[TraceRecord]) -> None:
        """全链路离线 — 序列化(CPU) + 落盘(I/O) 全在线程池。"""
        try:
            await asyncio.to_thread(self._sync_serialize_and_write, batch)
        except Exception:
            logger.exception("Telemetry 落盘失败 — 批次丢弃")

    def _sync_serialize_and_write(self, batch: list[TraceRecord]) -> None:
        """线程池内执行 — 序列化 + 加锁写磁盘。"""
        lines = "\n".join(
            json.dumps(self._record_to_dict(r), ensure_ascii=False)
            for r in batch
        ) + "\n"

        with self._write_lock:
            with open(self.cfg.storage_path, "a", encoding="utf-8") as f:
                f.write(lines)
                f.flush()

    # ── 序列化 ───────────────────────────────────────

    @staticmethod
    def _record_to_dict(r: TraceRecord) -> dict:
        return {
            "round": r.round_count,
            "timestamp": r.timestamp,
            "kernel_version": r.kernel_version,
            "state_vector": list(r.state_vector),
            "action": r.next_action,
            "gate": r.gate_triggered,
            "trace": dict(r.decision_trace),
            "reward": r.reward,
            "reward_source": r.reward_source,
            "user_edit_distance": r.user_edit_distance,
            "user_continued": r.user_continued,
            "code_copied": r.code_copied,
            "llm_calls": r.llm_calls,
            "llm_total_latency_ms": r.llm_total_latency_ms,
            "tool_calls": r.tool_calls,
            "tool_failures": r.tool_failures,
            "total_latency_ms": r.total_latency_ms,
        }
