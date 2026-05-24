"""Shared test fixtures — ContentBlock, Chunk, PipelineConfig, and mock steps."""

from __future__ import annotations

from typing import Any, Dict, List

from core.contracts import Chunk, ContentBlock, IdentityChunker
from core.pipeline.engine import (
    HealthStatus,
    PipelineConfig,
    RetryPolicy,
    StepConfig,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer


def make_content_block(text: str = "hello world", source: str = "test") -> ContentBlock:
    return ContentBlock.from_dict(text, source, {"test": True})


def make_chunk(text: str = "hello") -> Chunk:
    return Chunk(text=text, source_strategy="test", span=(0, len(text)))


def make_pipeline_config(
    steps: List[Dict[str, Any]] | None = None,
) -> PipelineConfig:
    if steps is None:
        steps = [
            {
                "name": "chunk_docs",
                "component_type": "chunker",
                "strategy": "identity",
                "params": {},
                "depends_on": ["document"],
                "provides": "chunks",
            }
        ]
    return PipelineConfig(steps=[StepConfig(**s) for s in steps])


def make_identity_step_config(name: str = "c1") -> StepConfig:
    return StepConfig(
        name=name,
        component_type="chunker",
        strategy="identity",
        depends_on=["document"],
        provides="chunks",
    )


class MockStep:
    """Synchronous mock step that returns a canned response."""

    def __init__(self, result: Any = "mock_result", should_fail: bool = False) -> None:
        self.result = result
        self.should_fail = should_fail

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        if self.should_fail:
            raise RuntimeError("mock failure")
        return StepOutput(result=self.result)

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="unavailable" if self.should_fail else "healthy",
            message="mock",
        )


class FailingStep:
    """Always raises RuntimeError."""

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        raise RuntimeError("boom")


class EmptyChunkerStep:
    """Returns empty chunk list to test auto-skip propagation."""

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        return StepOutput(result=[])


class DependentStep:
    """Step that depends on upstream output to verify skip propagation."""

    def __init__(self) -> None:
        self.was_called = False

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        self.was_called = True
        return StepOutput(result="called")
