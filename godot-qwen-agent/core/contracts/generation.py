"""Generation contracts: data models and strategy protocol for LLM generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Dict, List, Optional, Set

from .chunking import Chunk, SemVer


@dataclass(frozen=True)
class GenerationResult:
    """Single LLM generation output. Immutable — provider metadata can't be mutated downstream."""

    text: str
    model: str
    finish_reason: str  # "stop", "length", "content_filter", "tool_calls", etc.
    usage: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.usage, MappingProxyType):
            from copy import deepcopy

            object.__setattr__(
                self, "usage", MappingProxyType(deepcopy(dict(self.usage)))
            )
        if not isinstance(self.metadata, MappingProxyType):
            from copy import deepcopy

            object.__setattr__(
                self, "metadata", MappingProxyType(deepcopy(dict(self.metadata)))
            )

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


class GenerationStrategy:
    """Protocol for LLM generation strategies.

    Mandatory:
      VERSION: ClassVar[SemVer]
      generate(prompt: str, context: List[Chunk], **params) -> GenerationResult

    Optional:
      health_check() -> HealthStatus
      requires_metadata / provides_metadata class vars
    """

    VERSION: ClassVar[SemVer]
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = set()

    def generate(self, prompt: str, context: List[Chunk], **params: Any) -> GenerationResult:
        """Produce a GenerationResult from a prompt and optional context chunks."""
        ...

    def health_check(self) -> Any:
        """Optional health probe. Returns HealthStatus if implemented."""
        ...


@dataclass(frozen=True)
class StreamItem:
    """Single streaming token/chunk emitted during generation.

    Fields:
      delta: The incremental text (token or multi-token chunk).
      index: Zero-based sequence number of this item in the stream.
      finish_reason: None while streaming; set on the terminal item.
      model: The model producing this token.
      metadata: Provider-specific metadata (logprobs, token_id, etc.). Immutable.
      is_terminal: True for the final item in a stream (normal or error).
      error: Error description if the terminal item signals a failure.
    """

    delta: str
    index: int
    finish_reason: Optional[str] = None
    model: str = ""
    is_terminal: bool = False
    error: Optional[str] = None
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # Phase 9.1: opaque context bag for engine-specific tracing.
    # RAG: {"chunk_id": "...", "retrieval_latency_ms": ...}
    # Planning: {"step_index": 3, "reasoning_depth": 2}
    # Adapters pass through without inspection — each engine defines its own schema.
    trace_context: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            from copy import deepcopy

            object.__setattr__(
                self, "metadata", MappingProxyType(deepcopy(dict(self.metadata)))
            )
        if self.trace_context is not None:
            from copy import deepcopy

            object.__setattr__(
                self, "trace_context", deepcopy(dict(self.trace_context))
            )
