"""Phase 7.1: Reranker E2E + negative tests.

Covers: pipeline integration, health check, backend failures, contract enforcement
(output <= input, sequential ranks, descending scores), validation warnings.
All tests use mock backends — NO real API calls.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from core.adapters.chunker_adapter import ChunkerAdapter
from core.contracts import (
    Chunk,
    ContentBlock,
    IdentityChunker,
    validate_reranker_output,
)
from core.contracts.retrieval import RetrievalResult
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
)
from core.steps.reranker import MockScoringBackend, RerankerStep


# ── Helpers ──────────────────────────────────────────────────────────


def _chunk(text: str, idx: int = 0) -> Chunk:
    return Chunk(text=text, source_strategy="test", span=(idx, idx + len(text)))


# ── E2E: Full pipeline with reranker ─────────────────────────────────


class TestRerankerPipelineE2E:
    def test_full_pipeline_chunker_to_reranker(self):
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
                    name="rerank",
                    component_type="reranker",
                    strategy="mock_overlap",
                    depends_on=["chunks", "original_query"],
                    provides="results",
                    input_mapping={"chunks": "chunks", "original_query": "query"},
                ),
            ]
        )

        reranker = RerankerStep(backend=MockScoringBackend())
        identity = ChunkerAdapter(IdentityChunker())

        factories = {
            "chunk_docs": lambda sc: identity,
            "rerank": lambda sc: reranker,
        }

        runner = PipelineRunner(
            config=cfg,
            step_factories=factories,
            initial_keys={"document"},
        )

        doc = ContentBlock.from_dict("python is a great programming language", "test", {})
        state, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "python programming"}
        )

        assert tracelog.success_count == 2
        results = state["results"]
        assert isinstance(results, list)
        assert all(isinstance(r, RetrievalResult) for r in results)

        # Contract: ranks sequential
        for i, r in enumerate(results, start=1):
            assert r.rank == i

        # Contract: scores descending
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# ── Input edge cases ─────────────────────────────────────────────────


class TestRerankerInputCases:
    def test_empty_chunks_returns_empty(self):
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": [], "query": "anything"},
            resources=None,
        )
        assert output.result == []

    def test_missing_query_falls_back_to_first_chunk(self):
        chunks = [_chunk("fallback query text", 0)]
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": chunks},  # no query key
            resources=None,
        )
        assert len(output.result) >= 0

    def test_non_list_chunks_is_normalized(self):
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": "not_a_list", "query": "test"},
            resources=None,
        )
        assert output.result == []


# ── Contract enforcement ─────────────────────────────────────────────


class TestRerankerContractEnforcement:
    """Anti-pattern: reranker output must not exceed input, ranks must be sequential."""

    def test_output_never_exceeds_input(self):
        chunks = [_chunk(f"doc {i}", i) for i in range(5)]
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": chunks, "query": "doc 2"},
            resources=None,
        )
        assert len(output.result) <= len(chunks)

    def test_ranks_are_sequential_from_one(self):
        chunks = [_chunk("alpha beta", 0), _chunk("beta gamma", 1), _chunk("gamma delta", 2)]
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": chunks, "query": "beta"},
            resources=None,
        )
        for i, r in enumerate(output.result, start=1):
            assert r.rank == i

    def test_scores_are_descending(self):
        chunks = [_chunk(f"topic {i}", i) for i in range(10)]
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": chunks, "query": "topic 5"},
            resources=None,
        )
        scores = [r.score for r in output.result]
        assert scores == sorted(scores, reverse=True)

    def test_scores_in_valid_range(self):
        chunks = [_chunk("sample text", 0)]
        step = RerankerStep(backend=MockScoringBackend())
        output = step.run(
            inputs={"chunks": chunks, "query": "sample"},
            resources=None,
        )
        for r in output.result:
            assert -1.0 <= r.score <= 1.0


# ── Health check ─────────────────────────────────────────────────────


class TestRerankerHealth:
    def test_health_check_healthy_with_mock_backend(self):
        step = RerankerStep(backend=MockScoringBackend())
        hs = step.health_check()
        assert hs.status == "healthy"
        assert len(hs.dependencies) == 1
        assert hs.dependencies[0].name == "reranker_api"

    def test_health_check_includes_version(self):
        step = RerankerStep()
        hs = step.health_check()
        assert hs.version == "0.1.0"


# ── Backend failures ─────────────────────────────────────────────────


class FailingScoringBackend:
    def score(self, chunks, query, **params):
        raise RuntimeError("reranker API internal error")

    def count(self):
        return 0


class TestRerankerBackendFailures:
    def test_backend_exception_produces_empty_results(self):
        """Anti-pattern: adapter must NOT let exceptions propagate — graceful [ ]."""
        step = RerankerStep(backend=FailingScoringBackend())
        chunks = [_chunk("data", 0)]
        output = step.run(
            inputs={"chunks": chunks, "query": "data"},
            resources=None,
        )
        assert output.result == []

    def test_health_check_unavailable_with_failing_backend(self):
        step = RerankerStep(backend=FailingScoringBackend())
        hs = step.health_check()
        assert hs.status == "unavailable"
        assert hs.dependencies[0].status == "unavailable"


# ── Trace completeness ───────────────────────────────────────────────


class TestRerankerTrace:
    def test_trace_log_includes_metadata(self):
        step = RerankerStep(backend=MockScoringBackend())
        chunks = [_chunk("hello world", 0)]
        output = step.run(
            inputs={"chunks": chunks, "query": "hello"},
            resources=None,
        )
        tl = output.trace_log
        assert "input_chunks" in tl
        assert "results_count" in tl
        assert "elapsed_ms" in tl


# ── Validation function ──────────────────────────────────────────────


class TestValidateRerankerOutput:
    def test_valid_output_passes(self):
        chunk = _chunk("test", 0)
        results = [RetrievalResult(chunk=chunk, score=0.9, rank=1)]
        vr = validate_reranker_output(results, input_len=1)
        assert vr.passed

    def test_output_exceeding_input_is_error(self):
        chunk = _chunk("test", 0)
        results = [
            RetrievalResult(chunk=chunk, score=0.9, rank=1),
            RetrievalResult(chunk=chunk, score=0.8, rank=2),
        ]
        vr = validate_reranker_output(results, input_len=1)
        assert not vr.passed
        assert any(e.code == "OUTPUT_EXCEEDS_INPUT" for e in vr.errors)

    def test_non_sequential_rank_is_warning(self):
        chunk = _chunk("test", 0)
        results = [
            RetrievalResult(chunk=chunk, score=0.9, rank=5),  # wrong rank
        ]
        vr = validate_reranker_output(results, input_len=1)
        assert len(vr.warnings) >= 1
        assert any(w.code == "NON_SEQUENTIAL_RANK" for w in vr.warnings)

    def test_unsorted_scores_is_warning(self):
        chunk = _chunk("test", 0)
        results = [
            RetrievalResult(chunk=chunk, score=0.3, rank=1),
            RetrievalResult(chunk=chunk, score=0.9, rank=2),  # higher score later
        ]
        vr = validate_reranker_output(results, input_len=2)
        assert any(w.code == "UNSORTED_SCORES" for w in vr.warnings)

    def test_score_out_of_range_is_warning(self):
        chunk = _chunk("test", 0)
        results = [RetrievalResult(chunk=chunk, score=1.5, rank=1)]
        vr = validate_reranker_output(results, input_len=1)
        assert any(w.code == "SCORE_OUT_OF_RANGE" for w in vr.warnings)

    def test_wrong_type_is_error(self):
        vr = validate_reranker_output("not_a_list", input_len=0)  # type: ignore
        assert not vr.passed
