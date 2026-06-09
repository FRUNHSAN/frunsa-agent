"""V7.1 DualTrackCritic — multiplicative gating of semantic + physical signals.

Defensive Axiom C (Intent-Driven Contract Override):
  physical check is skipped for PSEUDOCODE / DEMONSTRATION / DESTRUCTIVE_TEST.

Multiplicative gating (not veto):
  Final_Pass = (θ_semantic > threshold) AND (q_physical != FAIL_FATAL)
  FAIL_RETRYABLE → allow semantic judgment for retry
  FAIL_FATAL → Rigid Contract #5, unconditional rejection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.execution.sandbox import PhysicalState


class CriticVerdict(Enum):
    PASS = "PASS"              # Both semantic and physical OK
    RETRY = "RETRY"            # Physical fail retryable → retry with fix_hint
    FAIL_FATAL = "FAIL_FATAL"  # Rigid Contract #5 → unconditional abort


@dataclass
class CriticDecision:
    """Structured output from DualTrackCritic."""
    verdict: CriticVerdict
    semantic_score: float
    physical_state: PhysicalState | None = None  # None if no physical execution
    fix_hint: str = ""                           # From ErrorMapper, for retry
    reason: str = ""


class DualTrackCritic:
    """Multiplicative gating of semantic (θ) and physical (q) signals.

    Usage:
        critic = DualTrackCritic()
        decision = critic.evaluate(
            semantic_score=0.80,
            theta=0.70,
            physical_result=exec_result,
            intent_type="EXECUTABLE",
        )
        if decision.verdict == CriticVerdict.RETRY:
            # inject decision.fix_hint into Planning
    """

    # ── Public API ──────────────────────────────────────────────────

    def evaluate(
        self,
        semantic_score: float,
        theta: float,
        physical_result=None,  # ExecutionResult | None
        intent_type: str = "EXECUTABLE",
        fix_hint: str = "",
    ) -> CriticDecision:
        """Evaluate combined semantic + physical signal.

        Args:
            semantic_score: LLM Critic score (0-1).
            theta: Current Critic threshold from V5.3/V6.2/V6.3.
            physical_result: ExecutionResult from SandboxExecutor, or None.
            intent_type: EXECUTABLE / PSEUDOCODE / DEMONSTRATION / DESTRUCTIVE_TEST.
            fix_hint: ErrorMapper fix_hint for retry.

        Returns:
            CriticDecision with verdict and diagnostics.
        """
        # ── Semantic check ──
        semantic_pass = semantic_score >= theta

        # ── Physical check (Defensive Axiom C: intent-driven override) ──
        if physical_result is None or not self._needs_physical(intent_type):
            # No physical execution or exempted by intent_type
            if semantic_pass:
                return CriticDecision(
                    verdict=CriticVerdict.PASS,
                    semantic_score=semantic_score,
                    reason="semantic pass (no physical check)",
                )
            else:
                return CriticDecision(
                    verdict=CriticVerdict.RETRY,
                    semantic_score=semantic_score,
                    reason=f"semantic fail: {semantic_score:.2f} < {theta:.2f}",
                )

        q = physical_result.state

        # ── Rigid Contract #5: FAIL_FATAL → unconditional abort ──
        if q.is_fatal():
            return CriticDecision(
                verdict=CriticVerdict.FAIL_FATAL,
                semantic_score=semantic_score,
                physical_state=q,
                reason=f"Rigid Contract #5: {q.value}",
            )

        # ── FAIL_RETRYABLE: physical says no, semantic may override ──
        if q.is_retryable():
            if semantic_pass and intent_type in ("PSEUDOCODE", "DEMONSTRATION"):
                # Intent override: user wanted pseudo/demo, physical fail is expected
                return CriticDecision(
                    verdict=CriticVerdict.PASS,
                    semantic_score=semantic_score,
                    physical_state=q,
                    reason=f"intent_type={intent_type} overrides {q.value}",
                )
            # Retry with fix_hint
            return CriticDecision(
                verdict=CriticVerdict.RETRY,
                semantic_score=semantic_score,
                physical_state=q,
                fix_hint=fix_hint,
                reason=f"physical retryable: {q.value}" + (
                    f" (semantic pass, retrying)" if semantic_pass
                    else f" (semantic fail: {semantic_score:.2f} < {theta:.2f})"
                ),
            )

        # ── q == PASS ──
        if semantic_pass:
            return CriticDecision(
                verdict=CriticVerdict.PASS,
                semantic_score=semantic_score,
                physical_state=q,
                reason="semantic + physical pass",
            )
        else:
            return CriticDecision(
                verdict=CriticVerdict.RETRY,
                semantic_score=semantic_score,
                physical_state=q,
                reason=f"semantic fail (physical OK): {semantic_score:.2f} < {theta:.2f}",
            )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _needs_physical(intent_type: str) -> bool:
        """Physical check only applies to EXECUTABLE steps."""
        return intent_type == "EXECUTABLE"


# ── Physical Budget Tracker ───────────────────────────────────────────


class PhysicalBudget:
    """V7.2: Weighted budget tracker for physical executions per Track C cycle.

    Costs weighted by compute time (Patch C):
      AST (Layer 1):      0.0  free, always runs
      Mypy (Layer 2):     0.1  micro-cost, skipped if budget tight
      Sandbox (Layer 3):  1.0  full cost, Fail-Safe guarantees at least 1.0 reserve
    """

    def __init__(self, max_budget: float = 5.0):
        self._max = float(max_budget)
        self._spent: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self._max - self._spent)

    @property
    def is_exhausted(self) -> bool:
        return self._spent >= self._max

    def spend(self, amount: float = 1.0) -> bool:
        """Spend budget units. Returns True if budget was available."""
        if self._spent + amount > self._max + 1e-9:
            return False
        self._spent += amount
        return True

    def reset(self) -> None:
        self._spent = 0

    def warn_if_exhausted(self) -> str:
        """X-Ray telemetry message."""
        if self.is_exhausted:
            return f"[WARN] physical budget exhausted ({self._spent}/{self._max})"
        return ""
