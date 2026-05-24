"""Scoring contracts: strategy protocol for reranking / relevance scoring."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Optional, Set

from .chunking import Chunk, SemVer
from .retrieval import RetrievalResult


class ScoringStrategy:
    """Protocol for scoring/reranking strategies.

    Takes a list of Chunks + query, returns a rescored list of RetrievalResults
    sorted by descending score. This reuses RetrievalResult so the engine can
    handle retriever output and reranker output identically.

    Mandatory:
      VERSION: ClassVar[SemVer]
      score(chunks: List[Chunk], query: str, **params) -> List[RetrievalResult]

    Optional:
      health_check() -> HealthStatus
      requires_metadata / provides_metadata class vars

    Contract:
      - Output length MUST NOT exceed input length
      - Ranks MUST be sequential starting at 1
      - Results MUST be sorted by descending score
      - Zero-chunk input MUST produce empty output (not an error)
    """

    VERSION: ClassVar[SemVer]
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = {"rerank_score", "rerank_rank"}

    def score(self, chunks: List[Chunk], query: str, **params: Any) -> List[RetrievalResult]:
        """Rescore chunks relative to query. Returns RetrievalResults with new scores."""
        ...

    def health_check(self) -> Any:
        """Optional health probe. Returns HealthStatus if implemented."""
        ...
