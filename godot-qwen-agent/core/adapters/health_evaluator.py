"""Contract Health Evaluator — Phase 20 + Phase 21 lifecycle weighting.

Aggregates discrete violation signals from ContractAwareEventSink into
a structured ContractHealthReport. This is the first layer that "understands"
the system's compliance state — transforming raw events into a decision-ready
health assessment.

Phase 21 adds lifecycle-aware severity: DRAFT violations are down-weighted (0.5x),
DEPRECATED violations are heavily down-weighted (0.3x), and ACTIVE violations
carry full weight (1.0x). This means 10 deprecated-routing violations may be
less severe than 1 active unknown_strategy violation.

Design invariants:
  - Pure function: no locks, no state mutation, no internal caching
  - Trend requires caller-provided previous report (stateless)
  - Severity mapping is injectable (testable, configurable)
  - Lifecycle weights are class-level constants (injectable in future Phase)
  - Zero truthiness checks on sink — all accesses are explicit method calls
  - Same input → same output (deterministic, offline-verifiable)

Future Phase 25+ consumers:
  - severity == 'critical' + trend == 'deteriorating' → trigger renegotiate
  - lifecycle_distribution shows deprecated-heavy → prompt cleanup
"""

from __future__ import annotations

import time
from typing import Dict

from core.contracts.composition import (
    ContractHealthReport,
    ContractLifecycle,
    SeverityMapping,
)
from core.contracts.event_sink import EventSink


class ContractHealthEvaluator:
    """Pure evaluator: violation signals → health assessment.

    Phase 21: lifecycle-aware — violations from deprecated blueprints
    are down-weighted; violations from draft blueprints are softened.

    Usage:
        evaluator = ContractHealthEvaluator()
        report = evaluator.evaluate(sink)
        # ... time passes, more composition runs ...
        next_report = evaluator.evaluate(sink, previous=report)
        # next_report.trend → 'improving' | 'stable' | 'deteriorating'
    """

    # Phase 21: lifecycle severity weights.
    # Active violations at full force; draft at half; deprecated at 0.3x.
    # Made class-level for transparency; injectable in future Phase.
    _LIFECYCLE_WEIGHTS: Dict[str, float] = {
        ContractLifecycle.ACTIVE: 1.0,
        ContractLifecycle.DRAFT: 0.5,
        ContractLifecycle.DEPRECATED: 0.3,
    }

    def __init__(
        self, severity_mapping: SeverityMapping | None = None
    ) -> None:
        self._mapping = severity_mapping if severity_mapping is not None else (
            SeverityMapping.default()
        )

    def evaluate(
        self,
        sink: EventSink,
        previous: ContractHealthReport | None = None,
    ) -> ContractHealthReport:
        """Produce a health report from the sink's current state.

        Args:
            sink:     ContractAwareEventSink with accumulated events
            previous: Optional previous report for trend calculation.
                      If None, trend is None (first assessment).

        Returns:
            ContractHealthReport — frozen, deterministic, JSON-serializable.
        """
        summary = sink.summary
        violations_by_cat = summary.get("violations_by_category", {})

        total_docs = summary["documents_tracked"]
        total_events = summary["total_events"]

        # Phase 21: compute lifecycle-weighted violation counts and distribution
        weighted_by_cat, lifecycle_dist = self._compute_weighted_violations(sink)

        # Compliance rate: fraction of documents without violations
        if total_docs == 0:
            compliance_rate = 1.0
        else:
            docs_with_violations = self._estimate_docs_with_violations(sink)
            compliance_rate = (total_docs - docs_with_violations) / total_docs
            compliance_rate = max(0.0, min(1.0, compliance_rate))

        # Phase 21: severity uses lifecycle-weighted counts
        severity = self._compute_severity(weighted_by_cat)

        # Dominant violation type (from raw counts — what's most frequent)
        dominant = self._dominant_violation(violations_by_cat)

        # Trend (stateless — requires caller-provided history)
        trend = self._compute_trend(previous, compliance_rate)

        return ContractHealthReport(
            compliance_rate=compliance_rate,
            severity=severity,
            dominant_violation_type=dominant,
            trend=trend,
            total_documents=total_docs,
            total_events=total_events,
            violation_counts=violations_by_cat,
            lifecycle_distribution=lifecycle_dist,
            evaluated_at=time.time(),
        )

    # ── Phase 21: Lifecycle-weighted violations ──────────────────

    @classmethod
    def _compute_weighted_violations(
        cls, sink: EventSink,
    ) -> tuple[Dict[str, float], Dict[str, int]]:
        """Compute lifecycle-weighted violation counts and distribution.

        Returns:
            (weighted_by_category, lifecycle_distribution)
            - weighted_by_category: {violation_type: weighted_count}
            - lifecycle_distribution: {lifecycle: unique_doc_count}
        """
        weighted: Dict[str, float] = {}
        lifecycle_docs: Dict[str, set] = {}

        for e in sink.violations:
            cv = e.context.get("contract_violation")
            lc = e.context.get("blueprint_lifecycle", ContractLifecycle.ACTIVE)
            weight = cls._LIFECYCLE_WEIGHTS.get(lc, 1.0)

            if cv:
                weighted[cv] = weighted.get(cv, 0.0) + weight

            # Track unique document correlation_ids per lifecycle
            cid = e.correlation_id
            if cid and cid != "batch":
                if lc not in lifecycle_docs:
                    lifecycle_docs[lc] = set()
                lifecycle_docs[lc].add(cid)

        lifecycle_dist = {
            lc: len(docs) for lc, docs in lifecycle_docs.items()
        }

        return weighted, lifecycle_dist

    # ── Internal (pure, testable) ────────────────────────────────

    def _compute_severity(
        self, violations_by_cat: dict
    ) -> str:
        """Compute severity from violation counts (raw or weighted).

        Accepts both int (Phase 20) and float (Phase 21 weighted) counts.
        The comparison is numeric — 0.6 weighted violations < 1 threshold.
        """
        result: str = "healthy"
        for rule in self._mapping.rules:
            count = violations_by_cat.get(rule.violation_type, 0)
            if count >= rule.count_threshold:
                if rule.severity == "critical":
                    return "critical"
                if rule.severity == "degraded":
                    result = "degraded"
        return result

    @staticmethod
    def _dominant_violation(violations_by_cat: dict) -> str | None:
        """Return the most frequent violation type, or None if no violations."""
        if not violations_by_cat:
            return None
        return max(violations_by_cat, key=lambda k: violations_by_cat[k])

    @staticmethod
    def _estimate_docs_with_violations(
        sink: EventSink,
    ) -> int:
        """Count unique documents that have at least one violation event.

        Uses correlation_id from violation events — each unique correlation_id
        (except 'batch') corresponds to a document that experienced a failure.
        """
        violation_events = sink.violations
        doc_ids: set[str] = set()
        for e in violation_events:
            cid = e.correlation_id
            if cid and cid != "batch":
                doc_ids.add(cid)
        return len(doc_ids)

    @staticmethod
    def _compute_trend(
        previous: ContractHealthReport | None,
        current_rate: float,
    ) -> str | None:
        """Determine trend direction from a previous report snapshot.

        Stateless — previous report is provided by caller, not stored internally.
        Returns None if no previous report exists (first assessment).
        """
        if previous is None:
            return None
        if current_rate > previous.compliance_rate:
            return "improving"
        if current_rate < previous.compliance_rate:
            return "deteriorating"
        return "stable"
