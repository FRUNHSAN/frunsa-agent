"""Identity chunking strategy: returns the entire ContentBlock as a single Chunk.

Purpose: end-to-end pipeline validation. Not for production use — it does zero actual splitting.
"""

from __future__ import annotations

from typing import ClassVar, List, Set

from .chunking import Chunk, ContentBlock, SemVer
from .registry import register_component


@register_component("chunker", "identity")
class IdentityChunker:
    """Dummy strategy: entire content as one chunk."""

    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = set()

    def chunk(self, content: ContentBlock) -> List[Chunk]:
        return [
            Chunk(
                text=content.text,
                metadata=content.metadata,
                source_strategy="chunking.identity",
                span=(0, len(content.text)),
            )
        ]

    def validate_config(self, config: dict) -> None:
        if config:
            raise ValueError(
                f"IdentityChunker takes no config, got: {list(config.keys())}"
            )

    def health_check(self) -> "HealthStatus":
        from core.pipeline.engine import HealthStatus
        return HealthStatus(
            status="healthy",
            message="IdentityChunker has no external dependencies",
            dependencies=[],
            version=str(self.VERSION),
        )
