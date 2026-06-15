"""
V9 Harness — 主编排器 (Bus Matrix + Session Manager)

硬件对标: SoC 总线矩阵 (Bus Matrix) + DMA 控制器
职责: 连接内核、Observer、适配层、四条总线、Track C 管道

数据流:
  UI → Observer → Adapter → Kernel → ControlFrame
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
        GENERATE_RESPONSE         EXECUTE_TOOL               WAIT
        LLM Bus (Synthesis)       Track C 管道              降级输出
              │                  (LLM + Tool Bus)              │
              └────────────────────────┼────────────────────────┘
                                       ▼
                                  response_packet → UI
                                  (content + metadata)

关键设计决策:
  - Harness 不决策 — 内核决定 next_action
  - Harness 不产文本 — Synthesis LLM 产文本
  - Harness 不调工具 — Tool Bus 调工具
  - Harness 只做四件事: 组装、路由、计时、反馈
"""

from __future__ import annotations

import time
import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from types import MappingProxyType

from protocol.v9_types import KernelInput, KernelState, NextAction
from mainboard.bus.telemetry import TraceRecord
from mainboard.track.track_c import RealTrackC

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Harness 配置与输出
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HarnessConfig:
    expected_latency_ms: float = 2000.0

@dataclass(frozen=True)
class ResponsePacket:
    """Harness → UI 的最终载荷。内核不感知这个结构。"""
    content: str = ""
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


# ═══════════════════════════════════════════════════════════════
# Harness
# ═══════════════════════════════════════════════════════════════

class Harness:
    """V9 Agent Harness — 主循环编排器。

    持有: Observer, Adapter, Kernel, LLMBridge, ToolBridge,
          EventBridge, TelemetryBus, Track C 管道。

    不持有: UI, LLM Provider, 工具实现。
    """

    def __init__(
        self,
        observer,
        adapter,
        kernel,
        llm_bridge,
        tool_bridge,
        event_bridge,
        telemetry,
        track_c=None,
        config: HarnessConfig = HarnessConfig(),
    ):
        self.observer = observer
        self.adapter = adapter
        self.kernel = kernel
        self.llm = llm_bridge
        self.tool = tool_bridge
        self.event = event_bridge
        self.telemetry = telemetry
        self.track_c = track_c or RealTrackC(llm_bridge, tool_bridge, event_bridge)
        self.cfg = config

        # 运行时状态
        self._kernel_state = None
        self._adapter_state = None
        self._last_step_time: float = 0.0   # Phase 4 打点 — 不含 execute 时间
        self._round_count: int = 0

    # ── 主循环 ────────────────────────────────────────

    async def step(self, user_text: str) -> ResponsePacket:
        """执行一轮 Agent 交互。永远返回 ResponsePacket — 不抛异常。"""
        t0 = time.perf_counter()
        self._round_count += 1

        # ═══════════════════════════════════════════════════
        # Phase 1: Observer
        # ═══════════════════════════════════════════════════
        obs = await self.observer.observe(user_text)

        # ═══════════════════════════════════════════════════
        # Phase 2: Adapter
        # ═══════════════════════════════════════════════════
        prev_raw_trust = (
            self._kernel_state.prev_raw_state_vector[0]
            if self._kernel_state else 0.30
        )
        prev_raw_e_t = (
            self._kernel_state.prev_raw_state_vector[1]
            if self._kernel_state else 0.0
        )
        current_timestamp = time.time()

        sv, signals, adapter_events, self._adapter_state = self.adapter.step(
            adapter_state=self._adapter_state,
            confidence=obs.confidence,
            text_tokens=obs.text_tokens,
            is_social=obs.is_social_query,
            escalated=obs.escalation_flag,
            relaxed=obs.relaxation_flag,
            discrete_events=obs.discrete_events,
            prev_raw_trust=prev_raw_trust,
            prev_raw_e_t=prev_raw_e_t,
            current_timestamp=current_timestamp,
            expected_latency_ms=self.cfg.expected_latency_ms,
            base_lamport=self.event.get_current_lamport(),  # 单一时钟源 — EventBridge
        )

        # ═══════════════════════════════════════════════════
        # Phase 3: 事件合并
        # ═══════════════════════════════════════════════════
        bridge_events = self.event.drain()
        all_events = tuple(itertools.chain(adapter_events, bridge_events))

        # ═══════════════════════════════════════════════════
        # Phase 4: 内核 — dt 在 kernel_step 之前打点
        # ═══════════════════════════════════════════════════
        # dt_ms = 从上轮内核决策结束到本轮内核决策开始
        # 不含 execute() 的耗时 — 那是执行期，不是环境演化期
        current_perf = time.perf_counter()
        dt_ms = (
            (current_perf - self._last_step_time) * 1000.0
            if self._last_step_time > 0 else 0.0
        )
        self._last_step_time = current_perf

        kernel_input = KernelInput(
            state_vector=sv,
            event_queue=all_events,
            dt_ms=dt_ms,
        )

        control_frame, self._kernel_state = self.kernel.step(
            self._kernel_state,
            kernel_input,
            signals,
        )

        # ═══════════════════════════════════════════════════
        # Phase 5: 执行 — 硬件级异常隔离
        # ═══════════════════════════════════════════════════
        try:
            response = await self._execute(control_frame, obs, user_text)
        except Exception as e:
            logger.exception("Harness Execute 阶段崩溃 — 降级为兜底响应")
            self.event.emit("BRIDGE_OVERLOAD", MappingProxyType({
                "reason": str(e),
                "phase": "execute",
            }))
            response = ResponsePacket(
                content="系统遇到内部错误，正在恢复...",
                metadata=MappingProxyType({
                    "gate": "HARNESS_CRASH_FALLBACK",
                }),
            )

        # ═══════════════════════════════════════════════════
        # Phase 6: 遥测
        # ═══════════════════════════════════════════════════
        reward = self._compute_reward(user_text, response)
        self.telemetry.log(TraceRecord(
            round_count=self._round_count,
            timestamp=current_timestamp,
            state_vector=sv.data,
            next_action=control_frame.next_action.value,
            gate_triggered=control_frame.trace.gate_id,
            decision_trace=control_frame.trace.operands,
            reward=reward,
            reward_source="heuristic",
            total_latency_ms=(time.perf_counter() - t0) * 1000.0,
        ))

        return response

    # ── 工具解析 — 用户意图 → 工具列表 ───────────────

    async def _resolve_tools(self, user_text: str, policy) -> tuple[dict, ...]:
        """翻译用户意图 → 具体工具列表。Harness 层桥接。

        内核决定"该不该走工具路径"（SHOULD we go?）。
        Harness 翻译"调哪个工具"（WHICH tools?）。

        不是 Planning——不决定"该不该"，只做路径解析。
        """
        resp = await self.llm.execute(
            target="llm://tool_resolver",
            context={"user_query": user_text},
            policy=policy,
            op_id=f"resolve_{self._round_count}",
        )
        return _parse_tool_calls(resp.payload.get("text", ""))

    # ── 执行分叉 ──────────────────────────────────────

    async def _execute(self, frame, obs, user_text: str) -> ResponsePacket:
        """根据 next_action 分叉。"""

        if frame.next_action == NextAction.GENERATE_RESPONSE:
            resp = await self.llm.execute(
                target="llm://synthesis",
                context={
                    "user_query": user_text,
                    "history": [],
                    "tool_results": [],
                },
                policy=frame.data_policy,
                op_id=f"syn_{self._round_count}",
            )
            return ResponsePacket(
                content=resp.payload.get("text", ""),
                metadata=MappingProxyType({
                    "gate": frame.trace.gate_id,
                    "latency_ms": resp.latency_ms,
                }),
            )

        elif frame.next_action == NextAction.EXECUTE_TOOL:
            # 内核只决定"该走工具路径"——不决定"调哪个工具"
            # Harness 翻译用户意图 → 具体工具列表
            tool_calls = frame.tool_calls or await self._resolve_tools(
                user_text, frame.data_policy)
            result = await self.track_c.run(
                user_text=user_text,
                policy=frame.data_policy,
                tool_calls=tool_calls,
                round_count=self._round_count,
            )
            return ResponsePacket(
                content=result.get("text", ""),
                metadata=MappingProxyType({
                    "gate": frame.trace.gate_id,
                    "track": "C",
                }),
            )

        else:  # WAIT
            return ResponsePacket(
                content="",
                metadata=MappingProxyType({
                    "gate": frame.trace.gate_id,
                    "status": "WAIT",
                    "reason": frame.trace.reason,
                }),
            )

    # ── 奖励计算 — V9.0 简版占位 ──────────────────────

    def _compute_reward(self, _user_text: str, _response: ResponsePacket) -> float:
        return 0.0  # V10 由 RL reward model 替代


# ═══════════════════════════════════════════════════════════════
# 工具调用解析器 — LLM 文本 → tool_calls
# ═══════════════════════════════════════════════════════════════

def _parse_tool_calls(text: str) -> tuple[dict, ...]:
    """从 LLM 输出中提取工具调用列表。

    LLM 输出 JSON: {"tools": [{"tool": "search_web", "params": {...}}, ...]}
    或纯文本 → 返回空元组。
    """
    import json, re
    try:
        m = re.search(r'\{.*"tools"\s*:\s*\[.*\]\s*\}', text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            tools = data.get("tools", [])
            if isinstance(tools, list):
                return tuple(t for t in tools if isinstance(t, dict) and t.get("tool"))
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return ()


# ═══════════════════════════════════════════════════════════════
# 默认 Track C 管道（简版 — 可注入替换）
# ═══════════════════════════════════════════════════════════════

class _DefaultTrackC:
    """Track C 管道的默认实现。Planning → Tool → Critic。"""

    def __init__(self, llm_bridge, tool_bridge, event_bridge):
        self.llm = llm_bridge
        self.tool = tool_bridge
        self.event = event_bridge

    async def run(
        self, user_text: str, policy, tool_calls: tuple, round_count: int
    ) -> dict:
        """执行一次 Track C 管道。"""

        plan_resp = await self.llm.execute(
            target="llm://planning",
            context={"user_query": user_text},
            policy=policy,
            op_id=f"plan_{round_count}",
        )
        if plan_resp.status != "OK":
            return {"text": plan_resp.payload.get("text", "规划失败"), "track": "C_degraded"}

        tool_results = []
        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            if not tool_name:
                continue
            resp = await self.tool.execute(
                target=f"tool://{tool_name}",
                params=tc.get("params", {}),
                policy=policy,
                op_id=f"tool_{round_count}_{tool_name}",
            )
            tool_results.append(resp.payload.get("result", str(resp.payload)))

        critic_resp = await self.llm.execute(
            target="llm://critic",
            context={"user_query": user_text, "tool_results": tool_results},
            policy=policy,
            op_id=f"critic_{round_count}",
        )

        text = critic_resp.payload.get("text", "") if critic_resp.status == "OK" else ""
        if not text and plan_resp.status == "OK":
            text = plan_resp.payload.get("text", "")
        return {"text": text, "track": "C"}
