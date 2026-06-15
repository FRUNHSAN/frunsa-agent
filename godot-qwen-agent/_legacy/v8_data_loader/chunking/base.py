from abc import ABC, abstractmethod
from typing import List

class BaseChunker(ABC):
    """所有分块器的基类"""
    @abstractmethod
    def split_text(self, text: str) -> List[str]:
        """将文本切分为 chunks"""
        pass