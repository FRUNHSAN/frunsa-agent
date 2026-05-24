# llm/qwen.py
"""
Qwen (通义千问) 客户端实现，基于 dashscope SDK
"""

import os
from typing import Optional
from .base import BaseLLMClient

try:
    from dashscope import Generation
    HAS_DASHSCOPE = True
except ImportError:
    HAS_DASHSCOPE = False

class QwenClient(BaseLLMClient):
    """
    调用阿里云 DashScope 的 Qwen 系列模型
    需要设置环境变量 DASHSCOPE_API_KEY
    """

    def __init__(self, model="qwen-max", api_key=None, temperature=0.3, timeout=None, **kwargs):
        if not HAS_DASHSCOPE:
            raise ImportError("dashscope 未安装。请运行: pip install dashscope")
        
        # 强制使用环境变量（最可靠）
        self.api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("未设置 QWEN_API_KEY 或 DASHSCOPE_API_KEY 环境变量")

        self.model = model
        self.temperature = temperature
        self.timeout = timeout

        print(f"✅ QwenClient 使用 API Key (前15位): {self.api_key[:15]}...")

    def generate(self, prompt: str) -> str:
        # 设置全局 api_key（DashScope 要求）
        import dashscope
        dashscope.api_key = self.api_key  # ← 关键！

        try:
            response = Generation.call(
                model=self.model,
                prompt=prompt,
                temperature=self.temperature,
                result_format='message'
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"Qwen API 错误 [{response.status_code}]: {response}")
            
            return response.output.choices[0].message.content.strip()
        
        except Exception as e:
            raise RuntimeError(f"调用 Qwen 模型失败: {e}") from e