"""Contract Health Evaluator — Phase 20.

Aggregates discrete violation signals from ContractAwareEventSink into
a structured ContractHealthReport. This is the first layer that "understands"
the system's compliance state — transforming raw events into a decision-ready
health assessment.

Design invariants:
  - Pure function: no locks, no state mutation, no internal caching
  - Trend requires caller-provided previous report (stateless)
  - Severity mapping is injectable (testable, configurable)
  - Zero truthiness checks on sink — all accesses are explicit method calls
  - Same input → same output (deterministic, offline-verifiable)

Future Phase 25+ consumers:
  - severity == 'critical' + trend == 'deteriorating' → trigger renegotiate
  - compliance_rate < threshold → notify relationship layer
"""

from __future__ import annotations

import time
from typing import List

from core.contracts.composition import (
    ContractHealthReport,
    ContractViolation,
    SeverityMapping,
    SeverityRule,
)
from core.adapters.event_sink import ContractAwareEventSink


class ContractHealthEvaluator:
    """Pure evaluator: violation signals → health assessment.

    Usage:
        evaluator = ContractHealthEvaluator()
        report = evaluator.evaluate(sink)
        # ... time passes, more composition runs ...
        next_report = evaluator.evaluate(sink, previous=report)
        # next_report.trend → 'improving' | 'stable' | 'deteriorating'
    """

    def __init__(
        self, severity_mapping: SeverityMapping | None = None
    ) -> None:
        self._mapping = severity_mapping if severity_mapping is not None else (
            SeverityMapping.default()
        )

    def evaluate(
        self,
        sink: ContractAwareEventSink,
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
        violation_total = summary["violation_count"]

        # Compliance rate: fraction of documents without violations
        if total_docs == 0:
            compliance_rate = 1.0
        else:
            docs_with_violations = self._estimate_docs_with_violations(sink)
            compliance_rate = (total_docs - docs_with_violations) / total_docs
            compliance_rate = max(0.0, min(1.0, compliance_rate))

        # Determine severity via injectable mapping
        severity = self._compute_severity(violations_by_cat)

        # Dominant violation type
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
            evaluated_at=time.time(),
        )

    # ── Internal (pure, testable) ────────────────────────────────

    def _compute_severity(
        self, violations_by_cat: dict
    ) -> ContractHealthReport.__dataclass_fields__:
        # Return type is Literal["healthy", "degraded", "critical"]
        result: str = "healthy"
        for rule in self._mapping.rules:
            count = violations_by_cat.get(rule.violation_type, 0)
            if count >= rule.count_threshold:
                if rule.severity == "critical":
                    return "critical"
                if rule.severity == "degraded":
                    result = "degraded"
        return result  # type: ignore[return-value]

    @staticmethod
    def _dominant_violation(violations_by_cat: dict) -> str | None:
        """Return the most frequent violation type, or None if no violations."""
        if not violations_by_cat:
            return None
        return max(violations_by_cat, key=lambda k: violations_by_cat[k])

    @staticmethod
    def _estimate_docs_with_violations(
        sink: ContractAwareEventSink,
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
