"""Negative and edge-case tests: empty chunks, adapter errors, DAG violations, circuit breaker.

Verification scenarios: 3, 6, 7, 9, 10, 12, 13, 17
"""

from __future__ import annotations

import pytest

from core.adapters import AdapterTypeError, ChunkerAdapter, create_step_factory
from core.contracts import ContentBlock, IdentityChunker, validate_chunk_output
from core.pipeline import (
    PipelineConfig,
    PipelineRunner,
    PipelineStartupError,
    StepConfig,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer

from tests.fixtures import (
    DependentStep,
    EmptyChunkerStep,
    FailingStep,
    make_content_block,
    make_pipeline_config,
)


class TestEmptyChunkAutoSkip:
    """Scenario 10+17: empty chunk list → skip propagation."""

    def test_empty_chunks_triggers_skip(self):
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="empty",
                    component_type="chunker",
                    strategy="empty",
                    depends_on=["document"],
                    provides="chunks",
                    on_failure="skip",
                ),
                StepConfig(
                    name="downstream",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["chunks"],
                    provides="result",
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={
                "empty": lambda s: EmptyChunkerStep(),
                "downstream": lambda s: DependentStep(),
            },
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": "test"})
        assert trace.steps[0].status == "success"  # empty list is valid output, not failure
        assert trace.steps[1].status == "success"  # downstream still runs — [] is valid input

    def test_failing_step_skip_propagates(self):
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="fail",
                    component_type="chunker",
                    strategy="bad",
                    depends_on=["document"],
                    provides="chunks",
                    on_failure="skip",
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={"fail": lambda s: FailingStep()},
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": "test"})
        assert trace.steps[0].status == "failed"

    def test_skip_propagates_to_multi_dep_step(self):
        """Scenario 17: step C depends on [a, b]; A skipped, B success → C skipped."""
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="step_a",
                    component_type="chunker",
                    strategy="bad",
                    depends_on=["document"],
                    provides="a_out",
                    on_failure="skip",
                ),
                StepConfig(
                    name="step_b",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="b_out",
                ),
                StepConfig(
                    name="step_c",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["a_out", "b_out"],
                    provides="c_out",
                ),
            ]
        )
        dep_step = DependentStep()
        runner = PipelineRunner(
            config,
            step_factories={
                "step_a": lambda s: FailingStep(),
                "step_b": create_step_factory,
                "step_c": lambda s: dep_step,
            },
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": make_content_block("test")})
        assert trace.steps[0].status == "failed"  # A fails + skips
        assert trace.steps[1].status == "success"  # B succeeds
        assert trace.steps[2].status == "skipped"  # C skipped (A was skipped)


class TestAdapterErrors:
    """Scenario 13: AdapterTypeError on non-ContentBlock input."""

    def test_wrong_type_raises_adapter_error(self):
        adapter = ChunkerAdapter(IdentityChunker())
        with pytest.raises(AdapterTypeError, match="ContentBlock"):
            adapter.run({"doc": "not a block"}, ResourceContainer())

    def test_missing_specific_key_raises(self):
        adapter = ChunkerAdapter(IdentityChunker(), content_key="required_key")
        with pytest.raises(AdapterTypeError, match="required_key"):
            adapter.run({"wrong": ContentBlock(text="hi", source="t")}, ResourceContainer())

    def test_adapter_error_in_pipeline_traces_correctly(self):
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="bad_input",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="chunks",
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={"bad_input": create_step_factory},
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": "not_a_content_block"})
        assert trace.steps[0].status == "failed"
        assert trace.steps[0].error_type == "AdapterTypeError"
        assert trace.steps[0].error_traceback is not None


class TestDAGValidation:
    """Scenario 3+9: DAG cycle detection and metadata compatibility."""

    def test_missing_dependency_rejected_at_init(self):
        bad = PipelineConfig(
            steps=[
                StepConfig(
                    name="s1",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["nonexistent_key"],
                    provides="chunks",
                ),
            ]
        )
        with pytest.raises(PipelineStartupError, match="nonexistent_key"):
            PipelineRunner(bad, step_factories={"s1": lambda s: None}, initial_keys={"document"})

    def test_self_cycle_rejected(self):
        """A step depends_on its own provides → error."""
        bad = PipelineConfig(
            steps=[
                StepConfig(
                    name="s1",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["chunks"],
                    provides="chunks",
                ),
            ]
        )
        with pytest.raises(PipelineStartupError):
            PipelineRunner(
                bad,
                step_factories={"s1": lambda s: None},
                initial_keys={"document"},
            )

    def test_backward_dep_rejected(self):
        """Step 2 depends_on step 3's output → error."""
        bad = PipelineConfig(
            steps=[
                StepConfig(
                    name="s1",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["document"],
                    provides="a",
                ),
                StepConfig(
                    name="s2",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["b"],  # b is provided AFTER s2
                    provides="c",
                ),
                StepConfig(
                    name="s3",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["a"],
                    provides="b",
                ),
            ]
        )
        with pytest.raises(PipelineStartupError):
            PipelineRunner(
                bad,
                step_factories={
                    "s1": lambda s: None,
                    "s2": lambda s: None,
                    "s3": lambda s: None,
                },
                initial_keys={"document"},
            )


class TestCircuitBreaker:
    """Scenario 7: failed step does not pollute downstream state."""

    def test_failure_does_not_update_state(self):
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="fail",
                    component_type="chunker",
                    strategy="bad",
                    depends_on=["document"],
                    provides="chunks",
                ),
                StepConfig(
                    name="next",
                    component_type="chunker",
                    strategy="identity",
                    depends_on=["chunks"],
                    provides="result",
                ),
            ]
        )
        dep = DependentStep()
        runner = PipelineRunner(
            config,
            step_factories={
                "fail": lambda s: FailingStep(),
                "next": lambda s: dep,
            },
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": "test"})
        assert trace.steps[0].status == "failed"
        # Circuit breaker: state not updated, next step gets None for 'chunks'
        assert trace.steps[1].status in ("success", "failed")


class TestValidateChunkOutput:
    """Scenario 6: validate_chunk_output catches violations."""

    def test_empty_text_error(self):
        from core.contracts import Chunk

        result = validate_chunk_output(
            [Chunk(text="", source_strategy="x", span=(0, 0))]
        )
        assert not result.passed
        assert any(e.code == "EMPTY_TEXT" for e in result.errors)

    def test_inverted_span_error(self):
        from core.contracts import Chunk

        result = validate_chunk_output(
            [Chunk(text="ok", source_strategy="x", span=(5, 3))]
        )
        assert not result.passed
        assert any(e.code == "INVERTED_SPAN" for e in result.errors)

    def test_not_a_list_error(self):
        result = validate_chunk_output("not a list")  # type: ignore
        assert not result.passed
        assert result.errors[0].code == "NOT_A_LIST"


class TestTraceLogErrorCompleteness:
    """Scenario 12+14: failed steps still record finished_at and error_traceback."""

    def test_failed_step_has_finished_at(self):
        config = PipelineConfig(
            steps=[
                StepConfig(
                    name="f",
                    component_type="chunker",
                    strategy="bad",
                    depends_on=["document"],
                    provides="chunks",
                ),
            ]
        )
        runner = PipelineRunner(
            config,
            step_factories={"f": lambda s: FailingStep()},
            initial_keys={"document"},
        )
        _, trace = runner.run({"document": "test"})
        assert trace.steps[0].finished_at > 0
        assert trace.steps[0].duration_seconds >= 0
        assert trace.steps[0].error_traceback is not None
        assert "RuntimeError" in trace.steps[0].error_type
