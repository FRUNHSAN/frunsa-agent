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

    @property
    def round_count(self) -> int:
        return self._round_count

    @property
    def trust_ema(self) -> float:
        return round(self._trust_ema, 4)
