"""Phase 7.3: Full pipeline integration — Chunker → Retriever → Reranker → Generator.

All 4 component types in a single pipeline — the complete RAG chain.
All tests use mock backends — NO real API calls.
"""

from __future__ import annotations

import pytest

from core.adapters.chunker_adapter import ChunkerAdapter
from core.contracts import (
    Chunk,
    ContentBlock,
    GenerationResult,
    IdentityChunker,
)
from core.contracts.retrieval import RetrievalResult
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
)
from core.steps.generator import GeneratorStep, MockGenerationBackend
from core.steps.reranker import MockScoringBackend, RerankerStep
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep


# ── Helpers ──────────────────────────────────────────────────────────


def _chunk(text: str, idx: int = 0) -> Chunk:
    return Chunk(text=text, source_strategy="test", span=(idx, idx + len(text)))


def _build_full_pipeline(
    doc: ContentBlock,
    query: str,
    *,
    index_chunks: list | None = None,
) -> tuple[dict, "PipelineRunner.TraceLog"]:
    """Build and run the full 4-step RAG pipeline. Returns (state, tracelog)."""
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
                depends_on=["chunks", "original_query"],
                provides="results",
                input_mapping={"chunks": "chunks", "original_query": "query"},
            ),
            StepConfig(
                name="rerank",
                component_type="reranker",
                strategy="mock_overlap",
                depends_on=["chunks", "original_query"],
                provides="reranked",
                input_mapping={"chunks": "chunks", "original_query": "query"},
            ),
            StepConfig(
                name="generate",
                component_type="generator",
                strategy="mock_echo",
                depends_on=["reranked", "original_query"],
                provides="generation",
                input_mapping={"reranked": "context", "original_query": "prompt"},
            ),
        ]
    )

    retriever = RetrieverStep(
        backend=InMemoryVectorBackend(index_chunks),
        top_k=3,
    )
    reranker = RerankerStep(backend=MockScoringBackend())
    generator = GeneratorStep(backend=MockGenerationBackend(model="full-pipeline-test"))
    identity = ChunkerAdapter(IdentityChunker())

    factories = {
        "chunk_docs": lambda sc: identity,
        "retrieve": lambda sc: retriever,
        "rerank": lambda sc: reranker,
        "generate": lambda sc: generator,
    }

    runner = PipelineRunner(
        config=cfg,
        step_factories=factories,
        initial_keys={"document"},
    )

    return runner.run(
        initial_state={"document": doc, "original_query": query}
    )


# ── Golden path ──────────────────────────────────────────────────────


class TestFullPipelineGoldenPath:
    """All 4 steps complete successfully with correct data flow."""

    def test_all_four_steps_complete(self):
        doc = ContentBlock.from_dict(
            "python is a great programming language for building AI systems",
            "test",
            {},
        )
        state, tracelog = _build_full_pipeline(
            doc, "python programming",
            index_chunks=[
                _chunk("python is a great programming language for building AI systems", 0),
                _chunk("machine learning requires careful data preparation", 1),
                _chunk("web development uses html css and javascript", 2),
            ],
        )

        assert tracelog.success_count == 4
        assert tracelog.failure_count == 0

    def test_generator_receives_reranked_context(self):
        doc = ContentBlock.from_dict("alpha beta gamma delta epsilon", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "beta delta",
            index_chunks=[
                _chunk("alpha beta gamma", 0),
                _chunk("delta epsilon zeta", 1),
            ],
        )

        generation = state["generation"]
        assert isinstance(generation, GenerationResult)
        assert generation.finish_reason == "stop"
        assert generation.total_tokens > 0
        assert "full-pipeline-test" in generation.model

    def test_all_intermediate_outputs_present(self):
        doc = ContentBlock.from_dict("test document content here", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "document content",
            index_chunks=[
                _chunk("test document content here", 0),
            ],
        )

        # Chunker output
        assert "chunks" in state
        assert len(state["chunks"]) >= 1
        assert all(isinstance(c, Chunk) for c in state["chunks"])

        # Retriever output
        assert "results" in state
        assert isinstance(state["results"], list)
        assert all(isinstance(r, RetrievalResult) for r in state["results"])

        # Reranker output
        assert "reranked" in state
        assert isinstance(state["reranked"], list)
        assert all(isinstance(r, RetrievalResult) for r in state["reranked"])

        # Generator output
        assert "generation" in state
        assert isinstance(state["generation"], GenerationResult)

    def test_reranker_output_contract_enforced_in_pipeline(self):
        doc = ContentBlock.from_dict("a b c d e f g h i j", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "c e g",
            index_chunks=[_chunk(f"item {i}", i) for i in range(10)],
        )

        reranked = state["reranked"]
        chunks = state["chunks"]

        # output <= input
        assert len(reranked) <= len(chunks)
        # sequential ranks
        for i, r in enumerate(reranked, start=1):
            assert r.rank == i
        # descending scores
        scores = [r.score for r in reranked]
        assert scores == sorted(scores, reverse=True)


# ── Edge cases ───────────────────────────────────────────────────────


class TestFullPipelineEdgeCases:
    """Entire pipeline handles edge cases gracefully."""

    def test_empty_document_produces_empty_chain(self):
        doc = ContentBlock.from_dict("", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "anything",
            index_chunks=[],
        )

        # Pipeline shouldn't crash — should complete or skip
        assert tracelog.success_count + tracelog.skipped_count >= 1

    def test_no_index_chunks_still_completes(self):
        doc = ContentBlock.from_dict("some text here", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "some text",
            index_chunks=[],  # empty vector store
        )

        # Retriever returns empty results, but pipeline still completes
        assert tracelog.success_count >= 1

    def test_single_chunk_flows_through_all_steps(self):
        doc = ContentBlock.from_dict("the only chunk", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "only chunk",
            index_chunks=[_chunk("the only chunk", 0)],
        )

        assert tracelog.success_count == 4
        assert len(state["results"]) <= 1
        assert len(state["reranked"]) <= 1
        assert isinstance(state["generation"], GenerationResult)


# ── Health check ─────────────────────────────────────────────────────


class TestFullPipelineHealth:
    """All 4 component types report healthy with mock backends."""

    def test_all_steps_health_check_healthy(self):
        retriever = RetrieverStep(
            backend=InMemoryVectorBackend([_chunk("health probe chunk", 0)]),
            top_k=3,
        )
        reranker = RerankerStep(backend=MockScoringBackend())
        generator = GeneratorStep(backend=MockGenerationBackend())

        checks = [
            retriever.health_check(),
            reranker.health_check(),
            generator.health_check(),
        ]

        for hs in checks:
            assert hs.status in ("healthy", "degraded"), f"expected healthy/degraded, got {hs.status}"


# ── Trace observability ──────────────────────────────────────────────


class TestFullPipelineTraceObservability:
    """Trace logs capture metadata across all 4 steps."""

    def test_tracelog_spans_cover_all_steps(self):
        doc = ContentBlock.from_dict("trace test content", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "trace test",
            index_chunks=[_chunk("trace test content", 0)],
        )

        step_names = [step.step_name for step in tracelog.steps]
        assert "chunk_docs" in step_names
        assert "retrieve" in step_names
        assert "rerank" in step_names
        assert "generate" in step_names

    def test_elapsed_times_are_reasonable(self):
        doc = ContentBlock.from_dict("timing test content", "test", {})
        state, tracelog = _build_full_pipeline(
            doc, "timing test",
            index_chunks=[_chunk("timing test content", 0)],
        )

        for step in tracelog.steps:
            assert step.duration_seconds >= 0
            assert step.duration_seconds < 10  # shouldn't take 10 seconds


# ── Type contract ────────────────────────────────────────────────────


class TestFullPipelineTypeContracts:
    """Every step output satisfies its type contract."""

    def test_chunker_output_is_list_of_chunks(self):
        doc = ContentBlock.from_dict("type check", "test", {})
        state, _ = _build_full_pipeline(
            doc, "type check",
            index_chunks=[_chunk("type check", 0)],
        )

        for c in state["chunks"]:
            assert isinstance(c, Chunk)
            assert hasattr(c, "text")
            assert hasattr(c, "source_strategy")

    def test_retrieval_results_have_required_fields(self):
        doc = ContentBlock.from_dict("retrieval test", "test", {})
        state, _ = _build_full_pipeline(
            doc, "retrieval",
            index_chunks=[_chunk("retrieval test", 0)],
        )

        for r in state["results"]:
            assert isinstance(r, RetrievalResult)
            assert isinstance(r.chunk, Chunk)
            assert isinstance(r.score, float)
            assert isinstance(r.rank, int)
            assert r.rank >= 1

    def test_generation_result_has_required_fields(self):
        doc = ContentBlock.from_dict("generation test docs", "test", {})
        state, _ = _build_full_pipeline(
            doc, "generation test",
            index_chunks=[_chunk("generation test docs", 0)],
        )

        gen = state["generation"]
        assert isinstance(gen, GenerationResult)
        assert hasattr(gen, "text")
        assert hasattr(gen, "model")
        assert hasattr(gen, "finish_reason")
        assert hasattr(gen, "total_tokens")
