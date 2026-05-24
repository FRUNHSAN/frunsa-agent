"""Phase 8.1 TDD: Async-native engine contract tests.

These tests define the BEHAVIOR of the async-native engine BEFORE implementation.
They will FAIL until Phase 8.1 is complete — that's by design.

Key contracts:
  C1: Single event loop — all steps share one loop, no per-step asyncio.run()
  C2: Concurrent execution — independent DAG branches run concurrently
  C3: Step.run() is async — steps directly await, no asyncio.run() wrapper
  C4: ResourceContainer lifecycle — lives for the entire pipeline execution
  C5: TraceLog concurrency — concurrent steps get distinct trace entries
  C6: Health check — works inside the shared event loop, no new loop creation
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest

from core.contracts import Chunk, ContentBlock, GenerationResult, IdentityChunker
from core.contracts.retrieval import RetrievalResult
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    StepConfig,
    StepOutput,
)
from core.pipeline.engine import (
    DependencyHealth,
    HealthStatus,
)
from core.pipeline.resources import ResourceContainer


# ── Test step that records its event loop ID ────────────────────────


class LoopRecordingStep:
    """A step that records which event loop it ran on. Used to verify C1."""

    def __init__(self, delay: float = 0.0, label: str = "") -> None:
        self.delay = delay
        self.label = label
        self._recorded_loop_id: int | None = None

    @property
    def recorded_loop_id(self) -> int | None:
        return self._recorded_loop_id

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        try:
            loop = asyncio.get_running_loop()
            self._recorded_loop_id = id(loop)
        except RuntimeError:
            self._recorded_loop_id = -1  # No loop running — FAIL

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        return StepOutput(
            result={"loop_id": self._recorded_loop_id, "label": self.label},
            trace_log={"loop_id": self._recorded_loop_id},
        )

    def health_check(self) -> HealthStatus:
        return HealthStatus(status="healthy", message="ok")


class ConcurrentTimerStep:
    """Records wall-clock start/end times. Used to verify C2 (concurrent execution)."""

    def __init__(self, delay: float = 0.05, label: str = "") -> None:
        self.delay = delay
        self.label = label
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        self.start_time = time.perf_counter()
        await asyncio.sleep(self.delay)
        self.end_time = time.perf_counter()
        return StepOutput(
            result={"label": self.label, "duration": self.end_time - self.start_time},
            trace_log={},
        )

    def health_check(self) -> HealthStatus:
        return HealthStatus(status="healthy", message="ok")


class ResourceAwareStep:
    """Uses ResourceContainer and verifies it stays alive across calls."""

    def __init__(self, resource_key: str) -> None:
        self.resource_key = resource_key

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        # Read accumulator, increment, write back
        val = resources.get(self.resource_key) or 0
        val += 1
        resources.set_state(self.resource_key, val)
        return StepOutput(
            result={"value": val},
            trace_log={},
        )

    def health_check(self) -> HealthStatus:
        return HealthStatus(status="healthy", message="ok")


class HealthCheckStep:
    """Step whose health_check probes the running event loop."""

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        return StepOutput(result="ok", trace_log={})

    def health_check(self) -> HealthStatus:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            return HealthStatus(
                status="healthy",
                message=f"loop_id={id(loop)}",
            )
        except RuntimeError:
            return HealthStatus(status="degraded", message="no running loop")


# ═════════════════════════════════════════════════════════════════════
# C1: Single event loop
# ═════════════════════════════════════════════════════════════════════


class TestSingleEventLoop:
    """All steps in a pipeline must share the SAME event loop."""

    def test_all_steps_share_same_event_loop(self):
        """C1: When pipeline runs, every step executes on the same loop."""
        step_a = LoopRecordingStep(label="a")
        step_b = LoopRecordingStep(label="b")
        step_c = LoopRecordingStep(label="c")

        cfg = PipelineConfig(steps=[
            StepConfig(name="a", component_type="test", strategy="loop_rec",
                       depends_on=["original_query"], provides="out_a"),
            StepConfig(name="b", component_type="test", strategy="loop_rec",
                       depends_on=["out_a"], provides="out_b"),
            StepConfig(name="c", component_type="test", strategy="loop_rec",
                       depends_on=["out_b"], provides="out_c"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={
                "a": lambda sc: step_a,
                "b": lambda sc: step_b,
                "c": lambda sc: step_c,
            },
            initial_keys={"original_query"},
        )

        state, tracelog = runner.run(
            initial_state={"original_query": "test"}
        )

        assert tracelog.success_count == 3
        assert step_a.recorded_loop_id is not None
        assert step_b.recorded_loop_id is not None
        assert step_c.recorded_loop_id is not None

        # The core invariant: all three steps ran on the SAME loop
        assert step_a.recorded_loop_id == step_b.recorded_loop_id == step_c.recorded_loop_id, (
            f"Loops differ: a={step_a.recorded_loop_id}, "
            f"b={step_b.recorded_loop_id}, c={step_c.recorded_loop_id}"
        )

    def test_no_runtime_error_from_missing_loop(self):
        """No step should raise RuntimeError from get_running_loop() — a loop must exist."""
        step = LoopRecordingStep(label="sole")
        cfg = PipelineConfig(steps=[
            StepConfig(name="sole", component_type="test", strategy="loop_rec",
                       depends_on=["original_query"], provides="out"),
        ])
        runner = PipelineRunner(
            config=cfg,
            step_factories={"sole": lambda sc: step},
            initial_keys={"original_query"},
        )
        state, tracelog = runner.run(initial_state={"original_query": "test"})
        assert tracelog.success_count == 1
        assert step.recorded_loop_id != -1, "No event loop was running during step execution"


# ═════════════════════════════════════════════════════════════════════
# C2: Concurrent execution
# ═════════════════════════════════════════════════════════════════════


class TestConcurrentExecution:
    """Independent DAG branches execute concurrently, not sequentially."""

    def test_independent_branches_run_concurrently(self):
        """Two steps with no mutual dependency should overlap in time."""
        step_left = ConcurrentTimerStep(delay=0.05, label="left")
        step_right = ConcurrentTimerStep(delay=0.05, label="right")

        cfg = PipelineConfig(steps=[
            StepConfig(name="source", component_type="test", strategy="timer",
                       depends_on=["original_query"], provides="data"),
            StepConfig(name="left", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_left"),
            StepConfig(name="right", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_right"),
        ])

        # source step just passes data through
        source = LoopRecordingStep(label="source")

        runner = PipelineRunner(
            config=cfg,
            step_factories={
                "source": lambda sc: source,
                "left": lambda sc: step_left,
                "right": lambda sc: step_right,
            },
            initial_keys={"original_query"},
        )
        state, tracelog = runner.run(initial_state={"original_query": "test"})

        assert tracelog.success_count == 3

        # If concurrent: left and right overlapped in time
        # left.start < right.end AND right.start < left.end
        left_overlaps_right = (
            step_left.start_time < step_right.end_time
            and step_right.start_time < step_left.end_time
        )
        assert left_overlaps_right, (
            f"Independent branches did NOT overlap — likely running sequentially. "
            f"Left: {step_left.start_time:.4f}-{step_left.end_time:.4f}, "
            f"Right: {step_right.start_time:.4f}-{step_right.end_time:.4f}"
        )

    def test_concurrent_execution_faster_than_sequential(self):
        """Two 0.05s steps concurrently: total < 0.10s (sequential would be >= 0.10s)."""
        step_a = ConcurrentTimerStep(delay=0.05, label="a")
        step_b = ConcurrentTimerStep(delay=0.05, label="b")

        cfg = PipelineConfig(steps=[
            StepConfig(name="source", component_type="test", strategy="timer",
                       depends_on=["original_query"], provides="data"),
            StepConfig(name="a", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_a"),
            StepConfig(name="b", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_b"),
        ])
        source = LoopRecordingStep(label="source")

        runner = PipelineRunner(
            config=cfg,
            step_factories={
                "source": lambda sc: source,
                "a": lambda sc: step_a,
                "b": lambda sc: step_b,
            },
            initial_keys={"original_query"},
        )

        t0 = time.perf_counter()
        state, tracelog = runner.run(initial_state={"original_query": "test"})
        total_duration = time.perf_counter() - t0

        assert tracelog.success_count == 3

        # Concurrent: total should be roughly max(delays) not sum(delays)
        # 0.05s concurrently should complete in < 0.10s
        assert total_duration < 0.10, (
            f"Concurrent execution took {total_duration:.3f}s — "
            f"expected < 0.10s for two 0.05s concurrent steps"
        )


# ═════════════════════════════════════════════════════════════════════
# C3: Step.run() is async (no per-step asyncio.run())
# ═════════════════════════════════════════════════════════════════════


class TestNoPerStepAsyncioRun:
    """After Phase 8.1, no step should call asyncio.run() internally."""

    def test_steps_dont_nest_event_loops(self):
        """Steps must NOT create new event loops via asyncio.run()."""
        # This test verifies that LoopRecordingStep.async_run() doesn't crash
        # when called from within an already-running event loop.
        # If a step called asyncio.run() internally, it would raise RuntimeError.
        step = LoopRecordingStep(label="nested_test")

        async def run_in_loop():
            return await step.async_run(
                inputs={"query": "test"},
                resources=ResourceContainer(),
            )

        result = asyncio.run(run_in_loop())
        assert result.result["loop_id"] is not None
        assert result.result["loop_id"] != -1


# ═════════════════════════════════════════════════════════════════════
# C4: ResourceContainer lifecycle
# ═════════════════════════════════════════════════════════════════════


class TestResourceLifecycle:
    """ResourceContainer lives for the entire pipeline, not per-step."""

    def test_state_persists_across_steps(self):
        """State set by earlier steps is visible to later steps."""
        step_a = ResourceAwareStep(resource_key="counter")
        step_b = ResourceAwareStep(resource_key="counter")
        step_c = ResourceAwareStep(resource_key="counter")

        cfg = PipelineConfig(steps=[
            StepConfig(name="a", component_type="test", strategy="res",
                       depends_on=["original_query"], provides="out_a"),
            StepConfig(name="b", component_type="test", strategy="res",
                       depends_on=["out_a"], provides="out_b"),
            StepConfig(name="c", component_type="test", strategy="res",
                       depends_on=["out_b"], provides="out_c"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={
                "a": lambda sc: step_a,
                "b": lambda sc: step_b,
                "c": lambda sc: step_c,
            },
            initial_keys={"original_query"},
        )

        state, tracelog = runner.run(initial_state={"original_query": "test"})
        assert tracelog.success_count == 3
        # Each step incremented, so final value should be 3
        assert state["out_c"]["value"] == 3

    def test_resources_not_closed_between_steps(self):
        """ResourceContainer.close() must not be called between steps."""
        closing_log: List[str] = []

        class WatchedContainer(ResourceContainer):
            def close(self):
                closing_log.append("closed")
                super().close()

        step_a = LoopRecordingStep(label="a")
        step_b = LoopRecordingStep(label="b")

        cfg = PipelineConfig(steps=[
            StepConfig(name="a", component_type="test", strategy="loop_rec",
                       depends_on=["original_query"], provides="out_a"),
            StepConfig(name="b", component_type="test", strategy="loop_rec",
                       depends_on=["out_a"], provides="out_b"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={"a": lambda sc: step_a, "b": lambda sc: step_b},
            initial_keys={"original_query"},
        )

        resources = WatchedContainer()
        state, tracelog = runner.run(
            initial_state={"original_query": "test"},
            resources=resources,
        )
        assert tracelog.success_count == 2
        # Should close exactly once at pipeline end
        assert closing_log == ["closed"], (
            f"Expected exactly one close at pipeline end, got: {closing_log}"
        )


# ═════════════════════════════════════════════════════════════════════
# C5: TraceLog concurrency semantics
# ═════════════════════════════════════════════════════════════════════


class TestTraceLogConcurrency:
    """TraceLog correctly records concurrent steps."""

    def test_concurrent_steps_have_distinct_traces(self):
        """Each concurrent step gets its own StepTrace entry."""
        step_left = ConcurrentTimerStep(delay=0.02, label="left")
        step_right = ConcurrentTimerStep(delay=0.02, label="right")
        source = LoopRecordingStep(label="source")

        cfg = PipelineConfig(steps=[
            StepConfig(name="source", component_type="test", strategy="timer",
                       depends_on=["original_query"], provides="data"),
            StepConfig(name="left", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_left"),
            StepConfig(name="right", component_type="test", strategy="timer",
                       depends_on=["data"], provides="out_right"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={
                "source": lambda sc: source,
                "left": lambda sc: step_left,
                "right": lambda sc: step_right,
            },
            initial_keys={"original_query"},
        )
        state, tracelog = runner.run(initial_state={"original_query": "test"})

        assert tracelog.success_count == 3
        step_names = {t.step_name for t in tracelog.steps}
        assert "left" in step_names
        assert "right" in step_names

    def test_tracelog_pipeline_run_id_is_consistent(self):
        """All StepTraces share the same pipeline_run_id."""
        step_a = LoopRecordingStep(label="a")
        step_b = LoopRecordingStep(label="b")

        cfg = PipelineConfig(steps=[
            StepConfig(name="a", component_type="test", strategy="loop_rec",
                       depends_on=["original_query"], provides="out_a"),
            StepConfig(name="b", component_type="test", strategy="loop_rec",
                       depends_on=["out_a"], provides="out_b"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={"a": lambda sc: step_a, "b": lambda sc: step_b},
            initial_keys={"original_query"},
        )
        state, tracelog = runner.run(initial_state={"original_query": "test"})

        run_ids = {t.pipeline_run_id for t in tracelog.steps}
        assert len(run_ids) == 1, f"Expected one pipeline_run_id, got {run_ids}"


# ═════════════════════════════════════════════════════════════════════
# C6: Health check in shared loop
# ═════════════════════════════════════════════════════════════════════


class TestHealthCheckInSharedLoop:
    """health_check() works correctly within the shared event loop."""

    def test_health_check_detects_running_loop_during_pipeline(self):
        """When health_check is called from within a step (during pipeline run),
        it must see the shared event loop — not create a new one."""
        # HealthCheckStep.health_check() detects the running loop
        step = HealthCheckStep()

        cfg = PipelineConfig(steps=[
            StepConfig(name="hc", component_type="test", strategy="health",
                       depends_on=["original_query"], provides="out"),
        ])

        runner = PipelineRunner(
            config=cfg,
            step_factories={"hc": lambda sc: step},
            initial_keys={"original_query"},
        )

        # Call health_check DURING pipeline execution via on_step callback
        health_results: list[HealthStatus] = []

        def check_during(step_trace):
            hs = step.health_check()
            health_results.append(hs)
            return False  # don't cancel

        state, tracelog = runner.run(
            initial_state={"original_query": "test"},
            on_step=check_during,
        )
        assert tracelog.success_count == 1
        assert len(health_results) == 1
        # During pipeline execution, a loop IS running
        assert health_results[0].status == "healthy", (
            f"health_check during pipeline should see running loop: {health_results[0].message}"
        )

    def test_health_check_works_outside_pipeline_too(self):
        """health_check() should work both inside and outside pipeline context."""
        step = HealthCheckStep()
        hs = step.health_check()
        # Outside pipeline: may be healthy or degraded, but NOT crash
        assert hs.status in ("healthy", "degraded"), (
            f"health_check crashed or returned unexpected: {hs.status}"
        )
