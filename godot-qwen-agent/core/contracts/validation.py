"""Structured validation types and runtime output validators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Tuple

from .chunking import Chunk
from .generation import GenerationResult
from .retrieval import RetrievalResult


@dataclass(frozen=True)
class ValidationError:
    """Single validation finding with machine-parseable field/code/level."""

    field: str    # e.g. "chunks[0].span"
    code: str     # e.g. "EMPTY_TEXT", "INVERTED_SPAN", "TYPE_MISMATCH"
    message: str
    level: Literal["error", "warning", "info"] = "error"


@dataclass(frozen=True)
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


# ── Generation output validator ────────────────────────────────────


def validate_generation_output(result: GenerationResult) -> ContractValidationResult:
    """Runtime validation of LLM generation output.

    Checks: type correctness, non-empty text (warning), finish_reason validity (info),
    usage fields present (warning).
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    if not isinstance(result, GenerationResult):
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="output",
                    code="NOT_GENERATION_RESULT",
                    message=f"Expected GenerationResult, got {type(result).__name__}",
                )
            ],
        )

    if not result.text or not result.text.strip():
        warnings.append(
            ValidationError(
                field="result.text",
                code="EMPTY_GENERATION",
                message="Generation produced empty text",
                level="warning",
            )
        )

    known_reasons = {"stop", "length", "content_filter", "tool_calls"}
    if result.finish_reason not in known_reasons:
        warnings.append(
            ValidationError(
                field="result.finish_reason",
                code="UNKNOWN_FINISH_REASON",
                message=f"Unrecognized finish_reason: {result.finish_reason}",
                level="warning",
            )
        )

    if result.total_tokens == 0 and result.finish_reason != "error":
        warnings.append(
            ValidationError(
                field="result.usage",
                code="ZERO_TOKENS",
                message="Generation used zero tokens — possible placeholder result",
                level="warning",
            )
        )

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        chunk_count=len(result.text),
        total_chars=len(result.text),
    )


# ── Reranker output validator ───────────────────────────────────────


def validate_reranker_output(
    results: List[RetrievalResult], input_len: int
) -> ContractValidationResult:
    """Runtime validation of reranker/scoring output.

    Contract checks:
      - Every element is a RetrievalResult
      - Output length <= input length (error if violated)
      - Ranks are sequential starting at 1 (warning if not)
      - Scores are in descending order (warning if not)
      - Scores are in [-1, 1] (warning if outside)
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    if not isinstance(results, list):
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="output",
                    code="NOT_A_LIST",
                    message=f"Expected list, got {type(results).__name__}",
                )
            ],
        )

    # Length contract
    if len(results) > input_len:
        errors.append(
            ValidationError(
                field="results",
                code="OUTPUT_EXCEEDS_INPUT",
                message=f"Reranker returned {len(results)} results for {input_len} input chunks",
            )
        )

    total_score = 0.0
    for i, item in enumerate(results):
        if not isinstance(item, RetrievalResult):
            errors.append(
                ValidationError(
                    field=f"results[{i}]",
                    code="TYPE_MISMATCH",
                    message=f"Expected RetrievalResult, got {type(item).__name__}",
                )
            )
            continue

        # Score range
        if not (-1.0 <= item.score <= 1.0):
            warnings.append(
                ValidationError(
                    field=f"results[{i}].score",
                    code="SCORE_OUT_OF_RANGE",
                    message=f"Score {item.score} is outside [-1, 1]",
                    level="warning",
                )
            )

        total_score += item.score

    # Rank contract
    for i, item in enumerate(r for r in results if isinstance(r, RetrievalResult)):
        if item.rank != i + 1:
            warnings.append(
                ValidationError(
                    field=f"results[{i}].rank",
                    code="NON_SEQUENTIAL_RANK",
                    message=f"Expected rank {i + 1}, got {item.rank}",
                    level="warning",
                )
            )

    # Descending score contract
    score_list = [r.score for r in results if isinstance(r, RetrievalResult)]
    if score_list != sorted(score_list, reverse=True):
        warnings.append(
            ValidationError(
                field="results[*].score",
                code="UNSORTED_SCORES",
                message="Results are not sorted by descending score",
                level="warning",
            )
        )

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        chunk_count=len(results),
        total_chars=0,
    )


# ── Streaming output validator ───────────────────────────────────────


def validate_stream_output(items: list) -> ContractValidationResult:
    """Runtime validation of streaming generation output.

    Checks:
      - Every item is a StreamItem
      - Indices are sequential (0, 1, 2, ...)
      - Exactly one item has finish_reason != None (the terminal item)
      - Terminal item has is_terminal=True (warning if not)
      - No items appear after the terminal item
      - Total delta text is non-empty (warning)
    """
    from .generation import StreamItem as SI

    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    if not isinstance(items, list):
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="output", code="NOT_A_LIST",
                    message=f"Expected list, got {type(items).__name__}",
                )
            ],
        )

    if len(items) == 0:
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="output", code="EMPTY_STREAM",
                    message="Streaming produced zero items",
                )
            ],
        )

    finished_at: Optional[int] = None
    total_text = ""

    for i, item in enumerate(items):
        if not isinstance(item, SI):
            errors.append(
                ValidationError(
                    field=f"items[{i}]", code="TYPE_MISMATCH",
                    message=f"Expected StreamItem, got {type(item).__name__}",
                )
            )
            continue

        if item.index != i:
            warnings.append(
                ValidationError(
                    field=f"items[{i}].index", code="NON_SEQUENTIAL_INDEX",
                    message=f"Expected index {i}, got {item.index}",
                    level="warning",
                )
            )

        if item.finish_reason is not None:
            if finished_at is None:
                finished_at = i
            elif finished_at != i:
                errors.append(
                    ValidationError(
                        field=f"items[{i}].finish_reason",
                        code="MULTIPLE_FINISH",
                        message=f"Multiple items have finish_reason set. "
                        f"First at index {finished_at}, also at {i}.",
                    )
                )

        if finished_at is not None and i > finished_at:
            errors.append(
                ValidationError(
                    field=f"items[{i}]", code="ITEM_AFTER_FINISH",
                    message=f"Item at index {i} appears after finish_reason "
                    f"was set at index {finished_at}.",
                )
            )

        total_text += item.delta

    if not total_text.strip():
        warnings.append(
            ValidationError(
                field="items[*].delta", code="EMPTY_STREAM_TEXT",
                message="Total streamed text is empty or whitespace-only",
                level="warning",
            )
        )

    if finished_at is None:
        warnings.append(
            ValidationError(
                field="items[*].finish_reason", code="NO_FINISH_REASON",
                message="No item in the stream has a finish_reason set",
                level="warning",
            )
        )
    else:
        terminal = items[finished_at]
        if isinstance(terminal, SI) and not terminal.is_terminal:
            warnings.append(
                ValidationError(
                    field=f"items[{finished_at}].is_terminal",
                    code="TERMINAL_NOT_MARKED",
                    message="Terminal item (with finish_reason) should have is_terminal=True",
                    level="warning",
                )
            )

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        chunk_count=len(items),
        total_chars=len(total_text),
    )
