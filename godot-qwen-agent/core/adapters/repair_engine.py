"""Self-Repair Engine — Phase 22b.

Consumes ContractHealthReport → decides repair actions → executes repairs
→ records outcomes → closes the loop back into EventSink.

This is where Phase 19-21's "passive cognition" becomes "active response."
HealthEvaluator knows the system is hurting; SelfRepairEngine stops the bleeding.

Design:
  - Pure function: decide(report, sink) → list of RepairAction
  - RepairBudget: max attempts per violation type, prevents infinite loops
  - Budget exhausted → emits repair_budget_exhausted event → EventSink
  - All repair outcomes flow back into EventSink for re-evaluation
  - Grammar engine (like HealthEvaluator) — lives in adapters/, reads
    contracts, produces decisions

Repair strategies (Phase 22b minimal):
  - routing_contract_breach → retry with default_chunker
  - unknown_chunker_strategy → use default_chunker instead
  - invalid_chunk_params → retry with default_params
  - output_contract_violation → retry once (may be transient)
  - tool_not_found → suggest alternative from Registry
  - tool_param_mismatch → retry with corrected params (future)

Future Phase 25+:
  - severity=critical + trend=deteriorating → escalate_to_human
  - Multiple failed repairs → initiate renegotiate
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.contracts.composition import (
    CompositionBlueprint,
    ContractHealthReport,
    ContractViolation,
)
from core.adapters.event_sink import ContractAwareEventSink


# ── Repair Action ─────────────────────────────────────────────────────

class RepairStrategy(str, Enum):
    """Available repair strategies, ordered by escalation."""
    RETRY_WITH_DEFAULT = "retry_with_default"
    REPLACE_COMPONENT = "replace_component"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    GIVE_UP = "give_up"


@dataclass(frozen=True)
class RepairAction:
    """A single repair decision produced by SelfRepairEngine.

    Attributes:
        violation_type:   Which contract violation triggered this
        strategy:         Chosen repair strategy
        target_component: Which component to repair (chunker name, tool name, etc.)
        replacement:      If REPLACE_COMPONENT, the suggested replacement name
        reason:           Human-readable explanation of the decision
        timestamp:        epoch seconds
    """

    violation_type: str
    strategy: RepairStrategy
    target_component: str = ""
    replacement: str | None = None
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


# ── Repair Budget ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class RepairBudget:
    """Limits repair attempts to prevent infinite loops.

    Each violation type has its own budget. When a budget is exhausted,
    the engine emits a repair_budget_exhausted event — "admitting inability"
    becomes a first-class contract signal.

    Attributes:
        max_total:       Maximum total repair attempts across all types
        max_per_type:    Maximum attempts per violation type
        attempts_used:   {violation_type: count} tracking
    """

    max_total: int = 5
    max_per_type: int = 2
    attempts_used: Dict[str, int] = field(default_factory=dict)

    def can_repair(self, violation_type: str) -> bool:
        """Check if there's budget remaining for this violation type."""
        total_used = sum(self.attempts_used.values())
        if total_used >= self.max_total:
            return False
        type_used = self.attempts_used.get(violation_type, 0)
        if type_used >= self.max_per_type:
            return False
        return True

    def consume(self, violation_type: str) -> RepairBudget:
        """Return a new RepairBudget with one attempt consumed."""
        new_used = dict(self.attempts_used)
        new_used[violation_type] = new_used.get(violation_type, 0) + 1
        return RepairBudget(
            max_total=self.max_total,
            max_per_type=self.max_per_type,
            attempts_used=new_used,
        )

    @property
    def total_used(self) -> int:
        return sum(self.attempts_used.values())

    @property
    def is_exhausted(self) -> bool:
        return self.total_used >= self.max_total


# ── Self-Repair Engine ────────────────────────────────────────────────

class SelfRepairEngine:
    """Pure decision engine: health report → repair actions.

    Usage:
        engine = SelfRepairEngine(blueprint, event_sink=sink)
        report = health_evaluator.evaluate(sink)
        actions = engine.decide(report, sink)
        results = engine.execute_all(actions)
        # results flow back into sink → re-evaluate health
    """

    # Phase 22b: default repair strategy per violation type
    _DEFAULT_STRATEGIES: Dict[str, RepairStrategy] = {
        ContractViolation.UNKNOWN_CHUNKER_STRATEGY: RepairStrategy.REPLACE_COMPONENT,
        ContractViolation.INVALID_CHUNK_PARAMS: RepairStrategy.RETRY_WITH_DEFAULT,
        ContractViolation.ROUTING_CONTRACT_BREACH: RepairStrategy.RETRY_WITH_DEFAULT,
        ContractViolation.OUTPUT_CONTRACT_VIOLATION: RepairStrategy.RETRY_WITH_DEFAULT,
        ContractViolation.TOOL_NOT_FOUND: RepairStrategy.REPLACE_COMPONENT,
        ContractViolation.TOOL_PARAM_MISMATCH: RepairStrategy.RETRY_WITH_DEFAULT,
    }

    def __init__(
        self,
        blueprint: CompositionBlueprint,
        event_sink: Callable | None = None,
        budget: RepairBudget | None = None,
    ) -> None:
        self._blueprint = blueprint
        self._emit = event_sink if event_sink is not None else (lambda _e: None)
        self._budget = budget if budget is not None else RepairBudget()

    # ── Decision ──────────────────────────────────────────────────

    def decide(
        self,
        report: ContractHealthReport,
        sink: ContractAwareEventSink,
    ) -> List[RepairAction]:
        """Decide repair actions based on health report.

        Only acts when severity is degraded or critical. Healthy reports
        produce no actions — the system is fine.

        Args:
            report: Health assessment from ContractHealthEvaluator
            sink:   Current event state for context

        Returns:
            List of RepairAction decisions (empty if healthy or budget exhausted).
        """
        if report.severity == "healthy":
            return []

        if self._budget.is_exhausted:
            return []

        actions: List[RepairAction] = []

        for violation_type, count in report.violation_counts.items():
            if count == 0:
                continue
            if not self._budget.can_repair(violation_type):
                continue

            strategy = self._DEFAULT_STRATEGIES.get(
                violation_type, RepairStrategy.ESCALATE_TO_HUMAN
            )

            action = RepairAction(
                violation_type=violation_type,
                strategy=strategy,
                target_component=self._infer_component(violation_type),
                replacement=self._find_replacement(violation_type, strategy),
                reason=self._build_reason(violation_type, count, strategy),
            )
            actions.append(action)
            self._budget = self._budget.consume(violation_type)

        # If budget exhausted during this decide call, emit event
        if self._budget.is_exhausted:
            self._emit_budget_exhausted(report)

        return actions

    # ── Execution ─────────────────────────────────────────────────

    def execute_all(
        self, actions: List[RepairAction]
    ) -> List[Dict[str, Any]]:
        """Execute repair actions and return outcomes.

        Each outcome is a dict describing what happened — these flow back
        into the event sink for re-evaluation by HealthEvaluator.

        Phase 22b: actions are logged but actual re-execution is orchestrated
        by the caller (PipelineComposer). This method returns the action plan;
        the caller applies it.
        """
        results = []
        for action in actions:
            result = {
                "action": action.strategy.value,
                "violation": action.violation_type,
                "target": action.target_component,
                "replacement": action.replacement,
                "timestamp": time.time(),
                "applied": action.strategy != RepairStrategy.GIVE_UP,
            }
            results.append(result)
            self._emit_repair_attempt(action, result)

        return results

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _infer_component(violation_type: str) -> str:
        """Infer which component type is affected by this violation."""
        if "chunker" in violation_type or "routing" in violation_type:
            return "chunker"
        if "tool" in violation_type:
            return "tool"
        return "unknown"

    def _find_replacement(
        self, violation_type: str, strategy: RepairStrategy
    ) -> str | None:
        """Find a replacement component from the Registry.

        For REPLACE_COMPONENT strategy: queries COMPONENT_REGISTRY for
        alternative implementations of the same component type.

        Phase 22b minimal: returns the default fallback.
        Phase 22d (MCP): will scan Registry for compatible alternatives.
        """
        if strategy != RepairStrategy.REPLACE_COMPONENT:
            return None

        component_type = self._infer_component(violation_type)
        if component_type == "chunker":
            return self._blueprint.default_chunker
        if component_type == "tool":
            # Scan Registry for any registered tool
            from core.contracts import COMPONENT_REGISTRY
            strategies = COMPONENT_REGISTRY.list_strategies("tool")
            if strategies:
                return strategies[0]  # first available alternative
        return None

    @staticmethod
    def _build_reason(
        violation_type: str, count: int, strategy: RepairStrategy
    ) -> str:
        """Build a human-readable reason for the repair decision."""
        return (
            f"{violation_type} occurred {count} time(s). "
            f"Strategy: {strategy.value}."
        )

    # ── Event emission ────────────────────────────────────────────

    def _emit_budget_exhausted(
        self, report: ContractHealthReport
    ) -> None:
        """Emit repair_budget_exhausted event — 'I cannot fix this.'"""
        from core.contracts.composition import CompositionEvent

        self._emit(CompositionEvent(
            event_type="repair_budget_exhausted",
            correlation_id="repair_engine",
            timestamp=time.time(),
            context={
                "total_attempts": self._budget.total_used,
                "max_total": self._budget.max_total,
                "severity_at_exhaustion": report.severity,
                "dominant_violation": report.dominant_violation_type,
                "message": (
                    "SelfRepairEngine has exhausted its repair budget. "
                    "Escalating to human or abandoning repair."
                ),
            },
        ))

    def _emit_repair_attempt(
        self, action: RepairAction, result: Dict[str, Any]
    ) -> None:
        """Emit repair_attempted event for audit trail."""
        from core.contracts.composition import CompositionEvent

        self._emit(CompositionEvent(
            event_type="repair_attempted",
            correlation_id="repair_engine",
            timestamp=time.time(),
            context={
                "violation_type": action.violation_type,
                "strategy": action.strategy.value,
                "target": action.target_component,
                "replacement": action.replacement,
                "applied": result["applied"],
                "budget_remaining": (
                    self._budget.max_total - self._budget.total_used
                ),
            },
        ))

    # ── Properties ────────────────────────────────────────────────

    @property
    def budget(self) -> RepairBudget:
        return self._budget
