"""Retrieval contracts: data models, strategy protocol, and validation for the retrieval domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Dict, List, Optional, Set

from .chunking import Chunk, SemVer


@dataclass(frozen=True)
class RetrievalResult:
    """Single retrieval hit: a chunk with a relevance score."""
    chunk: Chunk
    score: float
    rank: int
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            from copy import deepcopy
            object.__setattr__(
                self, "metadata", MappingProxyType(deepcopy(dict(self.metadata)))
            )


class RetrievalStrategy:
    """Protocol for retrieval strategies (structural, no ABC required).

    Mandatory:
      VERSION: ClassVar[SemVer]
      retrieve(chunks: List[Chunk], query: str) -> List[RetrievalResult]

    Optional:
      health_check() -> HealthStatus
      requires_metadata / provides_metadata class vars
    """
