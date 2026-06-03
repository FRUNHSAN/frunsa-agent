"""Relational Field — Phase 27 (PLAN2 Axiom 3).

The "skin and nerves" of the Agent. While Context is history (hard drive),
RelationalField is presence (skin) — a real-time projection of the
human-agent relationship state. The Agent doesn't "remember" the user's
fatigue; it "feels" it through this field.

Design:
  - Frozen dataclass (immutable snapshot per interaction)
  - Three temperature dimensions: energy, urgency, trust
  - NarrativeFlow: compressed emotional trajectory, not raw history
  - Updated by RelationalEvaluator (async bypass sensor)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class EnergyLevel(str, Enum):
    """The user's current cognitive/emotional energy.

    HIGH:    Excited, exploratory, high bandwidth
    NEUTRAL: Routine collaboration, baseline
    LOW:     Fatigued, frustrated, cognitive overload
    """
    HIGH = "high"
    NEUTRAL = "neutral"
    LOW = "low"


class Urgency(str, Enum):
    """The time-pressure dimension of the current interaction.

    CRITICAL: Immediate result needed, low tolerance for errors
    NORMAL:   Standard pace
    LEISURE:  Casual, exploratory, high tolerance for detours
    """
    CRITICAL = "critical"
    NORMAL = "normal"
    LEISURE = "leisure"


@dataclass(frozen=True)
class RelationalField:
    """Real-time projection of the human-agent relationship.

    This is WORKING MEMORY (Axiom 3) — not history, not storage.
    It captures "how things feel right now" rather than "what happened before."

    Attributes:
        energy_level:      User's cognitive/emotional bandwidth
        urgency:           Time-pressure dimension
        trust_watermark:   0.0 (broken) to 1.0 (absolute trust)
        active_contracts:  Which contract IDs are currently governing behavior
        recent_narrative:  Compressed emotional trajectory (1-2 sentences)
        updated_at:        Epoch timestamp of last field update
    """

    energy_level: EnergyLevel = EnergyLevel.NEUTRAL
    urgency: Urgency = Urgency.NORMAL
    trust_watermark: float = 0.5
    active_contracts: List[str] = field(default_factory=list)
    recent_narrative: str = ""
    updated_at: float = field(default_factory=__import__("time").time)

    def __post_init__(self) -> None:
        if not 0.0 <= self.trust_watermark <= 1.0:
            raise ValueError(
                f"trust_watermark must be in [0.0, 1.0], got {self.trust_watermark}"
            )

    @classmethod
    def default(cls) -> RelationalField:
        """Factory: a neutral, baseline relationship state."""
        return cls(
            energy_level=EnergyLevel.NEUTRAL,
            urgency=Urgency.NORMAL,
            trust_watermark=0.5,
            active_contracts=[],
            recent_narrative="Initial contact.",
        )

    def with_energy(self, level: EnergyLevel, narrative_delta: str) -> RelationalField:
        """Return a new field with updated energy and narrative."""
        return RelationalField(
            energy_level=level,
            urgency=self.urgency,
            trust_watermark=self.trust_watermark,
            active_contracts=list(self.active_contracts),
            recent_narrative=narrative_delta,
        )

    def with_trust(self, delta: float, narrative_delta: str) -> RelationalField:
        """Return a new field with adjusted trust watermark."""
        new_trust = max(0.0, min(1.0, self.trust_watermark + delta))
        return RelationalField(
            energy_level=self.energy_level,
            urgency=self.urgency,
            trust_watermark=new_trust,
            active_contracts=list(self.active_contracts),
            recent_narrative=narrative_delta,
        )

    @property
    def is_low_energy(self) -> bool:
        return self.energy_level == EnergyLevel.LOW

    @property
    def is_critical(self) -> bool:
        return self.urgency == Urgency.CRITICAL

    @property
    def trust_level(self) -> str:
        if self.trust_watermark >= 0.8:
            return "deep"
        if self.trust_watermark >= 0.5:
            return "stable"
        if self.trust_watermark >= 0.2:
            return "fragile"
        return "broken"
