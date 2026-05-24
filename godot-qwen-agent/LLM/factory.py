# llm/factory.py
"""
LLM 客户端工厂函数：根据配置动态创建对应客户端
"""

from typing import Dict, Any
from .base import BaseLLMClient
from .qwen import QwenClient
from .openai import OpenAIClient
from .ollama import OllamaClient      # ← 新增
from .claude import ClaudeClient      # ← 新增

# 支持的提供商映射
SUPPORTED_PROVIDERS: Dict[str, type] = {
    "qwen": QwenClient,
    "openai": OpenAIClient,
    "ollama": OllamaClient,      # ← 已正确引用
    "claude": ClaudeClient,      # ← 已正确引用
}

def create_llm_client(provider: str, **kwargs) -> BaseLLMClient:
    """
    工厂函数：根据 provider 创建对应的 LLM 客户端
    
    Args:
        provider (str): 模型提供商，如 "qwen", "openai"
        **kwargs: 传递给具体客户端的参数（model, api_key, temperature 等）
        
    Returns:
        BaseLLMClient: 对应的客户端实例
        
    Raises:
        ValueError: 不支持的 provider
    """
    if provider not in SUPPORTED_PROVIDERS:
        available = ", ".join(SUPPORTED_PROVIDERS.keys())
        raise ValueError(
            f"不支持的 LLM 提供商: '{provider}'。"
            f"当前支持: {available}"
        )
    
    client_class = SUPPORTED_PROVIDERS[provider]
    return client_class(**kwargs)