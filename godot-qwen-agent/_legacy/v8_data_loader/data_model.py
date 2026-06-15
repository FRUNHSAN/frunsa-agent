# data_loader/data_model.py
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Document:
    """表示一个加载后的原始文档（未分块）"""
    content: str          # 原始文本内容
    source: str           # 来源路径（如文件路径）
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class DocumentChunk:
    """表示一个分块后的文本片段"""
    text: str
    source_id: str
    metadata: Dict[str, Any]