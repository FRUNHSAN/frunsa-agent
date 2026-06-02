# llm/qwen.py
"""
Qwen (通义千问) 客户端 — 基于 DashScope 兼容 OpenAI 接口。

Phase 22: 新增 generate_with_tools() 支持 function calling。
DashScope 兼容模式: https://dashscope.aliyuncs.com/compatible-mode/v1

环境变量:
  QWEN_API_KEY 或 DASHSCOPE_API_KEY

免费额度 (Coding Plan):
  Base URL: https://coding.dashscope.aliyuncs.com/v1
  API Key 格式: sk-sp-xxxxxx
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from .base import BaseLLMClient, LLMResponse

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class QwenClient(BaseLLMClient):
    """调用通义千问模型（DashScope 兼容 OpenAI 接口）。

    推荐模型:
      qwen3-max   — 旗舰，性能均衡
      qwen-plus   — 性价比
      qwen-turbo  — 轻量快速
    """

    # Default base URL for DashScope compatible mode
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    CODING_PLAN_URL = "https://coding.dashscope.aliyuncs.com/v1"

    def __init__(
        self,
        model: str = "qwen3-max",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        if not HAS_OPENAI:
            raise ImportError(
                "openai 未安装。请运行: pip install openai"
            )

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.api_key = (
            api_key
            or os.getenv("QWEN_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "未提供 Qwen API Key。请设置环境变量 QWEN_API_KEY "
                "或 DASHSCOPE_API_KEY，或在初始化时传入 api_key 参数。"
            )

        self.base_url = base_url or os.getenv(
            "QWEN_BASE_URL", self.DASHSCOPE_BASE_URL
        )
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def generate(self, prompt: str) -> str:
        """基础文本生成。向后兼容。"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip() or ""

        except Exception as e:
            raise RuntimeError(f"调用 Qwen 模型失败: {e}") from e

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用千问，支持 function calling。

        千问兼容 OpenAI tool calling 格式。当模型决定调用工具时，
        返回 type="tool_call" 的 LLMResponse；否则返回 type="text"。

        Args:
            prompt: 用户提示（可以是 system + user 组合）
            tools:  OpenAI 原生 tool 格式列表:
                    [{"type": "function", "function": {
                        "name": "...", "description": "...",
                        "parameters": {"type": "object", ...}
                    }}]

        Returns:
            LLMResponse
        """
        if not tools:
            return LLMResponse.from_text(self.generate(prompt))

        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
                "tools": tools,
            }

            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message

            # Check for tool calls
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                func = tool_call.function

                # OpenAI returns arguments as a JSON string
                try:
                    arguments = json.loads(func.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}

                return LLMResponse.from_tool_call(
                    name=func.name,
                    arguments=arguments,
                    tool_id=tool_call.id or "",
                    raw=response,
                )

            # Plain text response
            return LLMResponse.from_text(
                message.content.strip() or "",
                raw=response,
            )

        except Exception as e:
            raise RuntimeError(
                f"调用 Qwen 模型 (with tools) 失败: {e}"
            ) from e
