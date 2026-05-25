"""Conformance tests: Orchestration chaos injection (Phase 16).

Verifies FailureInjectionConfig and multi-pool routing produce correct
retry_count and resource_pool_key values. All injection is deterministic:
same config → same output.
"""

from __future__ import annotations

import asyncio

import pytest

from engines.orchestration.config import FailureInjectionConfig, OrchestrationConfig
from engines.orchestration.stub import StubOrchestrationEngine


async def _collect(config: OrchestrationConfig | None = None):
    engine = StubOrchestrationEngine(config)
    items = []
    async for item in engine.orchestrate():
        items.append(item)
    return items


# ── TestRetryInjection ─────────────────────────────────────────────────


class TestRetryInjection:
    """Verify retry_count increments on injected failures."""

    def test_retry_count_increments_on_injected_failure(self):
        """c003 fails on attempt 1 → retry_count=1 on c003."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                fail_on_attempts=(("c003", 1),),
            ),
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            if ctx["retrieval.chunk_id"] == "c003":
                assert ctx["orchestration.retry_count"] == 1, (
                    f"c003 should have retry_count=1, got {ctx['orchestration.retry_count']}"
                )

    def test_non_failing_items_retry_count_stays_zero(self):
        """Only injected item retries — others stay at 0."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                fail_on_attempts=(("c003", 1),),
            ),
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            cid = ctx["retrieval.chunk_id"]
            if cid != "c003":
                assert ctx["orchestration.retry_count"] == 0, (
                    f"{cid}: expected retry_count=0, got {ctx['orchestration.retry_count']}"
                )

    def test_exhaust_retries_produces_error_terminal(self):
        """c005 fails all 3 attempts → error item with finish_reason=retry_exhausted."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                exhaust_retries=("c005",),
            ),
        )
        items = asyncio.run(_collect(config))

        c005_items = [i for i in items if i.trace_context["retrieval.chunk_id"] == "c005"]
        assert len(c005_items) == 1, f"Expected 1 c005 item, got {len(c005_items)}"
        c005 = c005_items[0]
        assert c005.finish_reason == "retry_exhausted", (
            f"Expected retry_exhausted, got {c005.finish_reason}"
        )
        assert c005.trace_context["orchestration.retry_count"] == 2, (
            f"Expected retry_count=2 (3 attempts), got {c005.trace_context['orchestration.retry_count']}"
        )

    def test_exhaust_retries_does_not_affect_other_items(self):
        """Only the exhaust_retries target is affected — other items normal."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                exhaust_retries=("c005",),
            ),
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            cid = ctx["retrieval.chunk_id"]
            if cid != "c005":
                assert "error" not in (item.finish_reason or ""), (
                    f"{cid}: unexpected error on non-targeted item"
                )
                assert ctx["orchestration.retry_count"] == 0, (
                    f"{cid}: non-targeted item should have retry_count=0"
                )

    def test_deterministic_injection_same_config_same_output(self):
        """Same FailureInjectionConfig → same retry_count values."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                fail_on_attempts=(("c003", 1),),
            ),
        )

        run1 = asyncio.run(_collect(config))
        run2 = asyncio.run(_collect(config))

        for i, (a, b) in enumerate(zip(run1, run2)):
            assert a.trace_context["orchestration.retry_count"] == b.trace_context["orchestration.retry_count"], (
                f"Item {i}: non-deterministic retry_count"
            )

    def test_fail_on_attempts_specific_attempt_only(self):
        """(c003, 2) fails attempt 2 only — attempt 1 succeeds, no retry."""
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                fail_on_attempts=(("c003", 2),),
            ),
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            if ctx["retrieval.chunk_id"] == "c003":
                # Attempt 1 succeeds (no failure), attempt 2 would fail but isn't reached
                assert ctx["orchestration.retry_count"] == 0, (
                    f"c003 should succeed on attempt 1, got retry_count={ctx['orchestration.retry_count']}"
                )


# ── TestMultiPoolRouting ───────────────────────────────────────────────


class TestMultiPoolRouting:
    """Verify resource_pool_key reflects per-branch pool assignments."""

    def test_resource_pool_key_cpu_on_fast_path(self):
        """fast_path → cpu pool."""
        config = OrchestrationConfig(
            resource_pools={"fast_path": "cpu", "full_rerank": "gpu"},
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            if ctx["orchestration.branch_taken"] == "fast_path":
                assert ctx["orchestration.resource_pool_key"] == "cpu", (
                    f"fast_path item should have pool=cpu, got {ctx['orchestration.resource_pool_key']}"
                )

    def test_resource_pool_key_gpu_on_full_rerank(self):
        """full_rerank → gpu pool."""
        config = OrchestrationConfig(
            resource_pools={"fast_path": "cpu", "full_rerank": "gpu"},
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            if ctx["orchestration.branch_taken"] == "full_rerank":
                assert ctx["orchestration.resource_pool_key"] == "gpu", (
                    f"full_rerank item should have pool=gpu, got {ctx['orchestration.resource_pool_key']}"
                )

    def test_default_pool_when_no_config(self):
        """No config → all items get 'default' pool."""
        items = asyncio.run(_collect())

        for item in items:
            assert item.trace_context["orchestration.resource_pool_key"] == "default", (
                f"Expected default pool, got {item.trace_context['orchestration.resource_pool_key']}"
            )

    def test_missing_branch_falls_back_to_default(self):
        """Branch not in resource_pools → 'default'."""
        config = OrchestrationConfig(
            resource_pools={"full_rerank": "gpu"},
        )
        items = asyncio.run(_collect(config))

        for item in items:
            ctx = item.trace_context
            if ctx["orchestration.branch_taken"] == "fast_path":
                assert ctx["orchestration.resource_pool_key"] == "default", (
                    f"fast_path should fall back to default, got {ctx['orchestration.resource_pool_key']}"
                )


# ── TestOrchestrationConfigBackwardCompat ───────────────────────────────


class TestOrchestrationConfigBackwardCompat:
    """No config → Phase 15 behavior unchanged."""

    def test_no_config_produces_five_items(self):
        """Same 5 items as Phase 14/15."""
        items = asyncio.run(_collect())
        assert len(items) == 5, f"Expected 5 items, got {len(items)}"

    def test_retry_count_zero_without_injection(self):
        """All items have retry_count=0 when no failure injection."""
        items = asyncio.run(_collect())
        for item in items:
            assert item.trace_context["orchestration.retry_count"] == 0

    def test_pool_key_default_without_config(self):
        """All items have pool='default' when no config."""
        items = asyncio.run(_collect())
        for item in items:
            assert item.trace_context["orchestration.resource_pool_key"] == "default"

    def test_none_config_also_works(self):
        """Explicit None config produces same behavior as no config."""
        items = asyncio.run(_collect(None))
        assert len(items) == 5
        for item in items:
            assert item.trace_context["orchestration.retry_count"] == 0
