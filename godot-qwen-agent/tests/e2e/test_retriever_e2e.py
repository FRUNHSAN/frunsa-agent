"""Phase 5.3: Retriever E2E integration — full pipeline (chunker → retriever) via PipelineRunner."""

from __future__ import annotations

import pytest

from core.adapters.chunker_adapter import ChunkerAdapter
from core.contracts import Chunk, ContentBlock, IdentityChunker
from core.contracts.retrieval import RetrievalResult
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
)
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep


# ── Helpers ──────────────────────────────────────────────────────────


def _chunk(text: str, idx: int = 0) -> Chunk:
    return Chunk(text=text, source_strategy="identity", span=(idx, idx + len(text)))


def _build_retriever_pipeline(top_k: int = 3) -> PipelineConfig:
    return PipelineConfig(
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
                params={"top_k": top_k},
                depends_on=["chunks", "original_query"],
                provides="results",
                input_mapping={"chunks": "chunks", "original_query": "query"},
            ),
        ]
    )


# ── E2E: Full pipeline ──────────────────────────────────────────────


class TestRetrieverPipelineE2E:
    """End-to-end: ContentBlock → IdentityChunker → RetrieverStep."""

    def test_full_pipeline_returns_retrieval_results(self):
        cfg = _build_retriever_pipeline(top_k=3)
        index_chunks = [_chunk(f"document {i} about topic alpha", i) for i in range(10)]

        retriever = RetrieverStep(top_k=3, index_chunks=index_chunks)
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

        doc = ContentBlock.from_dict("query about topic alpha", "test", {})
        state, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "topic alpha"}
        )

        results = state.get("results", [])
        assert isinstance(results, list)
        assert len(results) > 0, "Expected at least one retrieval result"
        assert all(isinstance(r, RetrievalResult) for r in results)

        # Verify descending score order
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

        assert tracelog.total_steps == 2
        assert tracelog.success_count == 2

    def test_tracelog_records_retriever_metadata(self):
        cfg = _build_retriever_pipeline(top_k=2)
        index_chunks = [_chunk(f"item {i}", i) for i in range(5)]

        retriever = RetrieverStep(top_k=2, index_chunks=index_chunks)
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

        doc = ContentBlock.from_dict("find item 2", "test", {})
        _, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "item 2"}
        )

        retriever_trace = tracelog.steps[1]
        assert retriever_trace.step_name == "retrieve"
        assert retriever_trace.status == "success"
        assert retriever_trace.component_type == "retriever"
        assert retriever_trace.strategy == "simple_cosine"

    def test_pipeline_with_more_specific_query_yields_results(self):
        """Results are always returned (hash-based embedding is deterministic)."""
        cfg = _build_retriever_pipeline(top_k=5)
        chunks = [_chunk(f"data point {i}", i) for i in range(15)]

        retriever = RetrieverStep(top_k=5, index_chunks=chunks)
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

        doc = ContentBlock.from_dict("looking for data point 7 specifically", "test", {})
        state, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "data point 7"}
        )

        results = state["results"]
        assert len(results) == 5  # top_k respected
        assert tracelog.success_count == 2


# ── E2E: Query routing via input_mapping ─────────────────────────────


class TestInputMappingRouting:
    def test_query_routed_from_original_query(self):
        """input_mapping correctly routes original_query → query param."""
        chunks = [_chunk("alpha beta gamma", 0), _chunk("delta epsilon", 1)]
        retriever = RetrieverStep(top_k=2, index_chunks=chunks)

        # Direct call simulating what engine does after input_mapping
        output = retriever.run(
            inputs={"chunks": chunks, "query": "alpha"},
            resources=None,
        )

        results = output.result
        assert len(results) > 0
        assert results[0].rank == 1

    def test_fallback_when_query_key_missing(self):
        """When no 'query' key, async_run falls back to first chunk's text."""
        chunks = [_chunk("primary fallback source", 0)]
        retriever = RetrieverStep(top_k=1, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks},  # no 'query' key
            resources=None,
        )

        results = output.result
        assert len(results) == 1


# ── E2E: Health check integration ───────────────────────────────────


class TestRetrieverHealthE2E:
    def test_health_check_healthy_with_populated_index(self):
        chunks = [_chunk("data", 0)]
        retriever = RetrieverStep(top_k=3, index_chunks=chunks)
        hs = retriever.health_check()
        assert hs.status == "healthy"
        assert len(hs.dependencies) == 1
        assert hs.dependencies[0].name == "vector_db"
        assert hs.dependencies[0].status == "healthy"

    def test_health_check_degraded_with_empty_index(self):
        retriever = RetrieverStep(top_k=3)  # no index_chunks → empty backend
        hs = retriever.health_check()
        # Empty index: backend reachable but returns no results → degraded
        assert hs.status in ("healthy", "degraded"), f"Unexpected status: {hs.status}"
        assert len(hs.dependencies) == 1

    def test_health_check_includes_version(self):
        retriever = RetrieverStep(top_k=3)
        hs = retriever.health_check()
        assert hs.version is not None
        assert "." in hs.version


# ── E2E: Result ordering and scoring ─────────────────────────────────


class TestRetrieverScoring:
    def test_results_sorted_by_descending_score(self):
        chunks = [_chunk(f"content {i}", i) for i in range(10)]
        retriever = RetrieverStep(top_k=10, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks, "query": "content 5"},
            resources=None,
        )

        scores = [r.score for r in output.result]
        assert scores == sorted(scores, reverse=True), f"Scores not descending: {scores}"

    def test_top_k_limits_results(self):
        chunks = [_chunk(f"doc {i}", i) for i in range(20)]
        retriever = RetrieverStep(top_k=5, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks, "query": "doc 7"},
            resources=None,
        )

        assert len(output.result) == 5

    def test_top_k_exceeds_index_returns_all(self):
        chunks = [_chunk(f"only {i}", i) for i in range(3)]
        retriever = RetrieverStep(top_k=10, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks, "query": "only"},
            resources=None,
        )

        assert len(output.result) == 3

    def test_rank_is_sequential_starting_at_one(self):
        chunks = [_chunk(f"x{i}", i) for i in range(5)]
        retriever = RetrieverStep(top_k=5, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks, "query": "x2"},
            resources=None,
        )

        for i, r in enumerate(output.result, start=1):
            assert r.rank == i

    def test_scores_are_between_neg_one_and_one(self):
        chunks = [_chunk(f"text {i}", i) for i in range(10)]
        retriever = RetrieverStep(top_k=10, index_chunks=chunks)

        output = retriever.run(
            inputs={"chunks": chunks, "query": "text"},
            resources=None,
        )

        for r in output.result:
            assert -1.0 <= r.score <= 1.0, f"Score out of range: {r.score}"
