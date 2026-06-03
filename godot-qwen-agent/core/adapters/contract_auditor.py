"""ContractAuditor — PLAN5 System 2: async LLM contract signature extractor.

Runs in background every N rounds. Feeds conversation history to DeepSeek
with a strict JSON Schema, asking it to extract implicit contract modification
signals. Does NOT block the main interaction loop.

Design:
  - Async: threading.Thread, non-blocking
  - Strict: JSON Schema forces LLM to be a "cold contract auditor"
  - World knowledge: LLM understands "2 AM + short replies = exhaustion"
"""

from __future__ import annotations

import json
import threading
from typing import Any


AUDITOR_SYSTEM_PROMPT = """你是一个冷酷的 AI 契约审计员。你的任务是从用户对话历史中提取"隐式契约修改信号"。
不要分析情绪，不要写小作文，不要给建议。你只关注"约束条件"的改变。

如果用户行为暗示当前 Agent 的行为模式需要调整，输出 JSON。如果没有发现，输出 {"has_proposal": false}。

【世界知识注入】：
- 深夜(23:00-05:00) + 用户话语简短 → 用户疲惫，Agent 应剥夺废话，直接给结果
- 连续追问同一概念 → Agent 当前解释维度失败，需切换策略（如理论→代码示例）
- 用户说"随便/都行"但有省略号或停顿 → 用户有顾虑未表达，需暂停执行主动探寻
- 用户长时间沉默后突然大量输出 → 用户在整理思路，不要打断
- 用户连续使用负面词汇 → 降低 Agent 的主动建议频率

【输出 Schema】：
{"has_proposal": false}  或者
{
  "has_proposal": true,
  "proposal": {
    "trigger_condition": "string (例如: user_exhausted_at_midnight)",
    "target_blueprint_key": "string (例如: response_verbose_level)",
    "old_value": "string (当前值，如果未知填 unknown)",
    "new_value": "string (建议修改的新值)",
    "human_reason": "string (一句话，必须包含对'人性'的洞察)"
  }
}"""


class ContractAuditor:
    """Async System 2: LLM-powered contract signature extraction.

    Usage:
        auditor = ContractAuditor(llm_client)
        auditor.audit_async(history, current_blueprint, current_time, callback)
        # callback receives (proposal_dict | None) when LLM responds
    """

    def __init__(self, llm_client: Any, interval: int = 10) -> None:
        self._llm = llm_client
        self._interval = interval
        self._call_count = 0

    def should_audit(self, round_count: int) -> bool:
        """Check if this round triggers an audit."""
        return round_count > 0 and round_count % self._interval == 0

    def audit_async(
        self,
        history: list[str],
        current_blueprint: dict,
        current_time: str = "",
        callback: Any = None,
    ) -> None:
        """Launch async audit in a background thread.

        Args:
            history:           Last N rounds of user messages
            current_blueprint: Current contract fields
            current_time:      ISO timestamp or "02:30 AM" style
            callback:          Called with (proposal_dict | None) on completion
        """
        self._call_count += 1

        def _run():
            proposal = self._audit_sync(history, current_blueprint, current_time)
            if callback:
                callback(proposal)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

    def _audit_sync(
        self, history: list[str], blueprint: dict, current_time: str,
    ) -> dict | None:
        """Synchronous audit — called from background thread."""
        user_prompt = (
            f"当前时间: {current_time or '未知'}\n"
            f"当前 Blueprint 状态: {json.dumps(blueprint, ensure_ascii=False)}\n"
            f"最近 {len(history)} 轮用户输入:\n"
        )
        for i, msg in enumerate(history, 1):
            user_prompt += f"  Round {i}: {msg}\n"
        user_prompt += "\n请分析是否有隐式契约修改信号。严格按 JSON Schema 输出。"

        full_prompt = f"{AUDITOR_SYSTEM_PROMPT}\n\n{user_prompt}"

        try:
            raw = self._llm.generate(full_prompt)
            # Extract JSON
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            result = json.loads(raw.strip())
        except Exception:
            return None

        if result.get("has_proposal") and "proposal" in result:
            return result["proposal"]
        return None

    @property
    def interval(self) -> int:
        return self._interval

    @property
    def call_count(self) -> int:
        return self._call_count
