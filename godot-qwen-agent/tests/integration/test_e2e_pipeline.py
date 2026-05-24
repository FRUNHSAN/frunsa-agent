"""End-to-end pipeline integration tests: auto_discover → factory → engine → TraceLog.

Verification scenarios: 1, 2, 8, 11, 14, 15
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.adapters import create_step_factory
from core.contracts import ContentBlock, IdentityChunker
from core.pipeline import (
    LocalJSONWriter,
    PipelineConfig,
    PipelineRunner,
    SnapshotPolicy,
    StepConfig,
    StepOutput,
    TraceLog,
    serialize_tracelog,
    snapshot,
)
from core.pipeline.resources import ResourceContainer

from tests.fixtures import (
    make_content_block,
    make_identity_step_config,
    make_pipeline_config,
)


class TestFullPipelineIntegration:
    """Scenario 1+2: IdentityChunker through the full pipeline."""

    def test_identity_chunker_end_to_end(self):
        config = make_pipeline_config()
        runner = PipelineRunner(
            config,
            step_factories={"chunk_docs": create_step_factory},
            initial_keys={"document"},
        )
        state, trace = runner.run(
            {"document": make_content_block("hello pipeline")}
        )

        assert len(state["chunks"]) == 1
        assert state["chunks"][0].text == "hello pipeline"
        assert state["chunks"][0].source_strategy == "chunking.identity"
        assert state["chunks"][0].span == (0, 14)

        assert trace.success_count == 1
        assert trace.total_steps == 1
        assert trace.steps[0].pipeline_run_id is not None
        assert trace.steps[0].contract_validation is not None
        assert trace.steps[0].contract_validation.passed

    def test_multi_step_pipeline(self):
        """Two IdentityChunker steps chained."""
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="step1",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="chunks1",
                ),
                StepConfig(
                    name="step2",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="chunks2",
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={
                "step1": create_step_factory,
                "step2": create_step_factory,
            },
            initial_keys={"document"},
        )
        state, trace = runner.run(
            {"document": make_content_block("multi-step test")}
        )

        assert len(state["chunks1"]) == 1
        assert len(state["chunks2"]) == 1
        assert trace.success_count == 2
        assert trace.total_steps == 2


class TestTraceLog:
    """Scenario 14+15: TraceLog completeness and SnapshotPolicy."""

    def test_tracelog_json_serialization(self):
        tl = TraceLog(pipeline_run_id="test-id", pipeline_version=1)
        out = serialize_tracelog(tl, "json")
        data = json.loads(out)
        assert data["pipeline_run_id"] == "test-id"
        assert data["total_steps"] == 0

    def test_snapshot_summary_does_not_leak_full_data(self):
        from core.contracts import Chunk

        chunks = [Chunk(text="x" * 5000, source_strategy="t", span=(0, 5000))]
        s = snapshot(chunks, SnapshotPolicy.SUMMARY)
        assert s["type"] == "list"
        assert s["count"] == 1
        assert "hash" in s
        # SUMMARY should NOT include the full 5000-char text
        preview = s.get("preview", "")
        assert len(str(preview)) < 1000

    def test_snapshot_none_returns_none(self):
        assert snapshot("anything", SnapshotPolicy.NONE) is None

    def test_trace_writer_local_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traces.json"
            writer = LocalJSONWriter(str(path))
            tl = TraceLog(pipeline_run_id="test", pipeline_version=1)
            writer.write([tl])
            assert path.exists()


class TestEmptyPipeline:
    """Scenario 8: Empty pipeline returns initial state."""

    def test_empty_pipeline(self):
        config = PipelineConfig(steps=[])
        runner = PipelineRunner(config, step_factories={})
        state, trace = runner.run({"initial": "value"})

        assert state == {"initial": "value"}
        assert trace.total_steps == 0
        assert trace.success_count == 0

    def test_empty_pipeline_with_trace_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty_traces.json"
            writer = LocalJSONWriter(str(path))
            config = PipelineConfig(steps=[])
            runner = PipelineRunner(
                config, step_factories={}, trace_writer=writer
            )
            _, trace = runner.run()
            # Empty pipeline — writer not called (no steps, no traces)
            assert trace.total_steps == 0


class TestResourceContainerLifecycle:
    """Scenario 16: ResourceContainer scoped and managed lifecycle."""

    def test_scoped_resource_released_on_exit(self):
        closed: list[int] = []
        rc = ResourceContainer()

        def factory():
            return type("R", (), {"close": lambda s: closed.append(1)})()

        with rc.scoped(factory):
            pass
        assert len(closed) == 1

    def test_managed_resource_released_on_close(self):
        closed: list[int] = []
        rc = ResourceContainer()
        rc.register_managed("r", type("R", (), {"close": lambda s: closed.append(1)})())
        rc.close()
        assert len(closed) == 1

    def test_scoped_and_managed_never_overlap(self):
        """scoped resource is NOT touched by close()."""
        scoped_closed: list[int] = []
        managed_closed: list[int] = []
        rc = ResourceContainer()

        def factory():
            return type("S", (), {"close": lambda s: scoped_closed.append(1)})()

        rc.register_managed(
            "m", type("M", (), {"close": lambda s: managed_closed.append(1)})()
        )

        with rc.scoped(factory):
            pass

        assert len(scoped_closed) == 1  # released on with-exit
        assert len(managed_closed) == 0  # not yet released

        rc.close()
        assert len(scoped_closed) == 1  # still 1 — close() doesn't touch scoped
        assert len(managed_closed) == 1  # released by close()

    def test_config_priority_over_state(self):
        """Scenario 18: config takes priority over state for same key."""
        rc = ResourceContainer()
        rc.set_config("key", "config_value")
        rc.set_state("key", "state_value")
        assert rc.get("key") == "config_value"


class TestOnFailureDefault:
    """Scenario 11: on_failure=default fills default_value."""

    def test_default_value_on_failure(self):
        from tests.fixtures import FailingStep

        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="f",
                    component_type="chunker",
                    strategy="bad",
                    depends_on=["document"],
                    provides="chunks",
                    on_failure="default",
                    default_value=["fallback"],
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={"f": lambda s: FailingStep()},
            initial_keys={"document"},
        )
        state, trace = runner.run({"document": "test"})
        assert state["chunks"] == ["fallback"]
        assert trace.steps[0].status == "failed"
