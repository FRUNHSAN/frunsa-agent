# llm/ollama.py
"""
Ollama 客户端：用于调用本地运行的开源大模型（如 llama3, qwen:7b, gemma 等）
需先安装并启动 Ollama: https://ollama.com/
"""

from typing import Optional
from .base import BaseLLMClient

try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False

class OllamaClient(BaseLLMClient):
    """
    调用本地 Ollama 服务
    默认连接 http://localhost:11434
    """

    def __init__(
        self,
        model: str = "llama3",
        host: Optional[str] = None,
        temperature: float = 0.3
    ):
        if not HAS_OLLAMA:
            raise ImportError(
                "ollama 未安装。请运行: pip install ollama"
            )
        
        self.model = model
        self.temperature = temperature
        self.host = host  # 如需远程 Ollama，可指定 host

    def generate(self, prompt: str) -> str:
        try:
            client = ollama.Client(host=self.host) if self.host else ollama
            response = client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": self.temperature}
            )
            return response["message"]["content"].strip()
        
        except Exception as e:
            raise RuntimeError(f"调用 Ollama 模型失败: {e}") from e