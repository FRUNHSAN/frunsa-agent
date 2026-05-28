"""Pipeline composition contracts: data models with zero business logic.

All dataclasses are frozen and hashable. No algorithm, no I/O, no side effects.

Design invariant:
  - Blueprint is pure data (no resolve(), no YAML parsing in the instance)
  - SourceRule carries deterministic rule_id for chunk-level lineage
  - AssemblyDiagnostic is the structured error representation
  - CompositionEvent is the engine decision log protocol
  - YAML parsing lives in CompositionBlueprint.from_yaml() classmethod
    (a data constructor, not an algorithm)
"""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from fnmatch import fnmatch
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Literal, Tuple

from .chunking import SemVer


# ── Source Rule ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRule:
    """Maps a glob pattern to a chunking strategy with parameters.

    Attributes:
        pattern:      Glob pattern for source file paths
        chunker:      Strategy name in COMPONENT_REGISTRY
        chunk_params: kwargs forwarded to chunker constructor
        priority:     Lower = higher priority (default 100)
        description:  Human-readable rule explanation
        rule_id:      Deterministic hash of (pattern, chunker, priority).
                      Explicitly settable in YAML, auto-generated if empty.
    """

    pattern: str
    chunker: str
    chunk_params: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    priority: int = 100
    description: str = ""
    rule_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "chunk_params",
            MappingProxyType(deepcopy(dict(self.chunk_params)))
        )
        if not self.rule_id:
            raw = f"{self.pattern}|{self.chunker}|{self.priority}"
            rid = hashlib.sha256(raw.encode()).hexdigest()[:12]
            object.__setattr__(self, "rule_id", rid)

    def matches(self, path: str) -> bool:
        """Check if this rule's glob pattern matches the given file path."""
        return fnmatch(path, self.pattern)


# ── Composition Blueprint ───────────────────────────────────────────

@dataclass(frozen=True)
class CompositionBlueprint:
    """Immutable pipeline composition specification.

    Pure data — no algorithm, no I/O. Factory methods (from_yaml, from_dict)
    are classmethods that produce Blueprint instances; they live here because
    they're data constructors, not orchestration logic.
    """

    version: SemVer
    default_chunker: str = "recursive"
    default_params: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    source_rules: Tuple[SourceRule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "default_params",
            MappingProxyType(deepcopy(dict(self.default_params)))
        )
        sorted_rules = tuple(sorted(self.source_rules, key=lambda r: r.priority))
        if sorted_rules != self.source_rules:
            object.__setattr__(self, "source_rules", sorted_rules)

    @property
    def rules_by_priority(self) -> Tuple[SourceRule, ...]:
        return self.source_rules

    @property
    def fingerprint(self) -> str:
        """Deterministic hash of the entire blueprint content."""
        canonical = json.dumps({
            "version": str(self.version),
            "default_chunker": self.default_chunker,
            "default_params": dict(self.default_params),
            "rules": [
                {
                    "pattern": r.pattern,
                    "chunker": r.chunker,
                    "chunk_params": dict(r.chunk_params),
                    "priority": r.priority,
                    "rule_id": r.rule_id,
                }
                for r in self.source_rules
            ],
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @classmethod
    def from_yaml(cls, path: str) -> CompositionBlueprint:
        """Parse a YAML file into a CompositionBlueprint."""
        import yaml
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls._from_raw(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> CompositionBlueprint:
        """Programmatic construction (for tests, API, database sources)."""
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict) -> CompositionBlueprint:
        version = SemVer.parse(raw["version"])
        default_chunker = raw.get("default_chunker", "recursive")
        default_params = raw.get("default_params", {})

        rules = []
        for r in raw.get("source_rules", []):
            if not r.get("pattern"):
                raise ValueError(f"SourceRule missing 'pattern': {r}")
            if not r.get("chunker"):
                raise ValueError(f"SourceRule missing 'chunker': {r}")
            rules.append(SourceRule(
                pattern=r["pattern"],
                chunker=r["chunker"],
                chunk_params=r.get("chunk_params", {}),
                priority=r.get("priority", 100),
                description=r.get("description", ""),
                rule_id=r.get("rule_id", ""),
            ))

        return cls(
            version=version,
            default_chunker=default_chunker,
            default_params=default_params,
            source_rules=tuple(rules),
        )


# ── Assembly Diagnostic ──────────────────────────────────────────────

@dataclass(frozen=True)
class AssemblyDiagnostic:
    """Structured error from the assembly phase.

    Attributes:
        path:              Source file path that caused the error
        chunker:           Chunker strategy name (or "unknown" if routing failed)
        error_type:        routing | instantiation | execution | validation
        message:           Human-readable error description
        contract_violation: Optional — which contract rule was violated.
                           Phase 19 fills None; Phase 25+ uses this for graceful
                           degradation decisions (repair / renegotiate / abandon).
        timestamp:         epoch seconds when the error was recorded
    """

    path: str
    chunker: str
    error_type: Literal["routing", "instantiation", "execution", "validation"]
    message: str
    contract_violation: str | None = None
    timestamp: float = field(default_factory=time.time)


# ── Composition Event ────────────────────────────────────────────────

@dataclass(frozen=True)
class CompositionEvent:
    """Engine decision log entry.

    The engine never calls logging.info() directly. It emits CompositionEvent
    objects through an injected event_sink callback. This decouples the engine
    from any specific logging/observability framework.

    Attributes:
        event_type:     rule_matched | rule_skipped | fallback_used |
                        chunker_instantiated | document_failed | assembly_complete
        correlation_id: Cross-event tracing key. Same value for all events
                        related to the same document (e.g. path hash or UUID).
        timestamp:      epoch seconds
        context:        Structured dict, never a formatted string.
    """

    event_type: Literal[
        "rule_matched", "rule_skipped", "fallback_used",
        "chunker_instantiated", "document_failed", "assembly_complete",
    ]
    correlation_id: str
    timestamp: float
    context: MappingProxyType[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "context",
            MappingProxyType(deepcopy(dict(self.context)))
        )
