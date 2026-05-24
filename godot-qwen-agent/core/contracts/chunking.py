"""
Component contracts for chunking: data models and strategy protocol.

ContentBlock and Chunk are frozen dataclasses with immutable metadata (MappingProxyType).
ChunkingStrategy is a Protocol — any class with VERSION (SemVer) and chunk() conforms,
no inheritance required.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Dict, List, Set, Tuple


# ── Semantic Version ────────────────────────────────────────────────


@dataclass(frozen=True)
class SemVer:
    """Strict three-part semantic version (X.Y.Z) with optional pre-release and build metadata."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    _PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
    )

    @classmethod
    def parse(cls, version_str: str) -> SemVer:
        m = cls._PATTERN.match(version_str.strip())
        if not m:
            raise ValueError(
                f"Invalid SemVer: '{version_str}'. "
                f"Must be 'X.Y.Z' (e.g., '1.0.0'), "
                f"optionally with pre-release (-alpha.1) or build (+20240101)."
            )
        return cls(
            major=int(m.group("major")),
            minor=int(m.group("minor")),
            patch=int(m.group("patch")),
            prerelease=m.group("prerelease"),
            build=m.group("build"),
        )

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += f"-{self.prerelease}"
        if self.build:
            s += f"+{self.build}"
        return s

    def __ge__(self, other: SemVer) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        a = (self.major, self.minor, self.patch, self.prerelease or "")
        b = (other.major, other.minor, other.patch, other.prerelease or "")
        return a >= b

    def __lt__(self, other: SemVer) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        a = (self.major, self.minor, self.patch, self.prerelease or "")
        b = (other.major, other.minor, other.patch, other.prerelease or "")
        return a < b


# ── Data Models ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ContentBlock:
    """Immutable input to a chunking strategy."""

    text: str
    source: str  # file path, URI, or document ID
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(deepcopy(dict(self.metadata))))

    @classmethod
    def from_dict(
        cls, text: str, source: str, metadata: Dict[str, Any] | None = None
    ) -> ContentBlock:
        """Factory with deepcopy defence: external mutation of the original dict won't affect us."""
        return cls(
            text=text,
            source=source,
            metadata=MappingProxyType(deepcopy(metadata or {})),
        )


@dataclass(frozen=True)
class Chunk:
    """Immutable output of a chunking strategy. Carries traceability and positional info."""

    text: str
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    source_strategy: str = ""  # qualified name, e.g. "chunking.identity"
    span: Tuple[int, int] = field(default_factory=lambda: (0, 0))  # (start, end) in source

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(deepcopy(dict(self.metadata))))

    def with_metadata(self, **kwargs: Any) -> Chunk:
        """Create a new Chunk with additional metadata fields (immutable pattern)."""
        new_meta = dict(self.metadata)
        new_meta.update(kwargs)
        return Chunk(
            text=self.text,
            metadata=MappingProxyType(new_meta),
            source_strategy=self.source_strategy,
            span=self.span,
        )


# ── Strategy Protocol ────────────────────────────────────────────────


class ChunkingStrategy:
    """
    Protocol for chunking strategies (structural, no ABC required).

    Mandatory:
      VERSION: ClassVar[SemVer]
      chunk(content: ContentBlock) -> List[Chunk]

    Optional:
      validate_config(config: dict) -> None   — pre-flight config check
      requires_metadata: ClassVar[Set[str]]   — metadata fields needed from upstream
      provides_metadata: ClassVar[Set[str]]   — metadata fields guaranteed on output
    """
