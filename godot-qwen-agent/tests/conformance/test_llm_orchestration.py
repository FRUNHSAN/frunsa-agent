"""Conformance tests for LLMOrchestrationEngine + MockOrchBackend.

Phase 18 Task 2: Validates Protocol conformance, trace key completeness,
parser correctness, and deterministic mock behavior.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.orchestration.identity import OrchestratorIdentity
from engines.orchestration.interface import (
    BranchSpec,
    OrchestrationContext,
    OrchestrationEngine,
)
from engines.orchestration.llm import (
    DEFAULT_MERGE_RESPONSE,
    DEFAULT_RETRY_RESPONSE,
    DEFAULT_ROUTE_RESPONSE,
    LLMOrchestrationEngine,
    MockOrchBackend,
    _parse_merge_decision,
    _parse_retry_decision,
    _parse_route_decision,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _default_context() -> OrchestrationContext:
    return OrchestrationContext(
        branches=(
            BranchSpec(name="fast_path", pool="cpu", items=2),
            BranchSpec(name="full_rerank", pool="gpu", items=1),
        ),
        agent_identity=OrchestratorIdentity(
            id="orchestrator-v1",
            role="orchestration",
            version="1.0.0",
            capabilities=("parallel_dispatch",),
        ),
    )


def _default_adapter() -> GenerationAdapter:
    backend = MockOrchBackend(responses=(
        DEFAULT_ROUTE_RESPONSE,
        DEFAULT_MERGE_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
    ))
    return GenerationAdapter(backend, dependency_name="mock_orch")


async def _collect(engine: LLMOrchestrationEngine, context=None, deadline=5.0):
    items = []
    ctx = context or _default_context()
    async for item in engine.orchestrate(ctx, deadline, PaceConfig()):
        items.append(item)
    return items


# ── TestMockOrchBackend ────────────────────────────────────────────────


class TestMockOrchBackend:
    """MockOrchBackend implements GenerationBackend Protocol deterministically."""

    def test_generate_returns_generation_result(self):
        backend = MockOrchBackend(responses=('{"ok": true}',))
        result = backend.generate("prompt", [])
        assert isinstance(result, GenerationResult)
        assert result.text == '{"ok": true}'
        assert result.model == "mock/orchestration"

    def test_count_tokens_estimates_by_word_split(self):
        backend = MockOrchBackend(responses=())
        tokens = backend.count_tokens("hello world test")
        assert tokens > 0

    def test_round_robin_cycles_responses(self):
        backend = MockOrchBackend(responses=("a", "b", "c"))
        assert backend.generate("p1", []).text == "a"
        assert backend.generate("p2", []).text == "b"
        assert backend.generate("p3", []).text == "c"
        assert backend.generate("p4", []).text == "a"

    def test_is_frozen_dataclass(self):
        backend = MockOrchBackend(responses=("x",))
        with pytest.raises(FrozenInstanceError):
            backend.responses = ("y",)

    def test_default_responses_follow_plan(self):
        backend = MockOrchBackend(responses=(
            DEFAULT_ROUTE_RESPONSE, DEFAULT_MERGE_RESPONSE, DEFAULT_RETRY_RESPONSE,
        ))
        r1 = backend.generate("p1", [])
        assert "branches" in r1.text and "parallel_depth" in r1.text
        r2 = backend.generate("p2", [])
        assert "strategy" in r2.text
        r3 = backend.generate("p3", [])
        assert "retry" in r3.text and "reason" in r3.text


# ── TestParsers ────────────────────────────────────────────────────────


class TestParsers:
    """Route, merge, and retry parsers handle valid and edge-case inputs."""

    def test_parse_route_valid(self):
        data = _parse_route_decision(DEFAULT_ROUTE_RESPONSE)
        assert "branches" in data
        assert "parallel_depth" in data

    def test_parse_merge_valid(self):
        data = _parse_merge_decision(DEFAULT_MERGE_RESPONSE)
        assert "strategy" in data

    def test_parse_retry_valid(self):
        data = _parse_retry_decision(DEFAULT_RETRY_RESPONSE)
        assert data["retry"] is True
        assert "reason" in data

    def test_parse_route_markdown_fenced(self):
        text = '```json\n{"branches": [], "parallel_depth": 1}\n```'
        data = _parse_route_decision(text)
        assert data["parallel_depth"] == 1

    def test_parse_merge_markdown_fenced(self):
        text = '```\n{"strategy": "interleave"}\n```'
        data = _parse_merge_decision(text)
        assert data["strategy"] == "interleave"

    def test_parse_route_missing_branches_raises(self):
        with pytest.raises(ValueError):
            _parse_route_decision('{"parallel_depth": 1}')

    def test_parse_route_malformed_json_raises(self):
        with pytest.raises(ValueError):
            _parse_route_decision("not json")

    def test_parse_route_empty_string_raises(self):
        with pytest.raises(ValueError):
            _parse_route_decision("")

    def test_parse_retry_extra_fields_accepted(self):
        data = _parse_retry_decision(
            '{"retry": false, "reason": "done", "extra": 123}'
        )
        assert data["retry"] is False


# ── TestLLMOrchestrationConformance ────────────────────────────────────


class TestLLMOrchestrationConformance:
    """LLMOrchestrationEngine conforms to OrchestrationEngine Protocol."""

    def test_implements_orchestration_engine_protocol(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        assert hasattr(engine, "orchestrate")
        assert callable(engine.orchestrate)

    def test_yields_stream_items(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        assert len(items) > 0
        for item in items:
            assert isinstance(item, StreamItem)

    def test_terminal_item_present(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        assert items[-1].is_terminal

    def test_all_six_orchestration_keys_present(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        required = {
            "orchestration.dag_node_id",
            "orchestration.parallel_depth",
            "orchestration.merge_ordinal",
            "orchestration.branch_taken",
            "orchestration.retry_count",
            "orchestration.resource_pool_key",
        }
        for item in items:
            ctx = item.trace_context or {}
            missing = required - set(ctx.keys())
            assert not missing, f"Missing keys: {missing}"

    def test_agent_identity_present(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert "agent.identity" in (item.trace_context or {})
            assert item.trace_context["agent.identity"]["role"] == "orchestration"

    def test_error_terminal_on_bad_route_response(self):
        backend = MockOrchBackend(responses=("not json",))
        adapter = GenerationAdapter(backend, dependency_name="mock_orch")
        engine = LLMOrchestrationEngine(adapter)
        items = asyncio.run(_collect(engine))
        assert items[0].is_terminal
        assert items[0].finish_reason == "error"

    def test_deadline_enforcement_before_route(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(_collect(engine, deadline=0.0))

    def test_metadata_passthrough_accepted(self):
        ctx = OrchestrationContext(
            branches=(BranchSpec(name="test", pool="cpu", items=1),),
            agent_identity=OrchestratorIdentity(
                id="orch-v1", role="orchestration", version="1.0.0",
            ),
            metadata={"debug": True, "source": "test"},
        )
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine, context=ctx))
        assert len(items) > 0


# ── TestEdgeCases ──────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case handling for LLMOrchestrationEngine."""

    def test_empty_branches_produces_terminal(self):
        ctx = OrchestrationContext(
            branches=(),
            agent_identity=OrchestratorIdentity(
                id="orch-v1", role="orchestration", version="1.0.0",
            ),
        )
        backend = MockOrchBackend(responses=(
            '{"branches": [], "parallel_depth": 0}',
            '{"strategy": "sequential"}',
        ))
        adapter = GenerationAdapter(backend, dependency_name="mock_orch")
        engine = LLMOrchestrationEngine(adapter)
        items = asyncio.run(_collect(engine, context=ctx))
        assert len(items) == 1
        assert items[0].is_terminal

    def test_single_branch_produces_items(self):
        ctx = OrchestrationContext(
            branches=(BranchSpec(name="solo", pool="cpu", items=2),),
            agent_identity=OrchestratorIdentity(
                id="orch-v1", role="orchestration", version="1.0.0",
            ),
        )
        backend = MockOrchBackend(responses=(
            '{"branches": [{"name": "solo", "pool": "cpu", "items": 2}], "parallel_depth": 1}',
            '{"strategy": "sequential"}',
            DEFAULT_RETRY_RESPONSE,
            DEFAULT_RETRY_RESPONSE,
        ))
        adapter = GenerationAdapter(backend, dependency_name="mock_orch")
        engine = LLMOrchestrationEngine(adapter)
        items = asyncio.run(_collect(engine, context=ctx))
        assert len(items) == 2  # 2 items, last one is terminal

    def test_model_field_is_orchestration_llm(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            assert item.model == "orchestration/llm"

    def test_component_pass_through_keys_present(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        items = asyncio.run(_collect(engine))
        for item in items:
            if item.trace_context and item.finish_reason != "error":
                assert "retrieval.chunk_id" in item.trace_context
                assert "retrieval.latency_ms" in item.trace_context

    def test_identity_has_llm_backed_capability(self):
        engine = LLMOrchestrationEngine(_default_adapter())
        assert "llm_backed" in engine.identity.capabilities
