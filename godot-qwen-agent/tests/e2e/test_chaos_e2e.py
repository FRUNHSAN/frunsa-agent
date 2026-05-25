"""E2E tests: chaos injection + multi-agent → SQLiteTraceSink (Phase 16).

Full-chain verification: orchestration with failure injection and multi-pool
routing, plus planning + critic agent coexistence, all written to sink and
queried back with correct trace key values.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
from core.observability.sqlite_sink import SQLiteTraceSink
from core.pipeline.tracing import StreamingTraceRecord
from engines.critic.identity import CriticAgent
from engines.orchestration.config import FailureInjectionConfig, OrchestrationConfig
from engines.orchestration.stub import StubOrchestrationEngine


async def _collect_orch_records(
    run_id: str = "chaos-e2e-1",
    config: OrchestrationConfig | None = None,
) -> list[StreamingTraceRecord]:
    engine = StubOrchestrationEngine(config)
    records = []
    async for item in engine.orchestrate():
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="orchestration",
            dependency_name="stub",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="orchestration",
        ))
    return records


async def _collect_critic_records(run_id: str = "chaos-e2e-critic") -> list[StreamingTraceRecord]:
    from engines.critic.stub import StubCriticEngine

    engine = StubCriticEngine()
    records = []
    async for item in engine.evaluate():
        records.append(StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="critic",
            dependency_name="stub",
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=item.trace_context,
            ts_iso="2026-05-25T00:00:00Z",
            engine="critic",
        ))
    return records


# ── TestRetryCountE2E ──────────────────────────────────────────────────


class TestRetryCountE2E:
    """Full chain: retry injection → StreamingTraceRecord → Sink → query."""

    def test_retry_count_survives_full_chain_to_sink(self):
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                fail_on_attempts=(("c003", 1),),
            ),
        )
        records = asyncio.run(_collect_orch_records(config=config))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == 5

                rows = sink.query_by_engine("orchestration")
                assert len(rows) == 5

                for row in rows:
                    ctx = json.loads(row["trace_context_json"])
                    cid = ctx["retrieval.chunk_id"]
                    retry = ctx["orchestration.retry_count"]
                    if cid == "c003":
                        assert retry == 1, f"c003 should have retry_count=1 in sink, got {retry}"
                    else:
                        assert retry == 0, f"{cid} should have retry_count=0 in sink, got {retry}"
            finally:
                sink.close()

    def test_exhaust_retries_survives_to_sink(self):
        config = OrchestrationConfig(
            failure_injection=FailureInjectionConfig(
                exhaust_retries=("c005",),
            ),
        )
        records = asyncio.run(_collect_orch_records(config=config))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == 5

                rows = sink.query_by_engine("orchestration")
                c005_rows = [
                    r for r in rows
                    if json.loads(r["trace_context_json"])["retrieval.chunk_id"] == "c005"
                ]
                assert len(c005_rows) == 1
                ctx = json.loads(c005_rows[0]["trace_context_json"])
                assert ctx["orchestration.retry_count"] == 2
            finally:
                sink.close()


# ── TestMultiPoolE2E ───────────────────────────────────────────────────


class TestMultiPoolE2E:
    """Full chain: multi-pool routing → Sink → pool keys preserved."""

    def test_pool_keys_survive_full_chain(self):
        config = OrchestrationConfig(
            resource_pools={"fast_path": "cpu", "full_rerank": "gpu"},
        )
        records = asyncio.run(_collect_orch_records(config=config))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(records)
                assert result.accepted_count == 5

                rows = sink.query_by_engine("orchestration")
                for row in rows:
                    ctx = json.loads(row["trace_context_json"])
                    branch = ctx["orchestration.branch_taken"]
                    pool = ctx["orchestration.resource_pool_key"]
                    if branch == "fast_path":
                        assert pool == "cpu", f"fast_path should be cpu, got {pool}"
                    else:
                        assert pool == "gpu", f"full_rerank should be gpu, got {pool}"
            finally:
                sink.close()


# ── TestMultiAgentE2E ──────────────────────────────────────────────────


class TestMultiAgentE2E:
    """Two agent identities coexist in same sink without collision."""

    def test_planning_and_critic_identities_both_in_sink(self):
        orch_records = asyncio.run(_collect_orch_records(run_id="multi-agent-orch"))
        critic_records = asyncio.run(_collect_critic_records(run_id="multi-agent-critic"))

        all_records = orch_records + critic_records

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(all_records)
                assert result.accepted_count == 8  # 5 orchestration + 3 critic

                # Orchestration records do NOT have agent.identity (only component + orch keys)
                orch_rows = sink.query_by_engine("orchestration")
                assert len(orch_rows) == 5

                # Critic records all have agent.identity with role=critic
                critic_rows = sink.query_by_engine("critic")
                assert len(critic_rows) == 3
                for row in critic_rows:
                    ctx = json.loads(row["trace_context_json"])
                    assert "agent.identity" in ctx
                    assert ctx["agent.identity"]["role"] == "critic"
            finally:
                sink.close()

    def test_no_key_collision_between_engines(self):
        """agent.identity from different engines don't collide in sink."""
        orch_records = asyncio.run(_collect_orch_records(run_id="collision-orch"))
        critic_records = asyncio.run(_collect_critic_records(run_id="collision-critic"))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                result = sink.write_streaming(orch_records + critic_records)
                assert result.accepted_count == 8

                # All 8 records accepted — no collision
                keys = sink.query_keys()
                agent_key = [k for k in keys if k["key_name"] == "agent.identity"]
                assert len(agent_key) == 1  # one key definition, not duplicated
            finally:
                sink.close()

    def test_engine_partitioning_isolation(self):
        """Querying by engine correctly isolates agent identities."""
        critic_records = asyncio.run(_collect_critic_records(run_id="iso-critic"))
        orch_records = asyncio.run(_collect_orch_records(run_id="iso-orch"))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            sink = SQLiteTraceSink(path)
            try:
                sink.write_streaming(critic_records + orch_records)

                critic_rows = sink.query_by_engine("critic")
                for row in critic_rows:
                    ctx = json.loads(row["trace_context_json"])
                    if "agent.identity" in ctx:
                        assert ctx["agent.identity"]["role"] == "critic"

                orch_rows = sink.query_by_engine("orchestration")
                for row in orch_rows:
                    ctx = json.loads(row["trace_context_json"])
                    # Phase 18: orchestration now emits agent.identity
                    # (registered to ["planning", "critic", "orchestration"])
                    assert ctx["agent.identity"]["role"] == "orchestration"
            finally:
                sink.close()


# ── TestSchemaNoMigration ──────────────────────────────────────────────


class TestSchemaNoMigration:
    """Phase 16 does not require schema migration."""

    def test_schema_version_stays_at_2(self):
        assert CURRENT_SCHEMA_VERSION == 2, (
            f"Schema should stay at v2, got v{CURRENT_SCHEMA_VERSION}"
        )
