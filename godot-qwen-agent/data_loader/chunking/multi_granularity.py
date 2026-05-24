# data_loader/chunking/multi_granularity.py
"""
多粒度分块器（Level 1 策略）
输入：纯文本（str）
输出：List[str] —— 多个粒度的 chunks 合并去重后的结果
"""

from typing import List


class MultiGranularityChunker:
    """
    支持多个 chunk size 并行切分，生成不同粒度的文本块。
    例如：同时生成 256 和 512 长度的 chunks，用于多粒度 embedding 对比。
    """

    def __init__(
        self,
        chunk_sizes: List[int] = [256, 512],
        overlaps: List[int] = [0, 50],
        enable_dedup: bool = True,
        min_length: int = 50,
        max_length: int = 1024
    ):
        if len(chunk_sizes) != len(overlaps):
            raise ValueError("chunk_sizes 和 overlaps 必须长度一致")
        if not all(s > 0 for s in chunk_sizes):
            raise ValueError("chunk_size 必须大于 0")

        self.chunk_sizes = chunk_sizes
        self.overlaps = overlaps
        self.enable_dedup = enable_dedup
        self.min_length = min_length
        self.max_length = max_length

    def _split_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """按指定大小和重叠切割文本"""
        if not text.strip():
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + chunk_size
            chunk = text[start:end]

            # 跳过太短的末尾片段
            if len(chunk.strip()) < self.min_length and end >= text_len:
                break

            # 截断超长 chunk（理论上不会发生，但安全起见）
            if len(chunk) > self.max_length:
                chunk = chunk[:self.max_length]

            chunks.append(chunk)
            start += (chunk_size - overlap)

        return chunks

    def split_text(self, text: str) -> List[str]:
        """
        主接口：对输入文本进行多粒度分块
        
        Args:
            text (str): 原始文本
            
        Returns:
            List[str]: 所有粒度的 chunks 列表（已去重）
        """
        all_chunks = []
        seen = set() if self.enable_dedup else None

        for chunk_size, overlap in zip(self.chunk_sizes, self.overlaps):
            sub_chunks = self._split_text(text, chunk_size, overlap)
            for ch in sub_chunks:
                if self.enable_dedup:
                    # 使用 strip() 避免空白差异导致重复
                    key = ch.strip()
                    if key in seen:
                        continue
                    seen.add(key)
                all_chunks.append(ch)

        return all_chunks