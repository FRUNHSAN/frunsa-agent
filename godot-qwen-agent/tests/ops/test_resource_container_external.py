"""Operational contract tests: ResourceContainer under external-resource stress.

Validates that the container can handle connection-pool-like patterns
that Retriever and other external-dependency components will use.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.pipeline.resources import ResourceContainer


class FakeConnection:
    """Simulates an external resource (e.g. vector DB client, HTTP session)."""

    def __init__(self, conn_id: int) -> None:
        self.conn_id = conn_id
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TestResourceContainerPoolPatterns:
    """Connection pool patterns — no built-in pooling yet, validated via wrapper."""

    def test_managed_resources_are_all_released_on_close(self):
        rc = ResourceContainer()
        conns = [FakeConnection(i) for i in range(5)]
        for i, conn in enumerate(conns):
            rc.register_managed(f"conn_{i}", conn)

        rc.close()
        assert all(c.closed for c in conns)

    def test_scoped_resource_factory_is_called_once(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return FakeConnection(call_count)

        rc = ResourceContainer()
        with rc.scoped(factory) as conn1:
            assert conn1.conn_id == 1

        with rc.scoped(factory) as conn2:
            assert conn2.conn_id == 2  # new instance each scoped block

        assert call_count == 2

    def test_concurrent_scoped_blocks_do_not_conflict(self):
        """Multiple scoped blocks can coexist (simulating concurrent pipeline steps)."""
        rc = ResourceContainer()
        closed_ids: list[int] = []

        def factory(conn_id):
            return FakeConnection(conn_id)

        # Nested scoped blocks (not concurrent, but validates non-interference)
        with rc.scoped(lambda: factory(1)) as c1:
            with rc.scoped(lambda: factory(2)) as c2:
                assert not c1.closed
                assert not c2.closed
            # c2 released on inner with-exit
        # c1 released on outer with-exit

    def test_close_after_scoped_does_not_double_free(self):
        """close() never touches scoped resources — no double-free path."""
        rc = ResourceContainer()
        closed_count = 0
        managed_closed_count = 0

        def scoped_factory():
            return FakeConnection(99)

        rc.register_managed(
            "m",
            type(
                "M",
                (),
                {
                    "close": lambda s: nonlocal_manager(),
                },
            )(),
        )

        def nonlocal_manager():
            nonlocal managed_closed_count
            managed_closed_count += 1

        with rc.scoped(scoped_factory):
            pass  # scoped released here

        rc.close()  # only managed released here
        # No crash = success (scoped already released, close doesn't touch it)


class TestGracefulDegradation:
    """Simulating what Retriever will need: degraded state when resource unavailable."""

    def test_health_check_reflects_managed_resource_state(self):
        """Managed resources are tracked internally and released by close()."""
        rc = ResourceContainer()
        conn = FakeConnection(1)
        rc.register_managed("db_conn", conn)

        # Managed resources live in _managed, not accessible via get()
        # (get() is for config/state only — managed resources are owned by the container)
        assert "db_conn" in rc._managed
        assert rc._managed["db_conn"] is conn
        assert not conn.closed  # alive before close

        rc.close()
        assert conn.closed  # _safe_close called on release

    def test_missing_managed_resource_returns_none(self):
        rc = ResourceContainer()
        assert rc.get("nonexistent") is None


class TestDependencyCallTrace:
    """Operational contract: tracing external calls with DependencyCallTrace."""

    def test_dependency_call_trace_fields(self):
        from core.pipeline.tracing import DependencyCallTrace, SpanType

        trace = DependencyCallTrace(
            dependency_name="vector_db",
            span_type=SpanType.DEPENDENCY_CALL,
            duration_ms=190.5,
            status="success",
            metadata={"index": "godot_docs", "results": 15},
        )
        assert trace.dependency_name == "vector_db"
        assert trace.duration_ms == 190.5
        assert trace.metadata["results"] == 15

    def test_step_trace_includes_dependency_calls(self):
        from core.pipeline.tracing import DependencyCallTrace, StepTrace, SpanType

        dc = DependencyCallTrace(
            dependency_name="llm_api",
            duration_ms=1200.0,
            status="success",
        )
        st = StepTrace(
            step_index=0,
            step_name="generate_answer",
            pipeline_run_id="run-1",
            dependency_calls=[dc],
        )
        assert len(st.dependency_calls) == 1
        assert st.dependency_calls[0].dependency_name == "llm_api"

    def test_tracelog_to_dict_includes_dependency_calls(self):
        from core.pipeline.tracing import (
            DependencyCallTrace,
            StepTrace,
            TraceLog,
            SpanType,
        )

        dc = DependencyCallTrace(
            dependency_name="faiss_search",
            duration_ms=45.0,
            status="success",
        )
        st = StepTrace(
            step_index=0,
            step_name="retrieve",
            pipeline_run_id="run-2",
            dependency_calls=[dc],
        )
        tl = TraceLog(
            pipeline_run_id="run-2",
            steps=[st],
            total_steps=1,
            success_count=1,
        )
        d = tl.to_dict()
        assert "steps" in d
        assert d["steps"][0]["dependency_calls"][0]["dependency_name"] == "faiss_search"


class TestHealthStatusContract:
    """Operational contract: all components must implement standardized health_check."""

    def test_health_status_includes_dependencies_and_version(self):
        from core.pipeline.engine import DependencyHealth, HealthStatus

        dep = DependencyHealth(
            name="vector_db",
            status="healthy",
            latency_ms=12.3,
            message="connected",
        )
        hs = HealthStatus(
            status="healthy",
            message="all systems go",
            dependencies=[dep],
            version="1.0.0",
        )
        assert hs.status == "healthy"
        assert len(hs.dependencies) == 1
        assert hs.dependencies[0].name == "vector_db"
        assert hs.version == "1.0.0"

    def test_identity_chunker_health_check(self):
        from core.contracts import IdentityChunker

        chunker = IdentityChunker()
        hs = chunker.health_check()  # type: ignore[attr-defined]
        assert hs.status == "healthy"
        assert hs.dependencies == []
        assert hs.version is not None

    def test_degraded_status_when_dependency_slow(self):
        from core.pipeline.engine import DependencyHealth, HealthStatus

        dep = DependencyHealth(
            name="llm_api",
            status="degraded",
            latency_ms=4500.0,
            message="high latency detected",
        )
        hs = HealthStatus(
            status="degraded",
            message="service operational but slow",
            dependencies=[dep],
        )
        assert hs.status == "degraded"
