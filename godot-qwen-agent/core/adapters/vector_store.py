"""VectorStoreAdapter: async wrapper around vector search backends.

Isolates external SDK (FAISS, Qdrant, etc.) behind a uniform async interface.
Every search call auto-injects a DependencyCallTrace for observability.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Protocol

from core.contracts import Chunk, RetrievalResult
from core.pipeline.tracing import DependencyCallTrace, SpanType


class VectorStoreBackend(Protocol):
    """Protocol for vector store backends — FAISS, Qdrant, Chroma, etc."""

    def search(self, query_vector: List[float], top_k: int) -> List[RetrievalResult]:
        """Synchronous search. The adapter wraps this in an executor."""
        ...

    def count(self) -> int:
        """Number of indexed vectors."""
        ...


class VectorStoreAdapter:
    """Async wrapper with auto-tracing and timeout support."""

    def __init__(
        self,
        backend: VectorStoreBackend,
        dependency_name: str = "vector_store",
        default_timeout: float = 30.0,
    ) -> None:
        self._backend = backend
        self._dependency_name = dependency_name
        self._default_timeout = default_timeout
        self._last_probe_latency_ms: Optional[float] = None

    async def search(
        self, query_vector: List[float], top_k: int, timeout: Optional[float] = None
    ) -> List[RetrievalResult]:
        """Async search with automatic DependencyCallTrace."""
        effective_timeout = timeout or self._default_timeout
        t0 = time.perf_counter()
        status: str = "success"
        error_msg: Optional[str] = None

        try:
            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._backend.search(query_vector, top_k)
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            status = "timeout"
            error_msg = f"search exceeded {effective_timeout}s"
            results = []
        except Exception as exc:
            status = "error"
            error_msg = f"{type(exc).__name__}: {exc}"
            results = []

        elapsed = (time.perf_counter() - t0) * 1000.0
        self._last_probe_latency_ms = elapsed

        # Auto-inject trace (caller can attach to StepTrace.dependency_calls)
        trace = DependencyCallTrace(
            dependency_name=f"{self._dependency_name}.search",
            span_type=SpanType.DEPENDENCY_CALL,
            started_at=t0,
            finished_at=time.perf_counter(),
            duration_ms=round(elapsed, 3),
            status=status,
            metadata={
                "top_k": top_k,
                "results_count": len(results),
                **({"error": error_msg} if error_msg else {}),
            },
        )
        # Store for retrieval by the step
        self._last_trace = trace

        return results

    @property
    def last_trace(self) -> Optional[DependencyCallTrace]:
        return getattr(self, "_last_trace", None)

    @property
    def last_probe_latency_ms(self) -> Optional[float]:
        return self._last_probe_latency_ms

    async def health_probe(self, sentinel_vector: List[float]) -> Dict[str, Any]:
        """Semantic health probe: search a known vector and report results."""
        try:
            results = await self.search(sentinel_vector, top_k=1, timeout=5.0)
            last = self.last_trace
            if last and last.status == "error":
                return {
                    "status": "unavailable",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": last.metadata.get("error", "semantic probe: search error"),
                }
            elif results:
                return {
                    "status": "healthy",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": f"semantic probe: found {len(results)} result(s)",
                }
            else:
                return {
                    "status": "degraded",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": "semantic probe: index returned 0 results",
                }
        except asyncio.TimeoutError:
            return {
                "status": "degraded",
                "latency_ms": self._last_probe_latency_ms,
                "message": "semantic probe timed out",
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "latency_ms": self._last_probe_latency_ms,
                "message": f"semantic probe failed: {exc}",
            }
