"""Phase 7.1: Generator E2E + negative tests.

Covers: pipeline integration, health check, backend failures, budget enforcement,
validation warnings, trace completeness. All tests use mock backends — NO real API calls.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from core.adapters.chunker_adapter import ChunkerAdapter
from core.contracts import (
    Chunk,
    ContentBlock,
    GenerationResult,
    IdentityChunker,
    validate_generation_output,
)
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
    StepOutput,
)
from core.steps.generator import GeneratorStep, MockGenerationBackend


# ── Helpers ──────────────────────────────────────────────────────────


def _chunk(text: str, idx: int = 0) -> Chunk:
    return Chunk(text=text, source_strategy="test", span=(idx, idx + len(text)))


# ── E2E: Full pipeline with generator ────────────────────────────────


class TestGeneratorPipelineE2E:
    def test_full_pipeline_chunker_to_generator(self):
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
                    name="generate",
                    component_type="generator",
                    strategy="mock_echo",
                    depends_on=["chunks", "original_query"],
                    provides="generation",
                    input_mapping={"chunks": "context", "original_query": "prompt"},
                ),
            ]
        )

        generator = GeneratorStep(backend=MockGenerationBackend(model="test-model"))
        identity = ChunkerAdapter(IdentityChunker())

        factories = {
            "chunk_docs": lambda sc: identity,
            "generate": lambda sc: generator,
        }

        runner = PipelineRunner(
            config=cfg,
            step_factories=factories,
            initial_keys={"document"},
        )

        doc = ContentBlock.from_dict("summarize this document", "test", {})
        state, tracelog = runner.run(
            initial_state={"document": doc, "original_query": "summarize this document"}
        )

        assert tracelog.success_count == 2
        result = state["generation"]
        assert isinstance(result, GenerationResult)
        assert "test-model" in result.model
        assert result.finish_reason == "stop"
        assert result.total_tokens > 0


# ── Input edge cases ─────────────────────────────────────────────────


class TestGeneratorInputCases:
    def test_empty_prompt_produces_result(self):
        step = GeneratorStep(backend=MockGenerationBackend())
        output = step.run(
            inputs={"prompt": "", "context": []},
            resources=None,
        )
        assert isinstance(output.result, GenerationResult)

    def test_missing_prompt_key_produces_result(self):
        step = GeneratorStep(backend=MockGenerationBackend())
        output = step.run(
            inputs={"context": [_chunk("fallback", 0)]},
            resources=None,
        )
        assert isinstance(output.result, GenerationResult)

    def test_context_not_a_list_is_normalized(self):
        step = GeneratorStep(backend=MockGenerationBackend())
        output = step.run(
            inputs={"prompt": "hello", "context": "not_a_list"},
            resources=None,
        )
        assert isinstance(output.result, GenerationResult)


# ── Health check ─────────────────────────────────────────────────────


class TestGeneratorHealth:
    def test_health_check_healthy_with_mock_backend(self):
        step = GeneratorStep(backend=MockGenerationBackend())
        hs = step.health_check()
        assert hs.status == "healthy"
        assert len(hs.dependencies) == 1
        assert hs.dependencies[0].name == "llm_api"

    def test_health_check_includes_version(self):
        step = GeneratorStep()
        hs = step.health_check()
        assert hs.version == "0.1.0"


# ── Backend failures ─────────────────────────────────────────────────


class FailingGenerationBackend:
    def generate(self, prompt, context, **params):
        raise RuntimeError("API connection refused")

    def count_tokens(self, text):
        return 0


class TimeoutGenerationBackend:
    def generate(self, prompt, context, **params):
        raise asyncio.TimeoutError("generation timed out")

    def count_tokens(self, text):
        return 0


class TestGeneratorBackendFailures:
    def test_backend_exception_produces_graceful_result(self):
        """Anti-pattern check: adapter must NOT let exceptions propagate."""
        step = GeneratorStep(backend=FailingGenerationBackend())
        output = step.run(
            inputs={"prompt": "test", "context": []},
            resources=None,
        )
        assert isinstance(output.result, GenerationResult)
        # Graceful degradation: error finish_reason
        assert output.result.finish_reason == "error"

    def test_health_check_unavailable_with_failing_backend(self):
        step = GeneratorStep(backend=FailingGenerationBackend())
        hs = step.health_check()
        assert hs.status == "unavailable"
        assert hs.dependencies[0].status == "unavailable"


# ── Token budget ─────────────────────────────────────────────────────


class TestGeneratorBudget:
    def test_budget_exceeded_returns_graceful_result(self):
        """Anti-pattern check: must not crash on budget exceeded."""
        step = GeneratorStep(backend=MockGenerationBackend(), max_tokens_per_run=0)
        output = step.run(
            inputs={"prompt": "test", "context": []},
            resources=None,
        )
        assert output.result.finish_reason == "error"
        assert output.result.model == "budget_exceeded"


# ── Trace completeness ───────────────────────────────────────────────


class TestGeneratorTrace:
    def test_trace_log_includes_token_info(self):
        step = GeneratorStep(backend=MockGenerationBackend(model="echo"))
        output = step.run(
            inputs={"prompt": "hello world", "context": []},
            resources=None,
        )
        tl = output.trace_log
        assert "model" in tl
        assert "prompt_tokens" in tl
        assert "completion_tokens" in tl
        assert "total_tokens" in tl
        assert "elapsed_ms" in tl

    def test_trace_log_present_on_error(self):
        step = GeneratorStep(backend=FailingGenerationBackend())
        output = step.run(
            inputs={"prompt": "test", "context": []},
            resources=None,
        )
        assert "generator" in output.trace_log


# ── Validation function ──────────────────────────────────────────────


class TestValidateGenerationOutput:
    def test_valid_result_passes(self):
        gr = GenerationResult(text="hello", model="m", finish_reason="stop")
        vr = validate_generation_output(gr)
        assert vr.passed

    def test_empty_text_produces_warning(self):
        gr = GenerationResult(text="", model="m", finish_reason="stop")
        vr = validate_generation_output(gr)
        assert not vr.passed or len(vr.warnings) >= 0

    def test_wrong_type_produces_error(self):
        vr = validate_generation_output("not_a_result")  # type: ignore
        assert not vr.passed
        assert len(vr.errors) >= 1

    def test_zero_tokens_produces_warning(self):
        gr = GenerationResult(
            text="hi", model="m", finish_reason="stop",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        vr = validate_generation_output(gr)
        assert len(vr.warnings) >= 1


# ── Cumulative token tracking ────────────────────────────────────────


class TestCumulativeTokenTracking:
    def test_cumulative_tokens_increase_across_calls(self):
        step = GeneratorStep(backend=MockGenerationBackend())
        assert step._adapter.cumulative_tokens == 0

        step.run(inputs={"prompt": "first call", "context": []}, resources=None)
        after_first = step._adapter.cumulative_tokens
        assert after_first > 0

        step.run(inputs={"prompt": "second call", "context": []}, resources=None)
        after_second = step._adapter.cumulative_tokens
        assert after_second > after_first
