"""Conformance tests: MockLLMBackend, parser, LLMPlanningEngine (Phase 17).

Four test classes:
  1. TestMockLLMBackend — deterministic generation, token counting
  2. TestPlanningOutputParser — JSON parsing, edge cases
  3. TestLLMPlanningEngineConformance — Protocol compliance, trace keys
  4. TestLLMPlanningEdgeCases — deadline, errors, token budget
"""

from __future__ import annotations

import asyncio

import pytest

from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext
from engines.planning.llm import (
    LLMPlanningEngine,
    MockLLMBackend,
    DEFAULT_DECOMPOSE_RESPONSE,
    DEFAULT_SYNTHESIZE_RESPONSE,
    _parse_planning_steps,
    _parse_synthesis,
)

from tests.conftest import async_collect


# ── Helpers ────────────────────────────────────────────────────────────

class _MockAdapter:
    """Minimal async adapter wrapping MockLLMBackend for conformance tests."""

    def __init__(self, backend: MockLLMBackend):
        self._backend = backend

    async def generate(self, prompt, context, **params):
        return self._backend.generate(prompt, context, **params)


def _make_context(**kwargs) -> PlanningContext:
    return PlanningContext(
        goal=kwargs.get("goal", "Test goal"),
        agent_identity=kwargs.get("agent_identity", AgentIdentity(
            id="planner-v1", role="planning", version="1.0.0",
        )),
        sub_tasks=kwargs.get("sub_tasks", ()),
    )


def _make_engine():
    backend = MockLLMBackend(
        responses=(DEFAULT_DECOMPOSE_RESPONSE, DEFAULT_SYNTHESIZE_RESPONSE),
    )
    return LLMPlanningEngine(_MockAdapter(backend))


# ── TestMockLLMBackend ────────────────────────────────────────────────


class TestMockLLMBackend:
    """Deterministic mock backend contract tests."""

    def test_basic_generate_returns_generation_result(self):
        backend = MockLLMBackend(responses=("hello",))
        result = backend.generate("prompt", [])
        assert isinstance(result, GenerationResult)
        assert result.text == "hello"
        assert result.model == "mock/planning"
        assert result.finish_reason == "stop"

    def test_round_robin_responses(self):
        backend = MockLLMBackend(responses=("a", "b", "c"))
        assert backend.generate("p", []).text == "a"
        assert backend.generate("p", []).text == "b"
        assert backend.generate("p", []).text == "c"
        assert backend.generate("p", []).text == "a"

    def test_token_counting_positive(self):
        backend = MockLLMBackend(responses=("test",))
        tokens = backend.count_tokens("hello world")
        assert tokens >= 1
        assert isinstance(tokens, int)

    def test_usage_includes_token_counts(self):
        backend = MockLLMBackend(responses=("response text here",))
        result = backend.generate("prompt text for token counting", [])
        assert "prompt_tokens" in result.usage
        assert "completion_tokens" in result.usage
        assert "total_tokens" in result.usage
        assert result.usage["total_tokens"] == (
            result.usage["prompt_tokens"] + result.usage["completion_tokens"]
        )

    def test_empty_responses_tuple_round_robin(self):
        backend = MockLLMBackend(responses=("only",))
        for _ in range(10):
            assert backend.generate("p", []).text == "only"


# ── TestPlanningOutputParser ───────────────────────────────────────────


class TestPlanningOutputParser:
    """Output parser conformance tests."""

    def test_parse_valid_json_array(self):
        steps = _parse_planning_steps(DEFAULT_DECOMPOSE_RESPONSE)
        assert len(steps) == 3
        assert steps[0].step_index == 0
        assert steps[0].reasoning_depth == 0
        assert steps[0].parent_step_id is None
        assert not steps[0].is_terminal
        assert steps[-1].is_terminal

    def test_parse_markdown_fenced_json(self):
        raw = (
            '```json\n'
            '[{"step_id": 0, "depth": 0, "parent_id": null, '
            '"content": "test", "is_terminal": true}]\n'
            '```'
        )
        steps = _parse_planning_steps(raw)
        assert len(steps) == 1
        assert steps[0].content == "test"
        assert steps[0].is_terminal

    def test_parse_json_with_extra_fields_ignores_them(self):
        raw = (
            '[{"step_id": 0, "depth": 0, "parent_id": null, '
            '"content": "ok", "is_terminal": false, "extra": "ignored"}]'
        )
        steps = _parse_planning_steps(raw)
        assert len(steps) == 1
        assert steps[0].content == "ok"

    def test_parse_missing_optional_fields_uses_defaults(self):
        raw = '[{"step_id": 0, "content": "minimal"}]'
        steps = _parse_planning_steps(raw)
        assert len(steps) == 1
        assert steps[0].reasoning_depth == 0
        assert steps[0].parent_step_id is None
        assert not steps[0].is_terminal

    def test_parse_non_json_raises_valueerror(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_planning_steps("not json at all")

    def test_parse_non_array_raises_valueerror(self):
        with pytest.raises(ValueError, match="Expected JSON array"):
            _parse_planning_steps('{"not": "an array"}')

    def test_parse_empty_list_raises_valueerror(self):
        with pytest.raises(ValueError, match="empty step list"):
            _parse_planning_steps("[]")

    def test_parse_synthesis_valid(self):
        text = _parse_synthesis(DEFAULT_SYNTHESIZE_RESPONSE)
        assert len(text) > 0
        assert isinstance(text, str)

    def test_parse_synthesis_markdown_fenced(self):
        raw = '```json\n{"content": "conclusion text"}\n```'
        text = _parse_synthesis(raw)
        assert text == "conclusion text"

    def test_parse_synthesis_non_json_raises_valueerror(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_synthesis("not json")


# ── TestLLMPlanningEngineConformance ───────────────────────────────────


class TestLLMPlanningEngineConformance:
    """LLMPlanningEngine Protocol compliance tests."""

    def test_produces_stream_items(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert len(items) > 0
        assert all(isinstance(i, StreamItem) for i in items)

    def test_last_item_is_terminal(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert items[-1].is_terminal

    def test_all_items_have_agent_identity(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        for item in items:
            assert item.trace_context is not None
            assert "agent.identity" in item.trace_context

    def test_all_items_have_planning_step_index(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        for item in items:
            assert "planning.step_index" in item.trace_context
            assert isinstance(item.trace_context["planning.step_index"], int)

    def test_cumulative_tokens_tracks_usage(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert items[-1].trace_context["planning.cumulative_tokens"] > 0

    def test_orchestration_keys_passthrough(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        orch_items = [i for i in items
                      if i.trace_context
                      and "orchestration.dag_node_id" in i.trace_context]
        assert len(orch_items) > 0, "Expected orchestration pass-through items"

    def test_llm_error_produces_error_terminal(self):
        class _FailingAdapter:
            async def generate(self, prompt, context, **params):
                raise RuntimeError("LLM API down")

        engine = LLMPlanningEngine(_FailingAdapter())
        items = async_collect(
            engine.plan(
                _make_context(goal="Test"),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert len(items) == 1
        assert items[0].is_terminal
        assert items[0].finish_reason == "error"


# ── TestLLMPlanningEdgeCases ──────────────────────────────────────────


class TestLLMPlanningEdgeCases:
    """LLMPlanningEngine edge case tests."""

    def test_deadline_exceeded_before_llm_call(self):
        async def _run():
            items = []
            with pytest.raises(asyncio.TimeoutError):
                async for _ in _make_engine().plan(
                    _make_context(goal="Test"),
                    deadline=-1.0, pace_config=PaceConfig(),
                ):
                    pass
        asyncio.run(_run())

    def test_parse_failure_produces_error_terminal(self):
        backend = MockLLMBackend(responses=("{{{not valid json", "ok"))
        engine = LLMPlanningEngine(_MockAdapter(backend))
        items = async_collect(
            engine.plan(
                _make_context(goal="Test"),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert items[0].is_terminal
        assert items[0].finish_reason == "error"

    def test_engine_has_identity(self):
        assert LLMPlanningEngine.identity is not None
        assert LLMPlanningEngine.identity.role == "planning"
        assert "llm_backed" in LLMPlanningEngine.identity.capabilities

    def test_planning_keys_in_all_non_error_items(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=("a", "b")),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        planning_keys = {"planning.step_index", "planning.reasoning_depth",
                         "planning.parent_step_id", "planning.cumulative_tokens",
                         "agent.identity"}
        for item in items:
            if item.finish_reason != "error":
                missing = planning_keys - set(item.trace_context.keys())
                assert not missing, f"Item {item.index} missing keys: {missing}"

    def test_no_sub_tasks_produces_orchestration_items(self):
        items = async_collect(
            _make_engine().plan(
                _make_context(goal="Test", sub_tasks=()),
                deadline=30.0, pace_config=PaceConfig(),
            )
        )
        assert len(items) >= 2  # serial + orchestration + terminal
