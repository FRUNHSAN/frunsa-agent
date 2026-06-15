"""
V9.1 RealTrackC — Tool Execution → Critic 管道（无 Planning）

硬件对标: APB 总线上的 DMA 描述符链执行器
职责: 执行内核批准的 tool_calls → Critic 评审 → 重试直到通过或耗尽

关键设计（红队强制）:
  - 无 Planning LLM 调用 — 内核已决策 EXECUTE_TOOL + 提供 tool_calls
  - Critic 阈值 = policy.safety_threshold — 不硬编码 0.70
  - 工具调用异常隔离 — 结构化 error 对象
  - 零自然语言泄漏到内核 — emit 用 MappingProxyType
"""

from __future__ import annotations

import json
import re
import time
import logging
from types import MappingProxyType

logger = logging.getLogger(__name__)


class RealTrackC:
    """Tool Execution → Critic — with retry loop.

    协议: TrackPipeline
      async run(user_text, policy, tool_calls, round_count) → dict

    架构边界:
      - 不调 llm://planning — 内核已决策
      - 透传 DataPolicy 给 Critic（LLM Bridge 自动翻译）
      - 工具失败 → 结构化 error + TOOL_FAILURE 事件
      - Critic 评分 < policy.safety_threshold → 重试
    """

    def __init__(self, llm_bridge, tool_bridge, event_bridge, max_retries=2):
        self.llm = llm_bridge
        self.tool = tool_bridge
        self.event = event_bridge
        self.max_retries = max_retries

    async def run(
        self, user_text: str, policy, tool_calls: tuple, round_count: int,
    ) -> dict:
        """执行一次 Track C 管道。

        Returns:
            {"text": str, "track": "C"}
        """
        tool_results: list[dict] = []
        t0 = time.perf_counter()
        critic = None
        attempt = 0

        for attempt in range(self.max_retries + 1):
            # ── Step 1: Tool Execution（仅首轮执行，重试不改工具结果）──
            if attempt == 0:
                tool_results = await self._execute_tools(
                    tool_calls, policy, round_count)

            # ── Step 2: Critic — policy 透传 ──
            critic = await self.llm.execute(
                target="llm://critic",
                context={
                    "user_query": user_text,
                    "tool_results": [
                        tr.get("result", tr.get("error", ""))
                        for tr in tool_results
                    ],
                },
                policy=policy,
                op_id=f"critic_{round_count}_{attempt}",
            )

            # ── Step 3: Score check using kernel's dynamic threshold ──
            score = _parse_critic_score(critic)
            if score >= policy.safety_threshold:
                break

        # ── Emit latency telemetry ──
        latency_ms = (time.perf_counter() - t0) * 1000
        self.event.emit("TRACK_C_LATENCY", MappingProxyType({
            "latency_ms": latency_ms,
            "attempts": attempt + 1,
        }))

        text = ""
        if critic is not None:
            text = critic.payload.get("text", "")
        return {"text": text, "track": "C"}

    async def _execute_tools(
        self, tool_calls: tuple, policy, round_count: int,
    ) -> list[dict]:
        """执行内核批准的所有工具调用。每个失败被结构化捕获。"""
        results = []

        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            if not tool_name:
                continue

            try:
                resp = await self.tool.execute(
                    target=f"tool://{tool_name}",
                    params=tc.get("params", {}),
                    policy=policy,
                    op_id=f"tool_{round_count}_{tool_name}",
                )
                results.append({
                    "tool": tool_name,
                    "result": resp.payload.get("result", str(resp.payload)),
                    "error": None,
                })

            except Exception as e:
                results.append({
                    "tool": tool_name,
                    "result": None,
                    "error": str(e),
                })
                self.event.emit("TOOL_FAILURE", MappingProxyType({
                    "tool": tool_name,
                    "op_id": f"tool_{round_count}_{tool_name}",
                    "error": str(e),
                }))

        return results


def _parse_critic_score(resp) -> float:
    """从 Critic 响应中提取评分。

    Critic 输出 JSON: {"pass": bool, "score": float, "reason": "..."}
    """
    text = resp.payload.get("text", "")
    try:
        m = re.search(r'\{[^}]+\}', text)
        if m:
            data = json.loads(m.group())
            if "score" in data:
                return float(data["score"])
            if "pass" in data:
                return 1.0 if data["pass"] else 0.0
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return 0.50
