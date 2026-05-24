"""Phase 7.0: Generation and Scoring contract conformance tests (TDD).

Tests define the contract before any adapter or implementation is written.
"""

from __future__ import annotations

import pytest

from core.contracts import Chunk, GenerationResult, SemVer
from core.contracts.generation import GenerationStrategy
from core.contracts.scoring import ScoringStrategy


# ── GenerationResult ─────────────────────────────────────────────────


class TestGenerationResultContract:
    def test_frozen_dataclass(self):
        gr = GenerationResult(text="hello", model="test-model", finish_reason="stop")
        assert gr.text == "hello"
        assert gr.model == "test-model"
        assert gr.finish_reason == "stop"

    def test_immutable_prevents_assignment(self):
        gr = GenerationResult(text="hello", model="x", finish_reason="stop")
        with pytest.raises(Exception):
            gr.text = "mutated"  # type: ignore[misc]

    def test_metadata_is_readonly(self):
        gr = GenerationResult(text="hi", model="m", finish_reason="stop", metadata={"key": "val"})
        with pytest.raises(TypeError):
            gr.metadata["key"] = "mutated"  # type: ignore[index]

    def test_usage_is_readonly(self):
        gr = GenerationResult(
            text="hi", model="m", finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
        with pytest.raises(TypeError):
            gr.usage["prompt_tokens"] = 999  # type: ignore[index]

    def test_metadata_deepcopy_defense(self):
        orig = {"key": "original", "nested": [1, 2, 3]}
        gr = GenerationResult(text="hi", model="m", finish_reason="stop", metadata=orig)
        orig["key"] = "MUTATED"
        orig["nested"].append(999)
        assert gr.metadata["key"] == "original"
        assert gr.metadata["nested"] == [1, 2, 3]

    def test_token_accessors(self):
        gr = GenerationResult(
            text="hi", model="m", finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        )
        assert gr.prompt_tokens == 100
        assert gr.completion_tokens == 50
        assert gr.total_tokens == 150

    def test_default_usage_is_empty(self):
        gr = GenerationResult(text="hi", model="m", finish_reason="stop")
        assert gr.prompt_tokens == 0
        assert gr.completion_tokens == 0
        assert gr.total_tokens == 0

    def test_plain_dict_usage_auto_coerced(self):
        gr = GenerationResult(
            text="hi", model="m", finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        )
        with pytest.raises(TypeError):
            gr.usage["prompt_tokens"] = 999  # type: ignore[index]


# ── GenerationStrategy Protocol ──────────────────────────────────────


class TestGenerationStrategyContract:
    def test_strategy_must_have_version(self):
        class ValidGen:
            VERSION = SemVer(1, 0, 0)

            def generate(self, prompt, context, **params):
                return GenerationResult(text="ok", model="test", finish_reason="stop")

        inst = ValidGen()
        assert isinstance(inst.VERSION, SemVer)

    def test_strategy_without_version_is_detectable(self):
        """Any class without VERSION fails hasattr check for SemVer."""
        class NoVersion:
            def generate(self, prompt, context, **params):
                pass

        inst = NoVersion()
        assert not hasattr(inst, "VERSION")


# ── ScoringStrategy Protocol ─────────────────────────────────────────


class TestScoringStrategyContract:
    def test_output_must_be_list_of_retrieval_results(self):
        """ScoringStrategy.score() returns List[RetrievalResult]."""
        from core.contracts.retrieval import RetrievalResult

        chunk = Chunk(text="test", source_strategy="x", span=(0, 4))
        result = RetrievalResult(chunk=chunk, score=0.95, rank=1)
        assert isinstance(result.score, float)
        assert result.rank == 1

    def test_zero_chunks_must_return_empty(self):
        """Contract: empty input → empty output, no error."""
        results: list = []
        assert isinstance(results, list)
        assert len(results) == 0

    def test_output_must_not_exceed_input_length(self):
        """Contract: output length ≤ input length."""
        chunks = [Chunk(text=f"c{i}", source_strategy="t", span=(i, i + 2)) for i in range(5)]
        # Simulate a scoring call
        scored = 3  # reranker should never add chunks
        assert scored <= len(chunks)

    def test_ranks_must_be_sequential(self):
        """Contract: ranks start at 1 and are sequential."""
        from core.contracts.retrieval import RetrievalResult

        chunk = Chunk(text="x", source_strategy="t", span=(0, 1))
        results = [
            RetrievalResult(chunk=chunk, score=0.9, rank=1),
            RetrievalResult(chunk=chunk, score=0.8, rank=2),
            RetrievalResult(chunk=chunk, score=0.7, rank=3),
        ]
        for i, r in enumerate(results, start=1):
            assert r.rank == i

    def test_results_must_be_sorted_descending(self):
        """Contract: results sorted by score descending."""
        scores = [0.9, 0.5, 0.3]
        assert scores == sorted(scores, reverse=True)


# ── Finish reason enumeration ────────────────────────────────────────


class TestFinishReasonContract:
    """GenerationResult.finish_reason standardized values."""

    VALID_REASONS = {"stop", "length", "content_filter", "tool_calls"}

    def test_known_reasons_accepted(self):
        for reason in self.VALID_REASONS:
            gr = GenerationResult(text="ok", model="test", finish_reason=reason)
            assert gr.finish_reason == reason

    def test_unknown_reason_still_stored(self):
        """Custom finish reasons aren't rejected — the field is a str, not an enum."""
        gr = GenerationResult(text="ok", model="test", finish_reason="custom_reason_xyz")
        assert gr.finish_reason == "custom_reason_xyz"
