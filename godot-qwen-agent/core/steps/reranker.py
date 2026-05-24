"""RerankerStep: business-layer reranking with async adapter and health probe."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, ClassVar, Dict, List, Optional, Set

from core.adapters.reranker_adapter import ScoringAdapter, ScoringBackend
from core.contracts import (
    Chunk,
    SemVer,
    register_component,
    validate_reranker_output,
)
from core.contracts.retrieval import RetrievalResult
from core.pipeline.engine import (
    DependencyHealth,
    HealthStatus,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer


# ── Simple inline mock backend (no external API required) ─────────────


class MockScoringBackend:
    """Scores chunks by TF-like term overlap with the query. For testing only."""

    def __init__(self, latency_ms: float = 0.0) -> None:
        self._latency = latency_ms

    def score(self, chunks: List[Chunk], query: str, **params: Any) -> List[RetrievalResult]:
        if self._latency > 0:
            time.sleep(self._latency / 1000.0)

        query_terms = set(query.lower().split())
        if not query_terms:
            query_terms = {"__empty_query__"}

        scored: List[RetrievalResult] = []
        for chunk in chunks:
            chunk_terms = set(chunk.text.lower().split())
            overlap = len(query_terms & chunk_terms)
            total = len(query_terms | chunk_terms)
            score = overlap / total if total > 0 else 0.0
            scored.append(RetrievalResult(chunk=chunk, score=round(score, 4), rank=0))

        scored.sort(key=lambda r: r.score, reverse=True)
        scored = [
            RetrievalResult(chunk=r.chunk, score=r.score, rank=i, metadata=r.metadata)
            for i, r in enumerate(scored, start=1)
        ]
        return scored

    def count(self) -> int:
        return 0  # unlimited


# ── RerankerStep ─────────────────────────────────────────────────────


@register_component("reranker", "mock_overlap")
class RerankerStep:
    """Business-layer reranker: chunks + query → rescored RetrievalResults.

    Contract enforcement at adapter level: output <= input, sequential ranks,
    descending scores. Validation at step level via validate_reranker_output.
    """

    VERSION: ClassVar[SemVer] = SemVer(0, 1, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = {"rerank_score", "rerank_rank"}

    def __init__(
        self,
        backend: Optional[ScoringBackend] = None,
    ) -> None:
        self._backend = backend or MockScoringBackend()
        self._adapter = ScoringAdapter(self._backend, dependency_name="reranker_api")

    async def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        """Async-native execution (Phase 8.1). The engine calls this directly."""
        chunks: List[Chunk] = inputs.get("chunks", [])
        if not isinstance(chunks, list):
            chunks = []

        if not chunks:
            return StepOutput(
                result=[],
                trace_log={"reranker": "RerankerStep", "version": str(self.VERSION)},
                contract_validation=None,
            )

        query = str(inputs.get("query", ""))
        if not query:
            query = chunks[0].text

        t0 = time.perf_counter()
        results = await self._adapter.score(chunks=chunks, query=query)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        validation = validate_reranker_output(results, len(chunks))

        trace_log = {
            "reranker": "RerankerStep",
            "version": str(self.VERSION),
            "input_chunks": len(chunks),
            "results_count": len(results),
            "elapsed_ms": round(elapsed_ms, 3),
        }

        return StepOutput(
            result=results,
            trace_log=trace_log,
            contract_validation=validation,
        )

    def health_check(self) -> HealthStatus:
        try:
            # Lightweight sync probe: minimal scoring call to verify backend
            self._backend.score(chunks=[], query="__health_probe__")
            dep_status: str = "healthy"
            dep_latency: Optional[float] = None
            dep_message = "health probe: backend reachable"
        except Exception as exc:
            dep_status = "unavailable"
            dep_latency = None
            dep_message = f"health probe failed: {exc}"

        dep = DependencyHealth(
            name="reranker_api",
            status=dep_status,
            latency_ms=dep_latency,
            message=dep_message,
        )

        return HealthStatus(
            status=dep_status,
            message="reranker operational" if dep_status == "healthy" else f"reranker {dep_status}",
            dependencies=[dep],
            version=str(self.VERSION),
        )
