"""ChunkerAdapter: wraps a ChunkingStrategy to satisfy the PipelineStep protocol.

Strict translation — no implicit type conversion. If the input is not a
ContentBlock, AdapterTypeError is raised immediately.
"""

from __future__ import annotations

from typing import Any, Dict

from core.contracts import ChunkingStrategy, ContentBlock, validate_chunk_output
from core.pipeline.engine import PipelineStep, StepOutput, ResourceContainer


class AdapterTypeError(Exception):
    """Translation-layer type mismatch. Strict mode: bad input → error, no guessing."""


class ChunkerAdapter:
    """Adapts ChunkingStrategy → PipelineStep.

    Timeout is controlled by the engine via StepConfig, not by the adapter.
    """

    def __init__(self, strategy: ChunkingStrategy, content_key: str | None = None) -> None:
        self._strategy = strategy
        self._content_key = content_key  # None = take first input value

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        content = self._extract_content(inputs)
        chunks = self._strategy.chunk(content)
        validation = validate_chunk_output(chunks)

        return StepOutput(
            result=chunks,
            trace_log={
                "chunker": self._strategy.__class__.__name__,
                "version": str(self._strategy.VERSION),
            },
            contract_validation=validation,
        )

    def _extract_content(self, inputs: Dict[str, Any]) -> ContentBlock:
        if self._content_key:
            if self._content_key not in inputs:
                raise AdapterTypeError(
                    f"Expected key '{self._content_key}' in inputs, "
                    f"but only have {list(inputs.keys())}"
                )
            content = inputs[self._content_key]
        else:
            if not inputs:
                raise AdapterTypeError("No inputs provided to ChunkerAdapter")
            content = next(iter(inputs.values()))

        if not isinstance(content, ContentBlock):
            raise AdapterTypeError(
                f"Expected ContentBlock, got {type(content).__name__}. "
                f"Value: {repr(content)[:200]}"
            )
        return content
