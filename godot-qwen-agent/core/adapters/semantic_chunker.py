"""SemanticChunker — embedding-based sentence boundary detection.

Registered via @register_component("chunker", "semantic").
Graceful degradation: regex sentence split when embedding model unavailable.
"""

from __future__ import annotations

import re
from typing import ClassVar

from core.contracts.chunking import Chunk, ContentBlock, SemVer
from core.contracts.registry import register_component


@register_component("chunker", "semantic")
class SemanticChunker:
    """Embedding-based chunking. Falls back to regex sentence split."""

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)

    def __init__(self, similarity_threshold: float = 0.5) -> None:
        self._threshold = similarity_threshold
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        except Exception:
            pass  # Graceful degradation to regex

    @classmethod
    def validate_params(cls, params: dict) -> list[str]:
        errors = []
        t = params.get("similarity_threshold", 0.5)
        if not (0.0 < t < 1.0):
            errors.append("similarity_threshold must be in (0, 1)")
        return errors

    def chunk(self, content: ContentBlock) -> list[Chunk]:
        if self._model:
            return self._semantic_split(content)
        return self._regex_split(content)

    def _regex_split(self, content: ContentBlock) -> list[Chunk]:
        """Fallback: split on sentence boundaries (。！？.!?)."""
        text = content.text
        # Split on sentence terminators, keeping the punctuation
        parts = re.split(r'(?<=[。！？.!?])\s*', text)
        chunks: list[Chunk] = []
        offset = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            chunks.append(Chunk(
                text=part,
                span=(offset, offset + len(part)),
                metadata={"chunker": "semantic_fallback"},
            ))
            offset += len(part)
        return chunks

    def _semantic_split(self, content: ContentBlock) -> list[Chunk]:
        """Embedding-based split: cut where cosine similarity drops."""
        import numpy as np
        from sentence_transformers import util

        # Split into sentences first
        sentences = re.split(r'(?<=[。！？.!?])\s*', content.text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) <= 1:
            return self._regex_split(content)

        # Embed all sentences
        embs = self._model.encode(sentences, convert_to_numpy=True)  # type: ignore

        # Group sentences by similarity
        chunks: list[Chunk] = []
        buffer = sentences[0]
        offset = 0
        for i in range(1, len(sentences)):
            sim = float(util.cos_sim(embs[i - 1], embs[i]))
            if sim < self._threshold:
                # Similarity drop → new chunk
                chunks.append(Chunk(
                    text=buffer,
                    span=(offset, offset + len(buffer)),
                    metadata={"chunker": "semantic", "similarity": round(sim, 3)},
                ))
                offset += len(buffer)
                buffer = sentences[i]
            else:
                buffer += " " + sentences[i]

        if buffer.strip():
            chunks.append(Chunk(
                text=buffer.strip(),
                span=(offset, offset + len(buffer)),
                metadata={"chunker": "semantic"},
            ))
        return chunks
