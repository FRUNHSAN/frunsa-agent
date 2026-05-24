"""Structured validation types and runtime chunk-output validator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Tuple

from .chunking import Chunk


@dataclass(frozen=True)
class ValidationError:
    """Single validation finding with machine-parseable field/code/level."""

    field: str    # e.g. "chunks[0].span"
    code: str     # e.g. "EMPTY_TEXT", "INVERTED_SPAN", "TYPE_MISMATCH"
    message: str
    level: Literal["error", "warning", "info"] = "error"


@dataclass
class ContractValidationResult:
    """Structured result of runtime contract validation."""

    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    chunk_count: int = 0
    total_chars: int = 0


def validate_chunk_output(chunks: List[Chunk]) -> ContractValidationResult:
    """Runtime validation of chunking output.

    Checks: type correctness, no empty text, span validity, strategy consistency,
    overlap detection (warning, not error).
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    if not isinstance(chunks, list):
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="output",
                    code="NOT_A_LIST",
                    message=f"Expected list, got {type(chunks).__name__}",
                )
            ],
        )

    strategies_seen: set[str] = set()
    spans: List[Tuple[int, int]] = []

    for i, item in enumerate(chunks):
        if not isinstance(item, Chunk):
            errors.append(
                ValidationError(
                    field=f"chunks[{i}]",
                    code="TYPE_MISMATCH",
                    message=f"Expected Chunk, got {type(item).__name__}",
                )
            )
            continue

        if not item.text or not item.text.strip():
            errors.append(
                ValidationError(
                    field=f"chunks[{i}].text",
                    code="EMPTY_TEXT",
                    message="Chunk text is empty or whitespace-only",
                )
            )

        start, end = item.span
        if start < 0:
            errors.append(
                ValidationError(
                    field=f"chunks[{i}].span.start",
                    code="NEGATIVE_SPAN",
                    message=f"Span start is negative: {start}",
                )
            )
        if end < start:
            errors.append(
                ValidationError(
                    field=f"chunks[{i}].span",
                    code="INVERTED_SPAN",
                    message=f"Span inverted: ({start}, {end})",
                )
            )
        if start == end and len(item.text) > 0:
            errors.append(
                ValidationError(
                    field=f"chunks[{i}].span",
                    code="ZERO_SPAN_WITH_TEXT",
                    message="Zero-length span but text is non-empty",
                )
            )

        spans.append((start, end))
        strategies_seen.add(item.source_strategy)

    if len(strategies_seen) > 1:
        warnings.append(
            ValidationError(
                field="chunks[*].source_strategy",
                code="MULTIPLE_STRATEGIES",
                message=f"Chunks from multiple strategies: {strategies_seen}",
                level="warning",
            )
        )

    sorted_spans = sorted(spans, key=lambda s: s[0])
    for j in range(len(sorted_spans) - 1):
        if sorted_spans[j][1] > sorted_spans[j + 1][0]:
            warnings.append(
                ValidationError(
                    field=f"chunks[{j}].span",
                    code="OVERLAPPING_SPANS",
                    message=f"Overlap: {sorted_spans[j]} and {sorted_spans[j+1]}",
                    level="warning",
                )
            )
            break

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        chunk_count=len(chunks),
        total_chars=sum(len(c.text) for c in chunks if isinstance(c, Chunk)),
    )
