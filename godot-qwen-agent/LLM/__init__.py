# llm/__init__.py
"""
统一导出 LLM 客户端接口，方便外部使用：
    from llm import create_llm_client
"""

from .factory import create_llm_client
from .base import BaseLLMClient

__all__ = ["create_llm_client", "BaseLLMClient"]