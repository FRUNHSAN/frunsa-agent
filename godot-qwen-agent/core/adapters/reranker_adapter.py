"""ScoringAdapter: async wrapper around reranking/scoring backends.

Isolates external reranker API behind a uniform async interface.
Every score call auto-injects a DependencyCallTrace.
Contract enforcement: output length <= input length, sequential ranks, descending scores.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Protocol

from core.contracts import Chunk
from core.contracts.retrieval import RetrievalResult
from core.pipeline.tracing import DependencyCallTrace, SpanType


class ScoringBackend(Protocol):
    """Protocol for scoring/reranking backends — Cohere, Cross-encoder, etc."""

    def score(self, chunks: List[Chunk], query: str, **params: Any) -> List[RetrievalResult]:
        """Synchronous scoring. The adapter wraps this in an executor."""
        ...

    def count(self) -> int:
        """Number of chunks this backend can score in one call (0 = unlimited)."""
        ...


class ScoringAdapter:
    """Async wrapper with auto-tracing, timeout, and contract enforcement."""

    def __init__(
        self,
        backend: ScoringBackend,
        dependency_name: str = "reranker_api",
        default_timeout: float = 60.0,
    ) -> None:
        self._backend = backend
        self._dependency_name = dependency_name
        self._default_timeout = default_timeout
        self._last_probe_latency_ms: Optional[float] = None

    async def score(
        self,
        chunks: List[Chunk],
        query: str,
        timeout: Optional[float] = None,
        **params: Any,
    ) -> List[RetrievalResult]:
        """Async scoring with automatic DependencyCallTrace and contract enforcement."""
        effective_timeout = timeout or self._default_timeout
        t0 = time.perf_counter()
        status: str = "success"
        error_msg: Optional[str] = None
        results: List[RetrievalResult] = []

        try:
            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._backend.score(chunks, query, **params)
                ),
                timeout=effective_timeout,
            )
            # Contract enforcement: output must not exceed input
            if len(results) > len(chunks):
                results = results[: len(chunks)]
            # Re-rank to ensure descending scores and sequential ranks
            results = sorted(results, key=lambda r: r.score, reverse=True)
            results = [
                RetrievalResult(chunk=r.chunk, score=r.score, rank=i, metadata=r.metadata)
                for i, r in enumerate(results, start=1)
            ]
        except asyncio.TimeoutError:
            status = "timeout"
            error_msg = f"scoring exceeded {effective_timeout}s"
        except Exception as exc:
            status = "error"
            error_msg = f"{type(exc).__name__}: {exc}"

        elapsed = (time.perf_counter() - t0) * 1000.0
        self._last_probe_latency_ms = elapsed

        trace = DependencyCallTrace(
            dependency_name=f"{self._dependency_name}.score",
            span_type=SpanType.DEPENDENCY_CALL,
            started_at=t0,
            finished_at=time.perf_counter(),
            duration_ms=round(elapsed, 3),
            status=status,
            metadata={
                "input_chunks": len(chunks),
                "output_results": len(results),
                "query_hash": str(hash(query))[:16],
                **({"error": error_msg} if error_msg else {}),
            },
        )
        self._last_trace = trace

        return results

    @property
    def last_trace(self) -> Optional[DependencyCallTrace]:
        return getattr(self, "_last_trace", None)

    @property
    def last_probe_latency_ms(self) -> Optional[float]:
        return self._last_probe_latency_ms

    async def health_probe(self) -> Dict[str, Any]:
        """Health probe: score a single chunk to verify the endpoint is reachable."""
        try:
            probe_chunk = Chunk(text="__health_probe__", source_strategy="test", span=(0, 16))
            results = await self.score(
                chunks=[probe_chunk],
                query="__health_probe__",
                timeout=10.0,
            )
            last = self.last_trace
            if last and last.status == "error":
                return {
                    "status": "unavailable",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": last.metadata.get("error", "health probe: scoring error"),
                }
            elif results:
                return {
                    "status": "healthy",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": f"health probe: scored {len(results)} result(s)",
                }
            else:
                return {
                    "status": "degraded",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": "health probe: scoring returned 0 results",
                }
        except asyncio.TimeoutError:
            return {
                "status": "degraded",
                "latency_ms": self._last_probe_latency_ms,
                "message": "health probe timed out",
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "latency_ms": self._last_probe_latency_ms,
                "message": f"health probe failed: {exc}",
            }
