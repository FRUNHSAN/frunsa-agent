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
from enum import Enum
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


# ── Contract Lifecycle Enum (Phase 21) ──────────────────────────────

class ContractLifecycle(str, Enum):
    """Blueprint lifecycle stages.

    str subclass — drop-in compatible with all existing string comparisons.
    Enum — IDE autocomplete, mypy exhaustiveness checking.

    Semantics:
      - DRAFT:      Experimental; violations are down-weighted (0.5x)
      - ACTIVE:     Production contract; violations at full severity (1.0x)
      - DEPRECATED: Legacy contract; violations heavily down-weighted (0.3x),
                    and new routing requests MUST be rejected.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


# ── Composition Blueprint ───────────────────────────────────────────

@dataclass(frozen=True)
class CompositionBlueprint:
    """Immutable pipeline composition specification.

    Pure data — no algorithm, no I/O. Factory methods (from_yaml, from_dict)
    are classmethods that produce Blueprint instances; they live here because
    they're data constructors, not orchestration logic.
    """

    version: SemVer
    lifecycle: ContractLifecycle = ContractLifecycle.ACTIVE
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
        # Normalize lifecycle from string (YAML/JSON) to enum
        if isinstance(self.lifecycle, str):
            object.__setattr__(
                self, "lifecycle", ContractLifecycle(self.lifecycle)
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
            "lifecycle": str(self.lifecycle),
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
        lifecycle_raw = raw.get("lifecycle", "active")
        lifecycle = ContractLifecycle(lifecycle_raw)
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
            lifecycle=lifecycle,
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


# ── Contract Violation Enum (Phase 20) ─────────────────────────────

class ContractViolation(str, Enum):
    """Enumeration of contract violation categories.

    str subclass — drop-in compatible with all existing string comparisons.
    Enum — IDE autocomplete, mypy exhaustiveness checking, no silent typo failures.

    These values correspond to _classify_violation() return categories in
    PipelineAssembler (core/adapters/composer.py).
    """

    UNKNOWN_CHUNKER_STRATEGY = "unknown_chunker_strategy"
    INVALID_CHUNK_PARAMS = "invalid_chunk_params"
    ROUTING_CONTRACT_BREACH = "routing_contract_breach"
    OUTPUT_CONTRACT_VIOLATION = "output_contract_violation"


# ── Severity Mapping (Phase 20) ─────────────────────────────────────

@dataclass(frozen=True)
class SeverityRule:
    """A single rule mapping violation count → severity level.

    Attributes:
        violation_type: ContractViolation category this rule applies to
        count_threshold: How many violations of this type trigger the severity
        severity:        healthy | degraded | critical — the assigned level
    """

    violation_type: str
    count_threshold: int = 1
    severity: Literal["healthy", "degraded", "critical"] = "degraded"

    def __post_init__(self) -> None:
        if self.count_threshold < 1:
            raise ValueError(
                f"count_threshold must be >= 1, got {self.count_threshold}"
            )


@dataclass(frozen=True)
class SeverityMapping:
    """Declarative rules for translating violation counts → health severity.

    Consumed by ContractHealthEvaluator. The mapping is injectable so tests
    and production configs can use different thresholds without touching
    evaluator code.

    Rules are applied in order; the most severe match wins.
    """

    rules: Tuple[SeverityRule, ...] = ()

    @classmethod
    def default(cls) -> SeverityMapping:
        """Factory producing sensible defaults for Phase 20."""
        return cls(rules=(
            SeverityRule(
                violation_type=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
                count_threshold=1,
                severity="critical",
            ),
            SeverityRule(
                violation_type=ContractViolation.ROUTING_CONTRACT_BREACH,
                count_threshold=3,
                severity="critical",
            ),
            SeverityRule(
                violation_type=ContractViolation.INVALID_CHUNK_PARAMS,
                count_threshold=1,
                severity="degraded",
            ),
            SeverityRule(
                violation_type=ContractViolation.OUTPUT_CONTRACT_VIOLATION,
                count_threshold=1,
                severity="degraded",
            ),
        ))


# ── Contract Health Report (Phase 20) ───────────────────────────────

@dataclass(frozen=True)
class ContractHealthReport:
    """Aggregated health assessment derived from CompositionEvent history.

    Pure data — computed by ContractHealthEvaluator, consumed by future
    relationship-layer decision logic (Phase 25+).

    Attributes:
        compliance_rate:         0.0–1.0 fraction of documents without violations
        severity:                Overall health level (healthy/degraded/critical)
        dominant_violation_type: Most frequent violation category, or None
        trend:                   Direction vs previous report, or None if first
        total_documents:         Number of documents tracked in the events
        total_events:            Total CompositionEvents processed
        violation_counts:        {violation_type: count} breakdown
        evaluated_at:            epoch timestamp of evaluation
    """

    compliance_rate: float
    severity: Literal["healthy", "degraded", "critical"]
    dominant_violation_type: str | None
    trend: Literal["improving", "stable", "deteriorating"] | None
    total_documents: int
    total_events: int
    violation_counts: MappingProxyType[str, int]
    evaluated_at: float
    lifecycle_distribution: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "violation_counts",
            MappingProxyType(deepcopy(dict(self.violation_counts)))
        )
        object.__setattr__(
            self, "lifecycle_distribution",
            MappingProxyType(deepcopy(dict(self.lifecycle_distribution)))
        )
        if not 0.0 <= self.compliance_rate <= 1.0:
            raise ValueError(
                f"compliance_rate must be in [0.0, 1.0], got {self.compliance_rate}"
            )
