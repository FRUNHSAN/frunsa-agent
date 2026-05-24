# llm/openai.py
"""
OpenAI / 兼容 OpenAI 协议的模型客户端（如 DeepSeek、Moonshot、本地 vLLM）
"""

import os
from typing import Optional
from .base import BaseLLMClient

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

class OpenAIClient(BaseLLMClient):
    """
    调用 OpenAI 或兼容 OpenAI API 的模型
    需要设置环境变量 OPENAI_API_KEY 和 OPENAI_BASE_URL（可选）
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.3
    ):
        if not HAS_OPENAI:
            raise ImportError(
                "openai 未安装。请运行: pip install openai"
            )
        
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        if not self.api_key:
            raise ValueError(
                "未提供 OpenAI API Key。请设置环境变量 OPENAI_API_KEY "
                "或在初始化时传入 api_key 参数。"
            )
        
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=1024
            )
            return response.choices[0].message.content.strip()
        
        except Exception as e:
            raise RuntimeError(f"调用 OpenAI 模型失败: {e}") from e