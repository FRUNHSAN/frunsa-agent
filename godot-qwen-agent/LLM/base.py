# llm/base.py
"""
定义 LLM 客户端的抽象基类
所有具体实现必须继承此类并实现 generate 方法
"""

from abc import ABC, abstractmethod

class BaseLLMClient(ABC):
    """
    大语言模型客户端的统一接口
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """
        根据输入提示生成文本
        
        Args:
            prompt (str): 输入提示
            
        Returns:
            str: 模型生成的文本
            
        Raises:
            Exception: 任何调用失败（网络、配额、认证等）
        """
        pass