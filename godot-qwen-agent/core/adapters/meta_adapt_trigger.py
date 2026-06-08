"""MetaAdaptTrigger — dimension-lifting trigger with annealing protection.

Two independent trigger paths (V5 perception-action loop):
  Path 1 — Tracking Error: e(t) > e_crit for N consecutive rounds
           → the current strategy is failing in a known environment.
  Path 2 — Selection Pressure: trust_variance > μ + 2σ
           → the environment exceeds the current model's capacity.

Safety constraints (V5 Phase 2):
  Hard floor: threshold ≥ MIN_THRESHOLD (prevents random-selection "brain death")
  EMA recovery: recovery uses EMA not multiplication (rate < relaxation rate)
  Escalation: >3 Path 2 triggers per session → structural meta-adapt required
  Cognition: Path 2 triggers expose a "cognitive honesty marker" to the user

Mathematical basis (Research 4):
  Path 1: e(t) > e_crit for N consecutive rounds
  Path 2: σ² > μ + 2δ → environment unpredictable → widen search aperture
  Joint Lyapunov boundedness via MIN_THRESHOLD + EMA recovery
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
RELAXATION_RATE = 0.85     # How much to multiply threshold when relaxing

# ── EMA Recovery (replaces simple *= RECOVERY_RATE) ──────────────────
RECOVERY_ALPHA = 0.05      # EMA α for threshold recovery (0.05 < 0.15 decay)

# ── Path 2: Selection Pressure ──────────────────────────────────────
PRESSURE_WINDOW = 20       # Rounds of variance history for dynamic threshold
PRESSURE_SIGMA = 2.0       # Number of std deviations above mean to trigger
PRESSURE_ESCALATE = 3      # Path 2 triggers in one session → escalate

# ── Cognition ─────────────────────────────────────────────────────────
COGNITION_EXPLORING = (
    "[exploring: high uncertainty detected, broadening search space]"
)


class MetaAdaptTrigger:
    """Dual-path meta-adaptation trigger with annealing + escalation.

    Usage:
        trigger = MetaAdaptTrigger()
        # Each round:
        new_threshold, action = trigger.maybe_relax(e_t, current_threshold)
        if trigger.cognition:
            response += " " + trigger.cognition  # inject into reply
    """

    def __init__(
        self,
        error_threshold: float = ERROR_THRESHOLD,
        persistence: int = PERSISTENCE_ROUNDS,
        cooldown: int = COOLDOWN_ROUNDS,
        min_threshold: float = MIN_THRESHOLD,
        default_threshold: float = DEFAULT_THRESHOLD,
        relaxation_rate: float = RELAXATION_RATE,
        recovery_alpha: float = RECOVERY_ALPHA,
        recovery_ratio: float = RECOVERY_RATIO,
        pressure_escalate: int = PRESSURE_ESCALATE,
    ) -> None:
        self.error_threshold = error_threshold
        self.persistence = persistence
        self.cooldown_rounds = cooldown
        self.min_threshold = min_threshold
        self.default_threshold = default_threshold
        self.relaxation_rate = relaxation_rate
        self.recovery_alpha = recovery_alpha
        self.recovery_ratio = recovery_ratio
        self.pressure_escalate = pressure_escalate

        # Internal state
        self._error_history: deque[float] = deque(maxlen=persistence)
        self._cooldown_remaining: int = 0
        self._trigger_count: int = 0
        self._relaxed: bool = False

        # ── Path 2: Selection Pressure ──
        self._pressure_history: deque[float] = deque(maxlen=PRESSURE_WINDOW)
        self._pressure_sigma: float = PRESSURE_SIGMA
        self._pressure_triggered: bool = False
        self._pressure_trigger_count: int = 0       # Session counter
        self._pressure_consecutive: int = 0          # Consecutive counter
        self._escalated: bool = False               # Threshold exhausted

        # ── Cognition marker ──
        self._cognition: str = ""

    # ═══════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════

    def maybe_relax(
        self,
        tracking_error: float,
        current_threshold: float,
    ) -> tuple[float, str]:
        """Called each round. Returns (new_threshold, action_description).

        Actions: "hold", "relax", "recover", "recovered", "cooldown",
                 "floor", "escalate"
        """
        self._error_history.append(tracking_error)
        self._cognition = ""  # Reset each round

        # ── Escalation: Path 2 exhausted local adaptation ──
        if self._escalated:
            return current_threshold, "escalate"

        # ── Cooling down ──
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return current_threshold, "cooldown"

        # ── Check trigger condition ──
        if self._should_trigger():
            self._cooldown_remaining = self.cooldown_rounds
            self._trigger_count += 1
            self._relaxed = True

            # Path 2 tracking
            if self._pressure_consecutive > 0:
                self._pressure_trigger_count += 1
                self._cognition = COGNITION_EXPLORING
                # >3 Path 2 triggers → escalate
                if self._pressure_trigger_count >= self.pressure_escalate:
                    self._escalated = True
                    return current_threshold, "escalate"
                self._pressure_consecutive = 0

            new_threshold = max(
                current_threshold * self.relaxation_rate,
                self.min_threshold,
            )
            if new_threshold <= self.min_threshold:
                return new_threshold, "floor"
            return new_threshold, "relax"

        # ── Recovery: error has dropped, EMA-restore threshold ──
        if self._relaxed and tracking_error < self.error_threshold * self.recovery_ratio:
            # EMA: threshold = (1-α)·threshold + α·default
            # Recovery rate (α=0.05) < decay rate (1-0.85=0.15) → no oscillation
            new_threshold = (
                (1.0 - self.recovery_alpha) * current_threshold
                + self.recovery_alpha * self.default_threshold
            )
            if new_threshold >= self.default_threshold * 0.98:
                self._relaxed = False
                self._pressure_trigger_count = 0  # Reset counter on full recovery
                return self.default_threshold, "recovered"
            return new_threshold, "recover"

        # ── Hold ──
        return current_threshold, "hold"

    # ═══════════════════════════════════════════════════════════════════
    # Path 2: Selection Pressure
    # ═══════════════════════════════════════════════════════════════════

    def feed_pressure(self, trust_variance: float) -> tuple[bool, float]:
        """Feed trust variance from SelectionPressureAccumulator.

        Returns (pressure_triggered, dynamic_threshold).
        Tracks consecutive triggers for escalation detection.
        """
        self._pressure_history.append(trust_variance)

        if len(self._pressure_history) < 4:
            return False, 1.0

        import statistics
        mu = statistics.mean(self._pressure_history)
        sigma = (
            statistics.stdev(self._pressure_history)
            if len(self._pressure_history) >= 2 else 0.0
        )
        dynamic_threshold = mu + self._pressure_sigma * sigma

        self._pressure_triggered = trust_variance > dynamic_threshold
        if self._pressure_triggered:
            self._pressure_consecutive += 1
        else:
            self._pressure_consecutive = 0

        return self._pressure_triggered, dynamic_threshold

    # ═══════════════════════════════════════════════════════════════════
    # Query
    # ═══════════════════════════════════════════════════════════════════

    @property
    def pressure_triggered(self) -> bool:
        return self._pressure_triggered

    @property
    def pressure_trigger_count(self) -> int:
        return self._pressure_trigger_count

    @property
    def escalated(self) -> bool:
        return self._escalated

    @property
    def cognition(self) -> str:
        """Cognitive honesty marker. Non-empty when Path 2 triggered."""
        return self._cognition

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    @property
    def is_relaxed(self) -> bool:
        return self._relaxed

    @property
    def cooldown_remaining(self) -> int:
        return self._cooldown_remaining

    # ═══════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════

    def reset(self) -> None:
        """Full reset (e.g., on /reset command)."""
        self._error_history.clear()
        self._pressure_history.clear()
        self._cooldown_remaining = 0
        self._trigger_count = 0
        self._relaxed = False
        self._pressure_triggered = False
        self._pressure_trigger_count = 0
        self._pressure_consecutive = 0
        self._escalated = False
        self._cognition = ""

    def snapshot(self) -> dict:
        """Serializable state for cross-session persistence."""
        return {
            "trigger_count": self._trigger_count,
            "relaxed": self._relaxed,
            "cooldown_remaining": self._cooldown_remaining,
            "error_history": list(self._error_history),
            "pressure_triggered": self._pressure_triggered,
            "pressure_trigger_count": self._pressure_trigger_count,
            "escalated": self._escalated,
        }

    def _should_trigger(self) -> bool:
        """True if Path 1 (tracking error) OR Path 2 (pressure spike)."""
        # Path 1: tracking error persistence
        if len(self._error_history) >= self.persistence:
            if all(e > self.error_threshold for e in self._error_history):
                return True
        # Path 2: selection pressure spike
        if self._pressure_triggered:
            boosted = min(1.0, self.error_threshold + 0.05)
            self._error_history.append(boosted)
            self._pressure_triggered = False
            if len(self._error_history) >= self.persistence:
                return all(e > self.error_threshold for e in self._error_history)
        return False
