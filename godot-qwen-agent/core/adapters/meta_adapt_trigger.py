"""MetaAdaptTrigger — dimension-lifting trigger with annealing protection.

When tracking error e(t) persistently exceeds threshold, the current
constraint manifold cannot converge to the moving target. The system
must relax its selection threshold (meta-adaptation Type I: defensive).

Engineering: Structure-Preserving Model Reduction (Patch 3).
Floor clipping prevents "brain death" (threshold → 0).
Cooldown prevents high-frequency chatter at the critical boundary.
Hysteresis prevents oscillation between relaxed and normal states.

Mathematical basis (Research 4):
  e(t) > e_crit for N consecutive rounds → meta-adaptation triggered
  MIN_THRESHOLD guarantees global boundedness of the joint Lyapunov function
  COOLDOWN prevents chattering near the stability boundary
"""

from __future__ import annotations

from collections import deque
from typing import Optional

# ── Guardrails ────────────────────────────────────────────────────────
MIN_THRESHOLD = 0.30       # Absolute floor: below this, system refuses service
DEFAULT_THRESHOLD = 0.65   # Default selection threshold
COOLDOWN_ROUNDS = 10       # Rounds to wait after each relaxation
PERSISTENCE_ROUNDS = 5     # Consecutive rounds of high error to trigger
ERROR_THRESHOLD = 0.70     # e(t) above this is considered "high"
RECOVERY_RATIO = 0.5       # Error must drop below threshold * this to recover
RECOVERY_RATE = 1.05       # Threshold recovery multiplier per round
RELAXATION_RATE = 0.85     # How much to multiply threshold when relaxing


class MetaAdaptTrigger:
    """Detects persistent tracking error and triggers threshold relaxation.

    Usage:
        trigger = MetaAdaptTrigger()
        # Each round:
        new_threshold = trigger.maybe_relax(
            tracking_error,
            current_threshold,
        )
    """

    def __init__(
        self,
        error_threshold: float = ERROR_THRESHOLD,
        persistence: int = PERSISTENCE_ROUNDS,
        cooldown: int = COOLDOWN_ROUNDS,
        min_threshold: float = MIN_THRESHOLD,
        default_threshold: float = DEFAULT_THRESHOLD,
        relaxation_rate: float = RELAXATION_RATE,
        recovery_rate: float = RECOVERY_RATE,
        recovery_ratio: float = RECOVERY_RATIO,
    ) -> None:
        self.error_threshold = error_threshold
        self.persistence = persistence
        self.cooldown_rounds = cooldown
        self.min_threshold = min_threshold
        self.default_threshold = default_threshold
        self.relaxation_rate = relaxation_rate
        self.recovery_rate = recovery_rate
        self.recovery_ratio = recovery_ratio

        # Internal state
        self._error_history: deque[float] = deque(maxlen=persistence)
        self._cooldown_remaining: int = 0
        self._trigger_count: int = 0
        self._relaxed: bool = False

    # ── Public API ──────────────────────────────────────────────────

    def maybe_relax(
        self,
        tracking_error: float,
        current_threshold: float,
    ) -> tuple[float, str]:
        """Called each round. Returns (new_threshold, action_description).

        Actions: "hold", "relax", "recover", "cooldown", "floor"
        """
        self._error_history.append(tracking_error)

        # ── Cooling down ──
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return current_threshold, "cooldown"

        # ── Check trigger condition ──
        if self._should_trigger():
            self._cooldown_remaining = self.cooldown_rounds
            self._trigger_count += 1
            self._relaxed = True
            new_threshold = max(
                current_threshold * self.relaxation_rate,
                self.min_threshold,
            )
            if new_threshold <= self.min_threshold:
                return new_threshold, "floor"
            return new_threshold, "relax"

        # ── Recovery: error has dropped, slowly restore threshold ──
        if self._relaxed and tracking_error < self.error_threshold * self.recovery_ratio:
            new_threshold = min(
                current_threshold * self.recovery_rate,
                self.default_threshold,
            )
            if new_threshold >= self.default_threshold:
                self._relaxed = False
                return new_threshold, "recovered"
            return new_threshold, "recover"

        # ── Hold ──
        return current_threshold, "hold"

    def _should_trigger(self) -> bool:
        """True if last N error readings all exceed threshold."""
        if len(self._error_history) < self.persistence:
            return False
        return all(e > self.error_threshold for e in self._error_history)

    # ── Query ──────────────────────────────────────────────────────

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    @property
    def is_relaxed(self) -> bool:
        return self._relaxed

    @property
    def cooldown_remaining(self) -> int:
        return self._cooldown_remaining

    def reset(self) -> None:
        """Full reset (e.g., on /reset command)."""
        self._error_history.clear()
        self._cooldown_remaining = 0
        self._trigger_count = 0
        self._relaxed = False

    def snapshot(self) -> dict:
        """Serializable state for cross-session persistence."""
        return {
            "trigger_count": self._trigger_count,
            "relaxed": self._relaxed,
            "cooldown_remaining": self._cooldown_remaining,
            "error_history": list(self._error_history),
        }
