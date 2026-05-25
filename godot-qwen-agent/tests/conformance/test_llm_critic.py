"""Conformance tests for LLMCriticEngine + MockCriticBackend.

Phase 18 Task 3: Validates Protocol conformance, trace key completeness,
parser correctness, and deterministic mock behavior.
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.critic.identity import CriticAgent
from engines.critic.interface import CriticContext
from engines.critic.llm import (
    DEFAULT_DECOMPOSITION_RESPONSE,
    DEFAULT_DISPATCH_RESPONSE,
    DEFAULT_SYNTHESIS_RESPONSE,
    LLMCriticEngine,
    MockCriticBackend,
    _parse_critic_evaluation,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _default_context() -> CriticContext:
    return CriticContext(
        plan_output="Goal: test task. Steps: [1. analyze, 2. execute, 3. verify]",
        agent_identity=CriticAgent(
            id="critic-v1", role="critic", version="1.0.0",
            capabilities=("result_evaluation",),
        ),
    )


def _default_adapter() -> GenerationAdapter:
    backend = MockCriticBackend(responses=(
        DEFAULT_DECOMPOSITION_RESPONSE,
        DEFAULT_DISPATCH_RESPONSE,
        DEFAULT_SYNTHESIS_RESPONSE,
    ))
    return GenerationAdapter(backend, dependency_name="mock_critic")


async def _collect(engine: LLMCriticEngine, context=None, deadline=5.0):
    items = []
    ctx = context or _default_context()
    async for item in engine.evaluate(ctx, deadline, PaceConfig()):
        items.append(item)
    return items


# ── TestMockCriticBackend ──────────────────────────────────────────────


class TestMockCriticBackend:
    """MockCriticBackend implements GenerationBackend Protocol deterministically."""

    def test_generate_returns_generation_result(self):
        backend = MockCriticBackend(responses=('{"score": 1.0, "verdict": "accept"}',))
        result = backend.generate("prompt", [])
        assert isinstance(result, GenerationResult)
        assert result.model == "mock/critic"

    def test_count_tokens_estimates_by_word_split(self):
        backend = MockCriticBackend(responses=())
        tokens = backend.count_tokens("hello world test critic")
        assert tokens > 0

    def test_round_robin_cycles_responses(self):
        backend = MockCriticBackend(responses=(
            DEFAULT_DECOMPOSITION_RESPONSE,
            DEFAULT_DISPATCH_RESPONSE,
            DEFAULT_SYNTHESIS_RESPONSE,
        ))
        r1 = backend.generate("p1", [])
        assert "accept" in r1.text and "0.85" in r1.text
        r2 = backend.generate("p2", [])
        assert "rework" in r2.text and "0.72" in r2.text
        r3 = backend.generate("p3", [])
        assert "accept" in r3.text and "0.90" in r3.text
        r4 = backend.generate("p4", [])
        assert "0.85" in r4.text

    def test_is_frozen_dataclass(self):
        backend = MockCriticBackend(responses=("x",))
        with pytest.raises(FrozenInstanceError):
            backend.responses = ("y",)

    def test_default_responses_match_stub_values(self):
        backend = MockCriticBackend(responses=(
            DEFAULT_DECOMPOSITION_RESPONSE,
            DEFAULT_DISPATCH_RESPONSE,
            DEFAULT_SYNTHESIS_RESPONSE,
        ))
        r1 = backend.generate("p1", []).text
        assert "0.85" in r1
        r2 = backend.generate("p2", []).text
        assert "0.72" in r2
        r3 = backend.generate("p3", []).text
        assert "0.90" in r3


# ── TestParser ─────────────────────────────────────────────────────────


class TestParser:
    """Critic evaluation parser handles valid and edge-case inputs."""

    def test_parse_valid_accept(self):
        data = _parse_critic_evaluation(DEFAULT_DECOMPOSITION_RESPONSE)
        assert data["score"] == 0.85
        assert data["verdict"] == "accept"

    def test_parse_valid_rework(self):
        data = _parse_critic_evaluation(DEFAULT_DISPATCH_RESPONSE)
        assert data["score"] == 0.72
        assert data["verdict"] == "rework"

    def test_parse_valid_reject(self):
        data = _parse_critic_evaluation(
            '{"score": 0.1, "verdict": "reject", "reasoning": "Bad plan"}'
        )
        assert data["verdict"] == "reject"

    def test_parse_markdown_fenced(self):
        text = '```json\n{"score": 0.5, "verdict": "accept", "reasoning": "ok"}\n```'
        data = _parse_critic_evaluation(text)
        assert data["score"] == 0.5

    def test_parse_missing_score_raises(self):
        with pytest.raises(ValueError):
            _parse_critic_evaluation('{"verdict": "accept"}')

    def test_parse_missing_verdict_raises(self):
        with pytest.raises(ValueError):
            _parse_critic_evaluation('{"score": 0.5}')

    def test_parse_invalid_verdict_raises(self):
        with pytest.raises(ValueError):
            _parse_critic_evaluation('{"score": 0.5, "verdict": "unknown"}')

    def test_parse_malformed_json_raises(self):
        with pytest.raises(ValueError):
            _parse_critic_evaluation("not json")

    def test_parse_empty_string_raises(self):
        with pytest.raises(ValueError):
            _parse_critic_evaluation("")


# ── TestLLMCriticConformance ───────────────────────────────────────────


class TestLLMCriticConformance:
    """LLMCriticEngine conforms to CriticEngine Protocol."""

    def test_yields_three_stream_items(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        assert len(items) == 3

    def test_terminal_item_present(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        assert items[-1].is_terminal
        assert items[-1].finish_reason == "stop"

    def test_critic_score_key_present(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert "critic.score" in (item.trace_context or {})

    def test_critic_verdict_key_present(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert "critic.verdict" in (item.trace_context or {})
            assert item.trace_context["critic.verdict"] in ("accept", "rework", "reject")

    def test_agent_identity_present(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert "agent.identity" in (item.trace_context or {})
            assert item.trace_context["agent.identity"]["role"] == "critic"

    def test_scores_are_floats(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert isinstance(item.trace_context["critic.score"], float)

    def test_deadline_enforcement(self):
        engine = LLMCriticEngine(_default_adapter())
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_collect(engine, deadline=0.0))

    def test_model_field_is_critic_llm(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert item.model == "critic/llm"


# ── TestEdgeCases ──────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case handling for LLMCriticEngine."""

    def test_error_on_bad_response_produces_error_terminal(self):
        backend = MockCriticBackend(responses=("not json", "also bad", "still bad"))
        adapter = GenerationAdapter(backend, dependency_name="mock_critic")
        engine = LLMCriticEngine(adapter)
        items = asyncio.run(_collect(engine))
        assert items[-1].is_terminal
        assert items[-1].finish_reason == "error"

    def test_empty_plan_output_accepted(self):
        ctx = CriticContext(
            plan_output="",
            agent_identity=CriticAgent(
                id="c", role="critic", version="1.0.0",
            ),
        )
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine, context=ctx))
        assert len(items) == 3

    def test_identity_has_llm_backed_capability(self):
        engine = LLMCriticEngine(_default_adapter())
        assert "llm_backed" in engine.identity.capabilities

    def test_metadata_in_context_accepted(self):
        ctx = CriticContext(
            plan_output="test plan",
            agent_identity=CriticAgent(
                id="c", role="critic", version="1.0.0",
            ),
            metadata={"source": "test", "debug": True},
        )
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine, context=ctx))
        assert len(items) == 3

    def test_scores_within_valid_range(self):
        engine = LLMCriticEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            score = item.trace_context["critic.score"]
            assert 0.0 <= score <= 1.0
