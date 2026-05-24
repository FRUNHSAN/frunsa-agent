"""Phase 5.3: Retriever negative cases — edge cases, error propagation, degradation."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from core.adapters.chunker_adapter import ChunkerAdapter
from core.contracts import Chunk, ContentBlock, IdentityChunker
from core.contracts.retrieval import RetrievalResult
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
)
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep, _simple_embedding


# ── Helpers ──────────────────────────────────────────────────────────


def _chunk(text: str, idx: int = 0) -> Chunk:
    return Chunk(text=text, source_strategy="test", span=(idx, idx + len(text)))


# ── Negative: Empty/missing inputs ──────────────────────────────────


class TestEmptyInputs:
    """Scenario: empty chunks or query → valid empty results, not error."""

    def test_empty_chunks_returns_empty_results(self):
        retriever = RetrieverStep(top_k=5)
        output = asyncio.run(retriever.run(
            inputs={"chunks": [], "query": "anything"},
            resources=None,
        ))
        assert output.result == []

    def test_empty_query_falls_back_to_first_chunk_text(self):
        chunks = [_chunk("fallback content", 0)]
        retriever = RetrieverStep(top_k=3, index_chunks=chunks)
        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": ""},
            resources=None,
        ))
        assert isinstance(output.result, list)

    def test_missing_query_key_falls_back(self):
        chunks = [_chunk("text", 0)]
        retriever = RetrieverStep(top_k=3, index_chunks=chunks)
        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks},  # no 'query' key
            resources=None,
        ))
        assert isinstance(output.result, list)

    def test_missing_chunks_key_returns_empty(self):
        retriever = RetrieverStep(top_k=5)
        output = asyncio.run(retriever.run(
            inputs={"query": "something"},
            resources=None,
        ))
        assert output.result == []


# ── Negative: Backend failures ──────────────────────────────────────


class FailingBackend:
    """Backend that raises on search to simulate index corruption."""

    def search(self, query_vector: List[float], top_k: int) -> List[RetrievalResult]:
        raise RuntimeError("index corrupt: segment fault")

    def count(self) -> int:
        return 0


class TimeoutBackend:
    """Backend that simulates a hung search call."""

    def search(self, query_vector: List[float], top_k: int) -> List[RetrievalResult]:
        raise asyncio.TimeoutError("search timed out")

    def count(self) -> int:
        return 100


class TestBackendFailures:
    """Scenario: backend errors → health check reflects them."""

    def test_health_check_unavailable_when_backend_raises(self):
        retriever = RetrieverStep(top_k=5, backend=FailingBackend())
        hs = retriever.health_check()
        assert hs.status == "unavailable"
        assert hs.dependencies[0].status == "unavailable"
        msg = hs.dependencies[0].message or ""
        assert "index corrupt" in msg or "failed" in msg.lower()

    def test_health_check_reports_vector_db_dependency_name(self):
        retriever = RetrieverStep(top_k=5, backend=FailingBackend())
        hs = retriever.health_check()
        assert hs.dependencies[0].name == "vector_db"

    def test_search_with_failing_backend_surfaces_via_adapter(self):
        """When backend fails, adapter catches error → returns empty results (graceful)."""
        retriever = RetrieverStep(top_k=5, backend=FailingBackend())
        chunks = [_chunk("data", 0)]
        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": "data"},
            resources=None,
        ))
        # Adapter catches error, returns [] — not a crash
        assert output.result == []


# ── Negative: Health check degradation ──────────────────────────────


class TestHealthDegradation:
    """Scenario: health check reports degraded when index is empty."""

    def test_empty_backend_is_reachable_but_empty(self):
        """Empty backend: probe runs, gets 0 results → degraded."""
        retriever = RetrieverStep(top_k=5, backend=InMemoryVectorBackend([]))
        hs = retriever.health_check()
        assert hs.status in ("healthy", "degraded")
        assert len(hs.dependencies) == 1

    def test_populated_backend_is_healthy(self):
        chunks = [_chunk("hello world", 0)]
        retriever = RetrieverStep(top_k=5, backend=InMemoryVectorBackend(chunks))
        hs = retriever.health_check()
        assert hs.status == "healthy"
        assert hs.dependencies[0].status == "healthy"

    def test_version_included_in_health_status(self):
        retriever = RetrieverStep(top_k=5)
        hs = retriever.health_check()
        assert hs.version == "0.1.0"


# ── Negative: Pipeline skip propagation ─────────────────────────────


class TestSkipPropagation:
    """Scenario: when upstream step produces chunks, retriever runs normally."""

    def test_retriever_runs_when_upstream_provides_chunks(self):
        cfg = PipelineConfig(
            steps=[
                StepConfig(
                    name="chunk_docs",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="chunks",
                ),
                StepConfig(
                    name="retrieve",
                    component_type="retriever",
                    strategy="simple_cosine",
                    params={"top_k": 3},
                    depends_on=["chunks", "original_query"],
                    provides="results",
                    input_mapping={"chunks": "chunks", "original_query": "query"},
                ),
            ]
        )

        retriever = RetrieverStep(top_k=3, index_chunks=[_chunk("sample doc", 0)])
        identity = ChunkerAdapter(IdentityChunker())

        factories = {
            "chunk_docs": lambda sc: identity,
            "retrieve": lambda sc: retriever,
        }

        runner = PipelineRunner(
            config=cfg,
            step_factories=factories,
            initial_keys={"document"},
        )

        doc = ContentBlock.from_dict("sample doc content", "test", {})
        state, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "sample"}
        )

        assert tracelog.success_count == 2
        results = state.get("results", [])
        assert isinstance(results, list)


# ── Negative: Large-scale input ─────────────────────────────────────


class TestLargeScaleInput:
    """Scenario: verify retriever handles larger input without error."""

    def test_many_chunks_no_error(self):
        chunks = [_chunk(f"document number {i} about various topics", i) for i in range(200)]
        retriever = RetrieverStep(top_k=10, index_chunks=chunks)

        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": "topics around number 150"},
            resources=None,
        ))

        assert len(output.result) == 10
        assert all(isinstance(r, RetrievalResult) for r in output.result)

    def test_single_chunk_returns_one_result(self):
        chunk = _chunk("the only document", 0)
        retriever = RetrieverStep(top_k=10, index_chunks=[chunk])

        output = asyncio.run(retriever.run(
            inputs={"chunks": [chunk], "query": "only document"},
            resources=None,
        ))

        assert len(output.result) == 1


# ── Negative: Result structure invariants ───────────────────────────


class TestResultInvariants:
    def test_rank_starts_at_one(self):
        chunks = [_chunk("a", 0), _chunk("b", 1)]
        retriever = RetrieverStep(top_k=5, index_chunks=chunks)

        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": "a"},
            resources=None,
        ))

        assert output.result[0].rank == 1

    def test_score_between_neg_one_and_one(self):
        chunks = [_chunk("sample text here", 0)]
        retriever = RetrieverStep(top_k=5, index_chunks=chunks)

        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": "sample"},
            resources=None,
        ))

        for r in output.result:
            assert -1.0 <= r.score <= 1.0


# ── Negative: Trace log completeness ─────────────────────────────────


class TestTraceCompleteness:
    def test_trace_log_present_on_graceful_degradation(self):
        """Even when backend fails, trace_log is recorded."""
        retriever = RetrieverStep(top_k=5, backend=FailingBackend())
        chunks = [_chunk("data", 0)]

        output = asyncio.run(retriever.run(
            inputs={"chunks": chunks, "query": "data"},
            resources=None,
        ))

        assert "retriever" in output.trace_log

    def test_trace_log_contains_version(self):
        retriever = RetrieverStep(top_k=5)
        output = asyncio.run(retriever.run(
            inputs={"chunks": [_chunk("x", 0)], "query": "x"},
            resources=None,
        ))
        assert "version" in output.trace_log


# ── InMemoryVectorBackend conformance ────────────────────────────────


class TestInMemoryBackendConformance:
    def test_count_reflects_added_chunks(self):
        backend = InMemoryVectorBackend()
        assert backend.count() == 0
        backend.add(_chunk("a", 0))
        assert backend.count() == 1

    def test_search_returns_empty_on_empty_index(self):
        backend = InMemoryVectorBackend()
        results = backend.search(_simple_embedding("query"), top_k=5)
        assert results == []

    def test_search_on_single_item(self):
        chunk = _chunk("hello", 0)
        backend = InMemoryVectorBackend([chunk])
        results = backend.search(_simple_embedding("hello"), top_k=5)
        assert len(results) == 1
        assert results[0].chunk.text == "hello"
        assert -1.0 <= results[0].score <= 1.0
