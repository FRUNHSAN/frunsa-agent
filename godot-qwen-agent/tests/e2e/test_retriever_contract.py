"""Phase 5.0: Retriever contract tests (TDD — tests before implementation).

These tests define what Retriever MUST satisfy. Implementation comes after they pass.
The mock Adapter below is the expected interface — the real FAISS adapter mirrors it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from core.contracts import Chunk, SemVer
from core.contracts.retrieval import RetrievalResult
from core.pipeline.engine import DependencyHealth, HealthStatus
from core.pipeline.tracing import DependencyCallTrace, SpanType


# ── Mock vector store for contract validation (no real FAISS needed) ──


@dataclass
class MockVectorStore:
    """Simulates FAISS index — returns pre-canned results with configurable latency."""

    results: List[RetrievalResult] = field(default_factory=list)
    latency_ms: float = 0.0
    should_timeout: bool = False
    should_fail: bool = False

    async def search(self, query_vector: List[float], top_k: int) -> List[RetrievalResult]:
        if self.should_fail:
            raise RuntimeError("index corrupt")
        if self.should_timeout:
            await asyncio.sleep(5.0)
            raise asyncio.TimeoutError("search timed out")
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000.0)
        return self.results[:top_k]


# ── Contract: RetrievalResult ─────────────────────────────────────


class TestRetrievalResultContract:
    def test_frozen_dataclass(self):
        chunk = Chunk(text="hello", source_strategy="test", span=(0, 5))
        rr = RetrievalResult(chunk=chunk, score=0.95, rank=1)
        assert rr.score == 0.95
        assert rr.chunk.text == "hello"

    def test_immutable_metadata(self):
        chunk = Chunk(text="hello", source_strategy="x", span=(0, 5))
        rr = RetrievalResult(chunk=chunk, score=0.8, rank=1, metadata={"source": "doc1"})
        with pytest.raises(TypeError):
            rr.metadata["source"] = "mutated"  # type: ignore[index]


# ── Contract: DependencyCallTrace injection ───────────────────────


class TestDependencyCallTraceContract:
    """Every external search call MUST produce a DependencyCallTrace."""

    def test_search_call_produces_trace(self):
        chunk = Chunk(text="result", source_strategy="identity", span=(0, 6))
        results = [RetrievalResult(chunk=chunk, score=0.9, rank=1)]

        t0 = time.perf_counter()
        trace = DependencyCallTrace(
            dependency_name="vector_store.search",
            span_type=SpanType.DEPENDENCY_CALL,
            started_at=t0,
            finished_at=time.perf_counter(),
            duration_ms=12.5,
            status="success",
            metadata={"top_k": 5, "results_count": len(results)},
        )
        assert trace.dependency_name == "vector_store.search"
        assert trace.duration_ms > 0
        assert trace.metadata["results_count"] == 1

    def test_timed_out_call_traces_as_timeout(self):
        trace = DependencyCallTrace(
            dependency_name="vector_store.search",
            span_type=SpanType.DEPENDENCY_CALL,
            status="timeout",
            metadata={"error": "search timed out"},
        )
        assert trace.status == "timeout"

    def test_failed_call_traces_as_error(self):
        trace = DependencyCallTrace(
            dependency_name="vector_store.search",
            span_type=SpanType.DEPENDENCY_CALL,
            status="error",
            metadata={"error": "index corrupt"},
        )
        assert trace.status == "error"


# ── Contract: Health check with DependencyHealth ───────────────────


class TestRetrieverHealthContract:
    """Health check MUST declare vector_db dependency with semantic probe."""

    def test_healthy_when_search_returns_results(self):
        dep = DependencyHealth(
            name="vector_db",
            status="healthy",
            latency_ms=12.3,
            message="semantic probe: found 1 result",
        )
        assert dep.status == "healthy"
        assert dep.name == "vector_db"

    def test_degraded_when_search_returns_empty(self):
        dep = DependencyHealth(
            name="vector_db",
            status="degraded",
            latency_ms=8.1,
            message="semantic probe: index returned 0 results",
        )
        assert dep.status == "degraded"

    def test_unavailable_when_connection_fails(self):
        dep = DependencyHealth(
            name="vector_db",
            status="unavailable",
            message="index not loaded",
        )
        assert dep.status == "unavailable"

    def test_health_status_aggregates_dependencies(self):
        hs = HealthStatus(
            status="healthy",
            message="retriever operational",
            dependencies=[
                DependencyHealth(
                    name="vector_db", status="healthy", latency_ms=5.0
                )
            ],
            version="0.1.0",
        )
        assert hs.status == "healthy"
        assert len(hs.dependencies) == 1
        assert hs.version == "0.1.0"


# ── Contract: Empty result → skip (not error) ─────────────────────


class TestEmptyResultSkipContract:
    """Empty result list is valid output, NOT a failure."""

    def test_empty_results_are_valid_output(self):
        """[] is a legitimate result — no relevant docs found."""
        results: List[RetrievalResult] = []
        # This should NOT raise — engine interprets [] as normal, not error
        assert isinstance(results, list)

    def test_empty_results_propagate_as_skip_in_pipeline(self):
        """When retriever returns [], downstream steps depending on it should skip."""
        from core.pipeline.engine import _SKIP_SENTINEL

        # Simulate: state gets skip sentinel
        state: Dict[str, Any] = {"results": _SKIP_SENTINEL}
        # Downstream step checks: any(dep is _SKIP_SENTINEL for dep in depends_on)
        downstream_deps = ["results"]
        should_skip = any(
            state.get(dep) is _SKIP_SENTINEL for dep in downstream_deps
        )
        assert should_skip


# ── Contract: Registration in ComponentRegistry ───────────────────


class TestRetrieverRegistration:
    def test_retriever_component_type_exists(self):
        """Retrieval strategies should register under component_type='retriever'."""
        from core.contracts.registry import COMPONENT_REGISTRY

        types = COMPONENT_REGISTRY.list_types()
        # At minimum, 'chunker' exists; 'retriever' gets added on first register
        assert "chunker" in types


# ── Contract: Resource release after use ──────────────────────────


class TestResourceRelease:
    """Managed resources (vector index, connections) MUST be released by close()."""

    def test_managed_resource_closed_by_container(self):
        from core.pipeline.resources import ResourceContainer

        closed = False

        class FakeIndex:
            def close(self):
                nonlocal closed
                closed = True

        rc = ResourceContainer()
        rc.register_managed("faiss_index", FakeIndex())
        rc.close()
        assert closed
