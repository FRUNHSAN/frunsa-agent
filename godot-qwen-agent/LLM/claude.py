# llm/claude.py
"""
Anthropic Claude 客户端（Claude 3.5 Sonnet / Haiku / Opus）
需设置 ANTHROPIC_API_KEY

Phase 22: 新增 generate_with_tools() 支持 Anthropic tool use API。
"""

from __future__ import annotations

import os
from typing import List, Optional

from .base import BaseLLMClient, LLMResponse

try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    from anthropic.types import ToolUseBlock
    HAS_TOOL_TYPES = True
except ImportError:
    HAS_TOOL_TYPES = False


class ClaudeClient(BaseLLMClient):
    """
    调用 Anthropic Claude 系列模型
    需要设置环境变量 ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: Optional[str] = None,
        temperature: float = 0.3,
    ):
        if not HAS_ANTHROPIC:
            raise ImportError(
                "anthropic 未安装。请运行: pip install anthropic"
            )

        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "未提供 Anthropic API Key。请设置环境变量 ANTHROPIC_API_KEY "
                "或在初始化时传入 api_key 参数。"
            )

        self.client = Anthropic(api_key=self.api_key)

    def generate(self, prompt: str) -> str:
        """基础文本生成。向后兼容。"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

        except Exception as e:
            raise RuntimeError(f"调用 Claude 模型失败: {e}") from e

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 Claude，支持 tool use。

        向 Anthropic Messages API 发送 tools 参数。
        如果 Claude 返回 TextBlock → type="text"
        如果 Claude 返回 ToolUseBlock → type="tool_call"

        Args:
            prompt: 用户提示
            tools:  Anthropic 原生 tool 格式列表:
                    [{"name": "...", "description": "...",
                      "input_schema": {"type": "object", ...}}]

        Returns:
            LLMResponse
        """
        if not tools:
            return LLMResponse.from_text(self.generate(prompt))

        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": 1024,
                "temperature": self.temperature,
                "messages": [{"role": "user", "content": prompt}],
                "tools": tools,
            }

            response = self.client.messages.create(**kwargs)

            # Check each content block for tool use
            for block in response.content:
                if block.type == "tool_use":
                    return LLMResponse.from_tool_call(
                        name=block.name,
                        arguments=dict(block.input) if block.input else {},
                        tool_id=block.id if hasattr(block, "id") else "",
                        raw=response,
                    )

            # No tool_use block found → text response
            text = response.content[0].text if response.content else ""
            return LLMResponse.from_text(text.strip(), raw=response)

        except Exception as e:
            raise RuntimeError(
                f"调用 Claude 模型 (with tools) 失败: {e}"
            ) from e
