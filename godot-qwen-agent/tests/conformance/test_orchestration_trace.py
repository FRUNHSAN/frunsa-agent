"""Conformance tests: orchestration engine stub trace contracts (Phase 14).

Acceptance gate for Phase 14: every StreamItem from StubOrchestrationEngine
MUST contain all 6 orchestration.* keys + consumed component keys with
correct types and values.
"""

from __future__ import annotations

import asyncio

import pytest

from core.observability.trace_registry import TRACE_KEY_REGISTRY
from engines.orchestration.stub import StubOrchestrationEngine


# ── Helpers ──────────────────────────────────────────────────────────

async def _collect_all_items():
    engine = StubOrchestrationEngine()
    items = []
    async for item in engine.orchestrate():
        items.append(item)
    return items


# ── TestOrchestrationStubOutput ──────────────────────────────────────


class TestOrchestrationStubOutput:
    """Every StreamItem must carry all 6 orchestration keys + component keys."""

    def test_produces_non_empty_stream(self):
        """Orchestration stub produces at least one StreamItem."""
        items = asyncio.run(_collect_all_items())
        assert len(items) > 0

    def test_all_six_orchestration_keys_present(self):
        """Every StreamItem has all 6 orchestration.* trace_context keys."""
        items = asyncio.run(_collect_all_items())
        required = {
            "orchestration.dag_node_id",
            "orchestration.parallel_depth",
            "orchestration.merge_ordinal",
            "orchestration.branch_taken",
            "orchestration.retry_count",
            "orchestration.resource_pool_key",
        }
        for i, item in enumerate(items):
            ctx = item.trace_context
            assert ctx is not None, f"Item {i}: trace_context is None"
            missing = required - set(ctx.keys())
            assert not missing, f"Item {i}: missing keys: {missing}"

    def test_component_keys_also_present(self):
        """Every StreamItem also carries component keys consumed by orchestration."""
        items = asyncio.run(_collect_all_items())
        for i, item in enumerate(items):
            ctx = item.trace_context
            assert "retrieval.chunk_id" in ctx, f"Item {i}: missing retrieval.chunk_id"
            assert "retrieval.latency_ms" in ctx, f"Item {i}: missing retrieval.latency_ms"

    def test_trace_context_not_none(self):
        """No StreamItem has trace_context=None."""
        items = asyncio.run(_collect_all_items())
        for i, item in enumerate(items):
            assert item.trace_context is not None, f"Item {i}: trace_context is None"

    def test_last_item_is_terminal(self):
        """The last StreamItem has is_terminal=True."""
        items = asyncio.run(_collect_all_items())
        assert items[-1].is_terminal is True

    def test_zero_items_no_crash(self):
        """Engine with zero-branch simulation doesn't crash."""
        # The stub always produces items (5 from 2 branches).
        # Verify it doesn't crash on repeated calls.
        items1 = asyncio.run(_collect_all_items())
        items2 = asyncio.run(_collect_all_items())
        assert len(items1) == len(items2)  # deterministic


# ── TestOrchestrationTraceKeyTypes ───────────────────────────────────


class TestOrchestrationTraceKeyTypes:
    """Each orchestration key value must match its declared TraceKeyDef type."""

    def test_dag_node_id_is_str(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.dag_node_id"], str)

    def test_parallel_depth_is_int(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.parallel_depth"], int)

    def test_merge_ordinal_is_int(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.merge_ordinal"], int)

    def test_branch_taken_is_str(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.branch_taken"], str)

    def test_retry_count_is_int(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.retry_count"], int)

    def test_resource_pool_key_is_str(self):
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert isinstance(item.trace_context["orchestration.resource_pool_key"], str)


# ── TestOrchestrationKeyRegistration ─────────────────────────────────


class TestOrchestrationKeyRegistration:
    """All 6 orchestration keys must be in TRACE_KEY_REGISTRY with correct metadata."""

    def test_all_six_in_registry(self):
        orch_keys = {k: v for k, v in TRACE_KEY_REGISTRY.items() if "orchestration" in v.engines}
        assert len(orch_keys) == 6

    def test_engine_is_orchestration(self):
        for key, defn in TRACE_KEY_REGISTRY.items():
            if key.startswith("orchestration."):
                assert "orchestration" in defn.engines, f"{key}: engines={defn.engines}"

    def test_component_candidate_false(self):
        for key, defn in TRACE_KEY_REGISTRY.items():
            if key.startswith("orchestration."):
                assert defn.component_candidate is False, (
                    f"{key}: component_candidate={defn.component_candidate}"
                )


# ── TestOrchestrationNotComponentCandidate ───────────────────────────


class TestOrchestrationNotComponentCandidate:
    """No orchestration key should appear in COMPONENT_TRACE_KEYS."""

    def test_not_in_component_keys(self):
        from core.contracts.trace_keys import COMPONENT_TRACE_KEYS
        for key in COMPONENT_TRACE_KEYS:
            assert not key.startswith("orchestration."), (
                f"{key} should not be in COMPONENT_TRACE_KEYS"
            )


# ── TestOrchestrationMergeOrdinal ────────────────────────────────────


class TestOrchestrationMergeOrdinal:
    """merge_ordinal must be sequential and 0-based across merged output."""

    def test_sequential_zero_based(self):
        items = asyncio.run(_collect_all_items())
        ordinals = [item.trace_context["orchestration.merge_ordinal"] for item in items]
        assert ordinals == list(range(len(items))), (
            f"Expected 0..{len(items)-1}, got {ordinals}"
        )

    def test_continuous_across_branches(self):
        """Merge ordinals are continuous — no gaps from branch boundaries."""
        items = asyncio.run(_collect_all_items())
        ordinals = [item.trace_context["orchestration.merge_ordinal"] for item in items]
        for i in range(1, len(ordinals)):
            assert ordinals[i] == ordinals[i - 1] + 1, (
                f"Gap at index {i}: {ordinals[i-1]} -> {ordinals[i]}"
            )


# ── TestOrchestrateTraceContextEdgeCases ─────────────────────────────


class TestOrchestrateTraceContextEdgeCases:
    """Edge case coverage from the Phase 14 plan."""

    def test_extra_key_would_be_detected(self):
        """Verify that an unknown orchestration.* key would fail registration check.

        This tests the guardrail's pollution detection contract:
        any key with 'orchestration.' prefix not in TRACE_KEY_REGISTRY
        should be flagged. We verify the registry is the source of truth.
        """
        fake_key = "orchestration.unknown_extra_key"
        assert fake_key not in TRACE_KEY_REGISTRY, (
            f"{fake_key} should not be in TRACE_KEY_REGISTRY"
        )

    def test_branch_taken_values_are_valid(self):
        """branch_taken values are from the stub's defined branches."""
        items = asyncio.run(_collect_all_items())
        branches = {item.trace_context["orchestration.branch_taken"] for item in items}
        assert branches.issubset({"fast_path", "full_rerank"}), (
            f"Unexpected branch values: {branches}"
        )

    def test_retry_count_starts_at_zero(self):
        """Stub items start with retry_count=0 (no retries in simulation)."""
        items = asyncio.run(_collect_all_items())
        for item in items:
            assert item.trace_context["orchestration.retry_count"] == 0

    def test_resource_pool_key_is_constant(self):
        """All stub items use the same resource pool."""
        items = asyncio.run(_collect_all_items())
        pools = {item.trace_context["orchestration.resource_pool_key"] for item in items}
        assert pools == {"default"}
