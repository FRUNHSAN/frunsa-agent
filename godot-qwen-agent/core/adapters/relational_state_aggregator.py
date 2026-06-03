"""Relational State Aggregator — PLAN3 core engine.

Aggregates data from three sources into a single RelationalContext:
  1. RelationalField — current energy, urgency, trust
  2. ContractHealthReport — active violations, severity
  3. RelationshipMemoryStore — historical resonance, deterioration patterns

This is the unified "current state" that PLAN3's PromptGenerator reads
to dynamically grow System Instructions from a relational seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.contracts.composition import ContractHealthReport, ContractViolation
from core.contracts.event_sink import EventSink
from core.contracts.interaction_repository import InteractionRepository
from core.adapters.relational_inertia import RelationalHistory
from core.contracts.relational_field import RelationalField


@dataclass(frozen=True)
class RelationalContext:
    """Unified snapshot of the current human-agent relationship.

    This is what PromptGenerator reads to grow relational seeds into
    context-aware System Instructions. Every field is derived from
    live data, not static configuration.
    """

    # From RelationalField
    energy: str = "neutral"
    urgency: str = "normal"
    trust_watermark: float = 0.5
    trust_level: str = "stable"

    # From ContractHealthReport
    severity: str = "healthy"
    compliance_rate: float = 1.0
    dominant_violation: str | None = None
    intentional_violation_count: int = 0

    # From RelationshipMemoryStore
    deterioration_count_7d: int = 0
    transition_count_7d: int = 0
    historical_resonance: str = "none"  # "high" if user responded well to past adaptations

    # Aggregated
    interaction_rhythm: str = "normal"  # "fatigued" | "urgent" | "normal" | "leisurely"
    active_contracts: List[str] = field(default_factory=list)
    suggested_tone: str = "neutral"  # "brief" | "neutral" | "detailed" | "urgent"


class RelationalStateAggregator:
    """Aggregator: three data sources -> one RelationalContext.

    Usage:
        agg = RelationalStateAggregator()
        ctx = agg.aggregate(field, report, sink, memory, fp)
        seed = PromptGenerator.grow(ctx)  # PLAN3
    """

    def aggregate(
        self,
        field: RelationalField,
        report: ContractHealthReport | None,
        sink: EventSink,
        memory: InteractionRepository,
        blueprint_fingerprint: str,
        history: RelationalHistory | None = None,
    ) -> RelationalContext:
        """Aggregate all relational data into a single context."""

        # ── From RelationalField ──
        energy = field.energy_level.value
        urgency = field.urgency.value
        trust = field.trust_watermark
        trust_level = field.trust_level

        # ── From ContractHealthReport ──
        severity = report.severity if report else "healthy"
        compliance = report.compliance_rate if report else 1.0
        dominant = report.dominant_violation_type if report else None

        # Count intentional violations
        intentional_count = sum(
            1 for e in sink.violations
            if e.context.get("contract_violation") == ContractViolation.INTENTIONAL_VIOLATION
        )

        # ── From MemoryStore ──
        deterioration_7d = memory.get_deterioration_count(
            blueprint_fingerprint, days=7,
        )
        transition_7d = memory.count_transitions(
            blueprint_fingerprint, days=7,
        )

        # Historical resonance: did past adaptations get positive feedback?
        # (PLAN3 heuristic: if intentional violations exist AND severity is
        #  not critical, user accepted past adaptations)
        resonance = "none"
        if intentional_count >= 2 and severity != "critical":
            resonance = "high"
        elif intentional_count >= 1:
            resonance = "emerging"

        # ── Aggregated ──
        rhythm = "normal"
        if energy == "low":
            rhythm = "fatigued"
        elif urgency == "critical":
            rhythm = "urgent"
        elif urgency == "leisure":
            rhythm = "leisurely"

        # Tone suggestion
        tone = "neutral"
        if energy == "low":
            tone = "brief"
        elif urgency == "critical":
            tone = "urgent"
        elif resonance == "high":
            tone = "brief"  # user liked concise before
        if severity == "critical":
            tone = "urgent"

        # ── Relational Inertia (PLAN3/4) ──
        if history is not None:
            energy, urgency, trust, tone = history.smooth(
                energy, urgency, trust, tone,
            )
            history.record(energy, urgency, trust, tone)
            # Re-derive rhythm from smoothed values
            rhythm = "normal"
            if energy == "low":
                rhythm = "fatigued"
            elif urgency == "critical":
                rhythm = "urgent"
            elif urgency == "leisure":
                rhythm = "leisurely"

        return RelationalContext(
            energy=energy,
            urgency=urgency,
            trust_watermark=round(trust, 4),
            trust_level=trust_level,
            severity=severity,
            compliance_rate=round(compliance, 4),
            dominant_violation=dominant,
            intentional_violation_count=intentional_count,
            deterioration_count_7d=deterioration_7d,
            transition_count_7d=transition_7d,
            historical_resonance=resonance,
            interaction_rhythm=rhythm,
            active_contracts=list(field.active_contracts),
            suggested_tone=tone,
        )
