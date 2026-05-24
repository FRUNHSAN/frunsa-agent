from .base import BaseChunker
from typing import List

class RecursiveCharacterTextSplitter(BaseChunker):
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._separators = ["\n\n", "\n", "。", ". ", " ", ""]

    def split_text(self, text: str) -> List[str]:
        if not text:
            return [""]
        return self._split_recursive(text, self._separators)

    def _split_recursive(self, text: str, separators: List[str]) -> List[str]:
        if len(separators) == 0 or len(separators[0]) == 0:
            # 最后手段：硬切（带 overlap）
            chunks = []
            start = 0
            while start < len(text):
                end = start + self.chunk_size
                chunks.append(text[start:end])
                start = end - self.chunk_overlap if self.chunk_overlap < end else end
            return chunks

        separator = separators[0]
        if text.count(separator) < 2:
            return self._split_recursive(text, separators[1:])

        parts = text.split(separator)
        chunks = []
        current_chunk = ""

        for part in parts:
            test_chunk = current_chunk + (separator if current_chunk else "") + part
            if len(test_chunk.encode("utf-8")) <= self.chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    # 计算 overlap 部分（简单按字符）
                    if self.chunk_overlap > 0 and len(current_chunk) > self.chunk_overlap:
                        current_chunk = current_chunk[-self.chunk_overlap:] + separator + part
                    else:
                        current_chunk = part
                else:
                    # 单个 part 超长 → 递归切
                    sub_chunks = self._split_recursive(part, separators[1:])
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""

        if current_chunk:
            chunks.append(current_chunk)

        return chunks