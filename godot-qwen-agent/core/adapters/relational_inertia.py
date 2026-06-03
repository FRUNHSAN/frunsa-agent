"""Relational Inertia — PLAN3/4 smoothing engine.

Prevents context oscillation by applying momentum, friction, and
temporal decay to relational state transitions. Human relationships
don't snap between states — they breathe.

Design (PLAN4-ready):
  - EMA (Exponential Moving Average) for slow-changing dimensions (trust)
  - Consecutive-read gating for categorical transitions (energy)
  - Sliding window for historical resonance
  - All in pure Python — no PyTorch, no heavy dependencies
  - Interface ready for future tensor-based upgrade (PLAN4)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List


@dataclass
class InertiaConfig:
    """Tunable parameters for relational smoothing.

    Calibrated from blind test data (2026-05-29).
    """

    # EMA alpha for trust (0.0 = no update, 1.0 = instant)
    trust_alpha: float = 0.3

    # Consecutive readings required before energy level change
    energy_confirm_window: int = 2

    # Window size for historical resonance detection
    history_window: int = 10

    # Tone damping: maximum change per round (0.0 = frozen, 1.0 = instant)
    tone_damping: float = 0.5

    # How quickly urgency decays after a critical signal (rounds)
    urgency_decay_rounds: int = 3

    # Smart Decay: exponential variance reduction when no surprise (PLAN4)
    # gamma=0.85 means each calm round shrinks variance by 15%
    variance_decay_gamma: float = 0.85


@dataclass
class RelationalHistory:
    """Sliding window of recent relational states.

    Maintains a deque of (energy, urgency, trust, tone) tuples
    for temporal analysis and smoothing.
    """

    config: InertiaConfig = field(default_factory=InertiaConfig)
    _energy_history: Deque[str] = field(default_factory=deque)
    _urgency_history: Deque[str] = field(default_factory=deque)
    _trust_ema: float = 0.5
    _tone_history: Deque[str] = field(default_factory=deque)
    _round_count: int = 0
    _urgency_rounds_since_critical: int = 999

    # Bayesian uncertainty tracking (PLAN4)
    _means: dict[str, float] = field(default_factory=lambda: {
        "trust": 0.5, "energy_strength": 0.5,
    })
    _variances: dict[str, float] = field(default_factory=lambda: {
        "trust": 0.25, "energy_strength": 0.25,
    })
    _alpha: float = 0.2   # Mean smoothing coefficient (base)
    _beta: float = 0.1    # Variance smoothing coefficient

    # P1 Psychology: asymmetric trust dynamics
    _alpha_negative: float = 0.30  # Trust erodes fast (negativity bias)
    _alpha_positive: float = 0.08  # Trust builds slow (requires repeated evidence)
    _peace_streak: int = 0         # Consecutive rounds without surprise
    _peace_threshold: int = 5      # Rounds before baseline drift activates
    _drift_rate: float = 0.01      # Trust per round during peace
    _drift_target: float = 0.3     # Trust naturally drifts toward this baseline

    def record(
        self, energy: str, urgency: str, trust: float, tone: str,
    ) -> None:
        """Record a round's raw state before smoothing."""
        self._round_count += 1

        # Maintain sliding windows
        maxlen = self.config.history_window
        if len(self._energy_history) >= maxlen:
            self._energy_history.popleft()
            self._urgency_history.popleft()
            self._tone_history.popleft()
        self._energy_history.append(energy)
        self._urgency_history.append(urgency)
        self._tone_history.append(tone)

        # EMA for trust
        self._trust_ema = (
            self.config.trust_alpha * trust
            + (1 - self.config.trust_alpha) * self._trust_ema
        )

        # Urgency decay counter
        if urgency == "critical":
            self._urgency_rounds_since_critical = 0
        else:
            self._urgency_rounds_since_critical += 1

    def smooth_energy(self, raw_energy: str) -> str:
        """Energy transitions require consecutive confirmation.

        Cannot snap from HIGH to LOW in one round. Requires
        energy_confirm_window consecutive readings of the new level.
        """
        if len(self._energy_history) < self.config.energy_confirm_window:
            return raw_energy

        recent = list(self._energy_history)[-self.config.energy_confirm_window:]
        if all(e == raw_energy for e in recent):
            return raw_energy
        # Not enough confirmation — return previous level
        return self._energy_history[-self.config.energy_confirm_window]

    def smooth_urgency(self, raw_urgency: str) -> str:
        """Urgency is immediate on the way up, decays slowly on the way down.

        Critical signals are trusted instantly. But after a critical
        signal, urgency decays over urgency_decay_rounds rather than
        snapping back to normal.
        """
        if raw_urgency == "critical":
            return "critical"

        # Decay: if we were recently critical, maintain elevated urgency
        if self._urgency_rounds_since_critical <= self.config.urgency_decay_rounds:
            return "normal"  # still elevated, but not critical

        return raw_urgency

    def smooth_trust(self, raw_trust: float) -> float:
        """Trust uses EMA — slow to build, resistant to erosion."""
        return round(self._trust_ema, 4)

    def smooth_tone(self, raw_tone: str) -> str:
        """Tone changes are damped — no flipping from brief to detailed.

        Returns a tone that's at most one step away from the previous tone.
        """
        if not self._tone_history:
            return raw_tone

        prev = self._tone_history[-1]
        if prev == raw_tone:
            return raw_tone

        # Allowed transitions (one step):
        transitions = {
            "brief": ["neutral"],
            "neutral": ["brief", "detailed"],
            "detailed": ["neutral", "urgent"],
            "urgent": ["detailed"],
        }
        if raw_tone in transitions.get(prev, [raw_tone]):
            return raw_tone
        # Too big a jump — stay at previous
        return prev

    def smooth(
        self, raw_energy: str, raw_urgency: str,
        raw_trust: float, raw_tone: str,
    ) -> tuple[str, str, float, str]:
        """Apply full inertia smoothing to raw state readings.

        Returns (energy, urgency, trust, tone) — all smoothed.
        """
        energy = self.smooth_energy(raw_energy)
        urgency = self.smooth_urgency(raw_urgency)
        trust = self.smooth_trust(raw_trust)
        tone = self.smooth_tone(raw_tone)
        return energy, urgency, trust, tone

    # ── Bayesian Uncertainty Tracking (PLAN4) ────────────────

    def decay_variances(self, surprise_score: float = 0.0) -> None:
        """Apply exponential decay to all dimension variances when calm.

        If no surprise detected (score < 0.3), each round naturally
        reduces uncertainty. This prevents 'stuck PTSD' where variance
        stays elevated long after the threat has passed.

        Called before bayesian_update/update_with_surprise.
        """
        if surprise_score >= 0.3:
            return  # Threat present — don't decay

        gamma = self.config.variance_decay_gamma
        for dim in self._variances:
            self._variances[dim] *= gamma
            self._variances[dim] = max(0.01, self._variances[dim])

    def bayesian_update(self, dim: str, observed: float) -> tuple[float, float]:
        """Bayesian EMA: update mean AND variance for a dimension.

        Returns (mean, variance) after update.
        """
        return self._update_internal(dim, observed, surprise_score=0.0)

    def update_with_surprise(
        self, dim: str, observed: float, surprise_score: float = 0.0,
    ) -> tuple[float, float]:
        """Bayesian EMA with behavioral surprise injection (PLAN4).

        When surprise_score > 0, the augmented error forcibly expands
        variance — preventing the 'confirmation bias' trap where low
        variance makes the system blind to behavioral mutations.

        Args:
            dim: dimension name ("energy_strength", "trust")
            observed: current observed value
            surprise_score: 0.0 (no surprise) to 1.0 (extreme anomaly)

        Returns:
            (mean, variance) after update
        """
        return self._update_internal(dim, observed, surprise_score)

    def _update_internal(
        self, dim: str, observed: float, surprise_score: float,
    ) -> tuple[float, float]:
        """Core Bayesian EMA update with optional surprise augmentation.

        P1 Psychology: asymmetric EMA for trust dimension.
        Negative signals (observed < current) erode trust fast (alpha=0.30).
        Positive signals (observed > current) build trust slow (alpha=0.08).
        Matches human negativity bias — one insult costs 4 compliments.
        """
        old_mean = self._means[dim]
        old_var = self._variances[dim]

        # P1: asymmetric alpha for trust
        if dim == "trust":
            alpha = self._alpha_negative if observed < old_mean else self._alpha_positive
        else:
            alpha = self._alpha

        # Mean: EMA with psychology-aware alpha
        new_mean = (alpha * observed) + ((1 - alpha) * old_mean)

        # Variance: EMA of squared prediction error
        error_sq = (observed - old_mean) ** 2

        # PLAN4: inject behavioral surprise into error
        augmented_error_sq = error_sq + (surprise_score ** 2)

        new_var = (self._beta * augmented_error_sq) + ((1 - self._beta) * old_var)
        new_var = max(0.01, min(new_var, 1.0))

        self._means[dim] = new_mean
        self._variances[dim] = new_var
        return new_mean, new_var

    # ── P1 Psychology: Baseline Drift + Trust Repair ──────────

    def apply_baseline_drift(self, surprise_score: float) -> None:
        """P1-4: Trust naturally heals during prolonged peace.

        If no surprise for peace_threshold consecutive rounds,
        trust drifts toward drift_target (0.3) at drift_rate (0.01/round).
        Time heals wounds — a month without insults rebuilds basic trust.
        """
        if surprise_score >= 0.3:
            self._peace_streak = 0
            return

        self._peace_streak += 1
        if self._peace_streak >= self._peace_threshold:
            current = self._means["trust"]
            if current < self._drift_target:
                self._means["trust"] = min(
                    self._drift_target,
                    current + self._drift_rate,
                )

    # ── P2-8: Cross-Session Persistence ──────────────────────

    def save_state(self, db_path: str, user_id: str = "default") -> None:
        """Persist all relational state to SQLite for cross-session memory.

        Stores means, variances, peace_streak, trust_ema, round_count.
        Restore with load_state() next session — Agent remembers.
        """
        import sqlite3, json
        state = {
            "means": self._means,
            "variances": self._variances,
            "peace_streak": self._peace_streak,
            "trust_ema": self._trust_ema,
            "round_count": self._round_count,
        }
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS relational_history
               (user_id TEXT PRIMARY KEY, state_json TEXT, updated_at REAL)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO relational_history VALUES (?, ?, ?)",
            (user_id, json.dumps(state), __import__("time").time()),
        )
        conn.commit()
        conn.close()

    @classmethod
    def load_state(
        cls, db_path: str, user_id: str = "default",
    ) -> RelationalHistory | None:
        """Restore relational state from SQLite. Returns None if no saved state."""
        import sqlite3, json
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS relational_history
               (user_id TEXT PRIMARY KEY, state_json TEXT, updated_at REAL)"""
        )
        row = conn.execute(
            "SELECT state_json FROM relational_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        state = json.loads(row[0])
        hist = cls()
        hist._means = state.get("means", hist._means)
        hist._variances = state.get("variances", hist._variances)
        hist._peace_streak = state.get("peace_streak", 0)
        hist._trust_ema = state.get("trust_ema", 0.5)
        hist._round_count = state.get("round_count", 0)
        return hist

    def trust_repair(self, amount: float = 0.02) -> None:
        """P1-5: Intentional Violation builds trust through demonstrated integrity.

        When Agent chooses to violate for a higher value, it shows
        principled boundary-setting — not blind obedience.
        Trust increases slightly, even though a violation occurred.
        """
        self._means["trust"] = min(1.0, self._means["trust"] + amount)

    def is_uncertain(self, threshold: float = 0.5) -> bool:
        """Check if any core dimension has high variance.

        High variance means the Agent is 'confused' about the
        relationship state — should switch to conservative mode.
        """
        return any(
            v > threshold for v in self._variances.values()
        )

    def get_mean(self, dim: str) -> float:
        return round(self._means.get(dim, 0.5), 4)

    def get_variance(self, dim: str) -> float:
        return round(self._variances.get(dim, 0.5), 4)

    def get_all_states(self) -> dict[str, dict[str, float]]:
        """Return all dimensions with mean + variance for telemetry."""
        return {
            dim: {"mean": round(self._means[dim], 4),
                  "variance": round(self._variances[dim], 4)}
            for dim in self._means
        }

    @property
    def round_count(self) -> int:
        return self._round_count

    @property
    def trust_ema(self) -> float:
        return round(self._trust_ema, 4)
