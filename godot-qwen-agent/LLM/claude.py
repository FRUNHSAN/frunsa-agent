# llm/claude.py
"""
Anthropic Claude 客户端（Claude 3.5 Sonnet / Haiku / Opus）
需设置 ANTHROPIC_API_KEY
"""

import os
from typing import Optional
from .base import BaseLLMClient

try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

class ClaudeClient(BaseLLMClient):
    """
    调用 Anthropic Claude 系列模型
    需要设置环境变量 ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: Optional[str] = None,
        temperature: float = 0.3
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
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        
        except Exception as e:
            raise RuntimeError(f"调用 Claude 模型失败: {e}") from e