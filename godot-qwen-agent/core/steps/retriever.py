"""RetrieverStep: business-layer retrieval with async adapter, health probe, and DependencyHealth."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from typing import Any, ClassVar, Dict, List, Optional, Set

from core.adapters.vector_store import VectorStoreAdapter, VectorStoreBackend
from core.contracts import (
    Chunk,
    ContentBlock,
    RetrievalResult,
    SemVer,
    register_component,
)
from core.pipeline.engine import (
    DependencyHealth,
    HealthStatus,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer


# ── Simple in-memory cosine-similarity backend (no FAISS dependency) ──


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two same-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _simple_embedding(text: str, dim: int = 64) -> List[float]:
    """Deterministic pseudo-embedding from text hash (not semantic, for testing)."""
    h = hashlib.sha256(text.encode()).digest()
    vec = []
    for i in range(dim):
        byte_idx = (i * 3) % len(h)
        val = (h[byte_idx] / 255.0) * 2 - 1  # map to [-1, 1]
        vec.append(val)
    # Normalize
    mag = math.sqrt(sum(x * x for x in vec))
    if mag > 0:
        vec = [x / mag for x in vec]
    return vec


class InMemoryVectorBackend:
    """Satisfies VectorStoreBackend protocol with in-memory cosine similarity."""

    def __init__(self, chunks: Optional[List[Chunk]] = None) -> None:
        self._chunks: List[Chunk] = []
        self._vectors: List[List[float]] = []
        if chunks:
            for c in chunks:
                self.add(c)

    def add(self, chunk: Chunk) -> None:
        self._chunks.append(chunk)
        self._vectors.append(_simple_embedding(chunk.text))

    def search(
        self, query_vector: List[float], top_k: int
    ) -> List[RetrievalResult]:
        if not self._chunks:
            return []
        scores = [(i, _cosine(query_vector, self._vectors[i])) for i in range(len(self._chunks))]
        scores.sort(key=lambda x: x[1], reverse=True)
        results: List[RetrievalResult] = []
        for rank, (idx, score) in enumerate(scores[:top_k], start=1):
            results.append(RetrievalResult(chunk=self._chunks[idx], score=round(score, 4), rank=rank))
        return results

    def count(self) -> int:
        return len(self._chunks)


# ── RetrieverStep ──────────────────────────────────────────────────


@register_component("retriever", "simple_cosine")
class RetrieverStep:
    """Business-layer retriever: chunks + query → scored RetrievalResults.

    health_check performs a semantic probe against the backend.
    Empty results are valid output (engine treats as skip-able).
    """

    VERSION: ClassVar[SemVer] = SemVer(0, 1, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = {"retrieval_score", "retrieval_rank"}

    def __init__(
        self,
        top_k: int = 5,
        backend: Optional[VectorStoreBackend] = None,
        index_chunks: Optional[List[Chunk]] = None,
    ) -> None:
        self._top_k = top_k
        if backend is not None:
            self._backend = backend
        else:
            self._backend = InMemoryVectorBackend(index_chunks or [])
        self._adapter = VectorStoreAdapter(self._backend, dependency_name="vector_store")
        self._sentinel_vector = _simple_embedding("__health_probe__")

    async def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        """Async-native execution (Phase 8.1). The engine calls this directly."""
        chunks: List[Chunk] = inputs.get("chunks", [])

        if not chunks:
            return StepOutput(
                result=[],
                trace_log={"retriever": "RetrieverStep", "version": str(self.VERSION)},
                contract_validation=None,
            )

        query_text = str(inputs.get("query", ""))
        if not query_text and chunks:
            query_text = chunks[0].text

        query_vec = _simple_embedding(query_text)

        t0 = time.perf_counter()
        results = await self._adapter.search(query_vec, self._top_k)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Attach dependency trace to output
        trace_log = {
            "retriever": "RetrieverStep",
            "version": str(self.VERSION),
            "query_hash": _text_hash(query_text),
            "results_count": len(results),
            "elapsed_ms": round(elapsed_ms, 3),
        }

        return StepOutput(
            result=results,
            trace_log=trace_log,
        )

    def health_check(self) -> HealthStatus:
        """Semantic probe: search a known sentinel vector and report DependencyHealth."""
        try:
            probe_results = self._backend.search(self._sentinel_vector, top_k=1)
            dep_status: str = "healthy" if probe_results else "degraded"
            dep_latency: Optional[float] = None
            dep_message = (
                f"semantic probe: found {len(probe_results)} result(s)"
                if probe_results
                else "semantic probe: index returned 0 results"
            )
        except Exception as exc:
            dep_status = "unavailable"
            dep_latency = None
            dep_message = f"health probe failed: {exc}"

        dep = DependencyHealth(
            name="vector_db",
            status=dep_status,
            latency_ms=dep_latency,
            message=dep_message,
        )

        # Overall status: lowest common denominator
        status: str = dep_status
        return HealthStatus(
            status=status,
            message="retriever operational" if status == "healthy" else f"retriever {status}",
            dependencies=[dep],
            version=str(self.VERSION),
        )
