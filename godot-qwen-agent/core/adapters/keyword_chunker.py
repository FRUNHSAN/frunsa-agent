"""KeywordChunker — minimal ChunkingStrategy implementation.

Splits text into paragraph-level chunks with overlap.
Registered via COMPONENT_REGISTRY — swap for semantic chunker anytime.
"""

from __future__ import annotations

from typing import ClassVar

from core.contracts.chunking import Chunk, ContentBlock, SemVer, ChunkingStrategy
from core.contracts.registry import COMPONENT_REGISTRY


@COMPONENT_REGISTRY.register("chunker", "keyword")
class KeywordChunker:
    """Paragraph-based chunking. Overlap = 1 sentence."""

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100) -> None:
        self._size = chunk_size
        self._overlap = chunk_overlap

    @classmethod
    def validate_params(cls, params: dict) -> list[str]:
        errors = []
        if params.get("chunk_size", 500) < params.get("chunk_overlap", 100):
            errors.append("chunk_overlap must be <= chunk_size")
        return errors

    def chunk(self, content: ContentBlock) -> list[Chunk]:
        text = content.text
        if not text.strip():
            return []

        # Split by paragraphs
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[Chunk] = []
        buffer = ""
        seq = 0

        for para in paragraphs:
            if len(buffer) + len(para) > self._size and buffer:
                chunks.append(Chunk(
                    text=buffer.strip(), sequence=seq,
                    metadata={"chunker": "keyword", "chunk_size": len(buffer)},
                ))
                seq += 1
                # Overlap: keep last N chars
                buffer = buffer[-self._overlap:] if self._overlap > 0 else ""
            buffer += para + "\n\n"

        if buffer.strip():
            chunks.append(Chunk(
                text=buffer.strip(), sequence=seq,
                metadata={"chunker": "keyword", "chunk_size": len(buffer)},
            ))

        return chunks
