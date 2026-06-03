# llm/deepseek.py
"""
DeepSeek 客户端 — 兼容 OpenAI 接口。

环境变量: DEEPSEEK_API_KEY
模型: deepseek-chat (V3), deepseek-reasoner (R1)
"""

from __future__ import annotations

import json
import os
from typing import Optional

from .base import BaseLLMClient, LLMResponse

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class DeepSeekClient(BaseLLMClient):
    """调用 DeepSeek 系列模型（兼容 OpenAI 接口）。"""

    BASE_URL = "https://api.deepseek.com/v1"

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ):
        if not HAS_OPENAI:
            raise ImportError("openai 未安装。请运行: pip install openai")

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "未提供 DeepSeek API Key。请设置环境变量 DEEPSEEK_API_KEY"
            )
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", self.BASE_URL)
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip() or ""
        except Exception as e:
            raise RuntimeError(f"调用 DeepSeek 模型失败: {e}") from e

    def generate_stream(self, prompt: str):
        """Stream response chunks. Yields str chunks as they arrive."""
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"\n[Stream error: {e}]"

    def generate_with_tools(
        self, prompt: str, tools: list[dict] | None = None,
    ) -> LLMResponse:
        if not tools:
            return LLMResponse.from_text(self.generate(prompt))

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
                tools=tools,
            )
            message = response.choices[0].message
            if message.tool_calls:
                tc = message.tool_calls[0]
                func = tc.function
                try:
                    arguments = json.loads(func.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                return LLMResponse.from_tool_call(
                    name=func.name, arguments=arguments,
                    tool_id=tc.id or "", raw=response,
                )
            return LLMResponse.from_text(
                message.content.strip() or "", raw=response,
            )
        except Exception as e:
            raise RuntimeError(f"调用 DeepSeek (with tools) 失败: {e}") from e
