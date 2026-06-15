from abc import ABC, abstractmethod

class BaseLoader(ABC):
    @abstractmethod
    def load(self) -> str:
        """从源加载原始文本"""
        pass