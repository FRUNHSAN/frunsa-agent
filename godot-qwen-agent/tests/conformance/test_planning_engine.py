"""Conformance tests: Planning Engine + Agent Identity (Phase 15).

Verifies the enhanced Planning Engine stub emits correct trace_context keys
with proper types, including agent.identity and orchestration passthrough.
"""

from __future__ import annotations

import asyncio

import pytest

from core.observability.trace_registry import TRACE_KEY_REGISTRY
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext


def _make_context(goal: str = "Validate Phase 14 orchestration contract") -> PlanningContext:
    return PlanningContext(
        goal=goal,
        agent_identity=AgentIdentity(
            id="planner-v1",
            role="planning",
            version="1.0.0",
            capabilities=("task_decomposition", "parallel_planning"),
        ),
    )


async def _collect_items(goal: str = "Validate Phase 14 orchestration contract"):
    """Collect all StreamItems from the enhanced planning stub."""
    from engines.planning.stub import StubPlanningEngine

    engine = StubPlanningEngine()
    ctx = _make_context(goal)
    items = []
    async for item in engine.plan(ctx, deadline=999.0, pace_config=None):
        items.append(item)
    return items


# ── TestPlanningStubOutput ────────────────────────────────────────────


class TestPlanningStubOutput:
    """Verify the enhanced planning stub produces correct StreamItems."""

    def test_produces_non_empty_stream(self):
        """Stub produces at least one StreamItem."""
        items = asyncio.run(_collect_items())
        assert len(items) > 0, "Planning stub should produce items"

    def test_produces_eight_items(self):
        """5-step scenario produces 8 items: 2 serial + 5 orchestration + 1 terminal."""
        items = asyncio.run(_collect_items())
        assert len(items) == 8, f"Expected 8 items (2+5+1), got {len(items)}"

    def test_all_four_planning_keys_present(self):
        """Every StreamItem carries all 4 planning.* keys."""
        items = asyncio.run(_collect_items())
        required = {
            "planning.step_index",
            "planning.reasoning_depth",
            "planning.parent_step_id",
            "planning.cumulative_tokens",
        }
        for i, item in enumerate(items):
            ctx = item.trace_context
            assert ctx is not None, f"Item {i}: trace_context is None"
            missing = required - set(ctx.keys())
            assert not missing, f"Item {i}: missing planning keys: {missing}"

    def test_agent_identity_present(self):
        """Every StreamItem carries agent.identity."""
        items = asyncio.run(_collect_items())
        for i, item in enumerate(items):
            assert "agent.identity" in item.trace_context, (
                f"Item {i}: missing agent.identity"
            )

    def test_agent_identity_is_dict_with_required_fields(self):
        """agent.identity is a dict with id, role, version, capabilities."""
        items = asyncio.run(_collect_items())
        for i, item in enumerate(items):
            identity = item.trace_context["agent.identity"]
            assert isinstance(identity, dict), f"Item {i}: agent.identity is {type(identity)}"
            assert "id" in identity, f"Item {i}: agent.identity missing 'id'"
            assert "role" in identity, f"Item {i}: agent.identity missing 'role'"
            assert "version" in identity, f"Item {i}: agent.identity missing 'version'"
            assert "capabilities" in identity, f"Item {i}: agent.identity missing 'capabilities'"
            assert isinstance(identity["capabilities"], list), (
                f"Item {i}: capabilities should be list, got {type(identity['capabilities'])}"
            )

    def test_trace_context_not_none(self):
        """No StreamItem has None trace_context."""
        items = asyncio.run(_collect_items())
        for i, item in enumerate(items):
            assert item.trace_context is not None, (
                f"Item {i}: trace_context should not be None"
            )

    def test_last_item_is_terminal(self):
        """Final StreamItem has is_terminal=True with finish_reason='stop'."""
        items = asyncio.run(_collect_items())
        last = items[-1]
        assert last.is_terminal is True, f"Last item is_terminal={last.is_terminal}"
        assert last.finish_reason == "stop", f"Last item finish_reason={last.finish_reason}"

    def test_non_terminal_items_have_no_finish_reason(self):
        """Non-terminal items have finish_reason=None."""
        items = asyncio.run(_collect_items())
        for i, item in enumerate(items[:-1]):
            assert item.finish_reason is None, (
                f"Item {i}: non-terminal should have finish_reason=None, got {item.finish_reason}"
            )

    def test_orchestration_keys_passthrough(self):
        """Items 2-6 carry all 6 orchestration.* keys (passthrough from orchestration engine)."""
        items = asyncio.run(_collect_items())
        orch_required = {
            "orchestration.dag_node_id",
            "orchestration.parallel_depth",
            "orchestration.merge_ordinal",
            "orchestration.branch_taken",
            "orchestration.retry_count",
            "orchestration.resource_pool_key",
        }
        orch_items = items[2:7]  # items at indices 2-6 are orchestration passthrough
        assert len(orch_items) == 5
        for i, item in enumerate(orch_items):
            ctx = item.trace_context
            missing = orch_required - set(ctx.keys())
            assert not missing, f"Orch item {i}: missing orchestration keys: {missing}"

    def test_component_keys_passthrough(self):
        """Orchestration items also carry retrieval.chunk_id + retrieval.latency_ms."""
        items = asyncio.run(_collect_items())
        orch_items = items[2:7]
        for i, item in enumerate(orch_items):
            ctx = item.trace_context
            assert "retrieval.chunk_id" in ctx, f"Orch item {i}: missing retrieval.chunk_id"
            assert "retrieval.latency_ms" in ctx, f"Orch item {i}: missing retrieval.latency_ms"


# ── TestPlanningTraceKeyTypes ─────────────────────────────────────────


class TestPlanningTraceKeyTypes:
    """Verify planning/agent trace key values match declared types."""

    def test_step_index_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items:
            assert isinstance(item.trace_context["planning.step_index"], int)

    def test_reasoning_depth_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items:
            assert isinstance(item.trace_context["planning.reasoning_depth"], int)

    def test_parent_step_id_is_str_or_none(self):
        items = asyncio.run(_collect_items())
        for item in items:
            val = item.trace_context["planning.parent_step_id"]
            assert val is None or isinstance(val, str)

    def test_cumulative_tokens_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items:
            assert isinstance(item.trace_context["planning.cumulative_tokens"], int)

    def test_merge_ordinal_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items[2:7]:
            assert isinstance(item.trace_context["orchestration.merge_ordinal"], int)

    def test_parallel_depth_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items[2:7]:
            assert isinstance(item.trace_context["orchestration.parallel_depth"], int)

    def test_retry_count_is_int(self):
        items = asyncio.run(_collect_items())
        for item in items[2:7]:
            assert isinstance(item.trace_context["orchestration.retry_count"], int)


# ── TestPlanningKeyRegistration ───────────────────────────────────────


class TestPlanningKeyRegistration:
    """Verify all planning keys are in TRACE_KEY_REGISTRY."""

    def test_all_four_planning_keys_in_registry(self):
        planning_keys = {k for k, v in TRACE_KEY_REGISTRY.items() if v.engine == "planning"}
        expected = {
            "planning.step_index",
            "planning.reasoning_depth",
            "planning.parent_step_id",
            "planning.cumulative_tokens",
            "agent.identity",
        }
        assert planning_keys == expected, (
            f"Planning keys mismatch: got {planning_keys}, expected {expected}"
        )

    def test_agent_identity_in_registry(self):
        assert "agent.identity" in TRACE_KEY_REGISTRY
        key_def = TRACE_KEY_REGISTRY["agent.identity"]
        assert key_def.engine == "planning"
        assert key_def.type == dict
        assert key_def.component_candidate is False


# ── TestPlanningMergeOrdinal ──────────────────────────────────────────


class TestPlanningMergeOrdinal:
    """Verify merge_ordinal semantics across merged orchestration output."""

    def test_sequential_zero_based(self):
        """merge_ordinal starts at 0 and increments by 1."""
        items = asyncio.run(_collect_items())
        ordinals = [
            item.trace_context["orchestration.merge_ordinal"]
            for item in items[2:7]
        ]
        assert ordinals == [0, 1, 2, 3, 4], f"Expected [0,1,2,3,4], got {ordinals}"

    def test_continuous_across_branches(self):
        """merge_ordinal is continuous with no gaps across both branches."""
        items = asyncio.run(_collect_items())
        ordinals = [
            item.trace_context["orchestration.merge_ordinal"]
            for item in items[2:7]
        ]
        for i, o in enumerate(ordinals):
            assert o == i, f"merge_ordinal[{i}] = {o}, expected {i}"


# ── TestPlanningParallelBranches ──────────────────────────────────────


class TestPlanningParallelBranches:
    """Verify both parallel branches produce items."""

    def test_both_branches_produce_items(self):
        """Both fast_path and full_rerank branches contribute items."""
        items = asyncio.run(_collect_items())
        branches = {
            item.trace_context["orchestration.branch_taken"]
            for item in items[2:7]
        }
        assert "fast_path" in branches, f"fast_path missing from branches: {branches}"
        assert "full_rerank" in branches, f"full_rerank missing from branches: {branches}"

    def test_total_orchestration_item_count_is_five(self):
        """3 fast_path + 2 full_rerank = 5 orchestration items."""
        items = asyncio.run(_collect_items())
        orch_items = items[2:7]
        assert len(orch_items) == 5

    def test_fast_path_has_three_items(self):
        """fast_path branch produces exactly 3 items."""
        items = asyncio.run(_collect_items())
        fast = [
            item for item in items[2:7]
            if item.trace_context["orchestration.branch_taken"] == "fast_path"
        ]
        assert len(fast) == 3, f"Expected 3 fast_path items, got {len(fast)}"

    def test_full_rerank_has_two_items(self):
        """full_rerank branch produces exactly 2 items."""
        items = asyncio.run(_collect_items())
        rerank = [
            item for item in items[2:7]
            if item.trace_context["orchestration.branch_taken"] == "full_rerank"
        ]
        assert len(rerank) == 2, f"Expected 2 full_rerank items, got {len(rerank)}"


# ── TestAgentIdentityRoundTrip ────────────────────────────────────────


class TestAgentIdentityRoundTrip:
    """Verify AgentIdentity serialization round-trip."""

    def test_to_trace_value_and_back(self):
        ai = AgentIdentity(
            id="planner-v1",
            role="planning",
            version="1.0.0",
            capabilities=("task_decomposition", "parallel_planning"),
        )
        data = ai.to_trace_value()
        ai2 = AgentIdentity.from_trace_value(data)
        assert ai == ai2
        assert ai2.capabilities == ("task_decomposition", "parallel_planning")

    def test_minimal_identity(self):
        """AgentIdentity works with default capabilities."""
        ai = AgentIdentity(id="test", role="test", version="0.1.0")
        assert ai.capabilities == ()
        data = ai.to_trace_value()
        assert data["capabilities"] == []

    def test_round_trip_preserves_capabilities(self):
        """Round-trip preserves capabilities as tuple."""
        ai = AgentIdentity(
            id="test",
            role="test",
            version="1.0.0",
            capabilities=("a", "b", "c"),
        )
        data = ai.to_trace_value()
        assert isinstance(data["capabilities"], list)
        ai2 = AgentIdentity.from_trace_value(data)
        assert isinstance(ai2.capabilities, tuple)
        assert ai2.capabilities == ("a", "b", "c")


# ── TestPlanningSchemaNoMigration ─────────────────────────────────────


class TestPlanningSchemaNoMigration:
    """Phase 15 requires no DDL migration."""

    def test_schema_version_stays_at_2(self):
        from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 2
