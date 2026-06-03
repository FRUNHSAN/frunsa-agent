"""Relational Evaluator — Phase 27 (PLAN2 Axiom 3).

Bypass sensor that updates the RelationalField without blocking
the main reasoning chain. Level 1 heuristics (fast, deterministic);
future Phase 28+ adds Level 2 (small-model semantic tagging, async).

Design:
  - Stateless: input + current field -> new field
  - Non-blocking: runs before main reasoning, not during
  - Deterministic: same input + same field = same output (testable)
"""

from __future__ import annotations

import re
from datetime import datetime

from core.contracts.relational_field import (
    EnergyLevel,
    RelationalField,
    Urgency,
)


class RelationalEvaluator:
    """Heuristic sensor for relational temperature.

    Level 1: regex-based keyword + time-of-day heuristics.
    Level 2 (future): small-model semantic tagging.
    """

    # ── Level 1: Keyword heuristics ────────────────────────────────

    # Chinese patterns: NO \b — Chinese chars are \W in Python regex
    _LOW_ENERGY_PATTERNS = [
        r"(累|困|乏|头痛|头晕|好累|好困|疲惫|没精神|不想|懒|随便|简单点|就这样|算了)",
        r"(?i)\b(tired|exhausted|fatigue|headache|lazy|drained)\b",
    ]

    _HIGH_ENERGY_PATTERNS = [
        r"(兴奋|期待|来吧|开始|搞起|冲)",
        r"(?i)\b(excited|ready|go|awesome|great|let's)\b",
    ]

    _CRITICAL_URGENCY_PATTERNS = [
        r"(急|快|马上|紧急|立刻|赶紧|救命)",
        r"(?i)\b(urgent|asap|critical|emergency|now|quickly)\b",
    ]

    _LEISURE_URGENCY_PATTERNS = [
        r"(不急|慢慢来|随便|无所谓|闲聊)",
        r"(?i)\b(leisure|casual|whenever|no rush|chat)\b",
    ]

    _TRUST_POSITIVE_PATTERNS = [
        r"(谢谢|感谢|太好了|很棒)",
        r"(?i)\b(nice|great|awesome|appreciate|thanks)\b",
    ]

    _TRUST_NEGATIVE_PATTERNS = [
        r"(不对|错了|不行|糟糕|失望)",
        r"(?i)\b(useless|wrong|bad|broken)\b",
    ]

    # ── Evaluate ──────────────────────────────────────────────────

    @classmethod
    def evaluate(
        cls,
        user_input: str,
        current_field: RelationalField | None = None,
    ) -> RelationalField:
        """Sense relational temperature from user input.

        Args:
            user_input:    Raw user message
            current_field: Previous RelationalField (None = default)

        Returns:
            Updated RelationalField reflecting sensed state
        """
        field = current_field if current_field is not None else RelationalField.default()

        # Detect energy level
        energy = cls._detect_energy(user_input, field.energy_level)

        # Detect urgency
        urgency = cls._detect_urgency(user_input, field.urgency)

        # Detect trust delta
        trust_delta = cls._detect_trust_delta(user_input)

        # Build narrative
        narrative = cls._build_narrative(user_input, energy, urgency, trust_delta)

        # Time-of-day heuristic: late night -> slight energy drop
        if energy == EnergyLevel.NEUTRAL:
            hour = datetime.now().hour
            if hour >= 23 or hour <= 5:
                energy = EnergyLevel.LOW
                narrative += " 检测到深夜交互。"

        return RelationalField(
            energy_level=energy,
            urgency=urgency,
            trust_watermark=field.trust_watermark + trust_delta,
            active_contracts=list(field.active_contracts),
            recent_narrative=narrative,
        )

    # ── Internal detectors ────────────────────────────────────────

    @classmethod
    def _detect_energy(
        cls, text: str, current: EnergyLevel,
    ) -> EnergyLevel:
        for pattern in cls._LOW_ENERGY_PATTERNS:
            if re.search(pattern, text):
                return EnergyLevel.LOW
        for pattern in cls._HIGH_ENERGY_PATTERNS:
            if re.search(pattern, text):
                return EnergyLevel.HIGH
        return current

    @classmethod
    def _detect_urgency(
        cls, text: str, current: Urgency,
    ) -> Urgency:
        for pattern in cls._CRITICAL_URGENCY_PATTERNS:
            if re.search(pattern, text):
                return Urgency.CRITICAL
        for pattern in cls._LEISURE_URGENCY_PATTERNS:
            if re.search(pattern, text):
                return Urgency.LEISURE
        return current

    @classmethod
    def _detect_trust_delta(cls, text: str) -> float:
        """Return trust adjustment from keywords."""
        delta = 0.0
        for pattern in cls._TRUST_POSITIVE_PATTERNS:
            if re.search(pattern, text):
                delta += 0.02
        for pattern in cls._TRUST_NEGATIVE_PATTERNS:
            if re.search(pattern, text):
                delta -= 0.03
        return max(-0.10, min(0.10, delta))  # clamp

    # ── Behavioral Signals (PLAN4 Surprise Detector) ────────────

    @staticmethod
    def extract_behavioral_signals(
        user_input: str, recent_lengths: list[int] | None = None,
    ) -> dict[str, float]:
        """Extract physics-level behavioral signals independent of semantics.

        These signals catch what keyword detectors miss: a user who types
        200 excited characters without using the word 'excited'.

        Returns:
            dict with length_ratio, exclamation_density, surprise_score
        """
        if not recent_lengths:
            recent_lengths = [20]  # default baseline

        avg_len = sum(recent_lengths) / len(recent_lengths)
        input_len = len(user_input)

        # Length ratio: how many times longer/shorter than recent average
        length_ratio = input_len / max(avg_len, 1.0)

        # Exclamation density per 10 characters
        exclamations = user_input.count("！") + user_input.count("!")
        exclamation_density = exclamations / max(input_len / 10.0, 1.0)

        # Surprise score: composite of behavioral anomalies
        # length_ratio > 3x means significant deviation
        # exclamation_density > 0.5 means very excited
        surprise = max(0.0, (length_ratio - 3.0) / 5.0)
        surprise += min(exclamation_density, 1.0)
        surprise = round(min(surprise, 1.0), 4)

        return {
            "length_ratio": round(length_ratio, 2),
            "exclamation_density": round(exclamation_density, 2),
            "surprise_score": surprise,
        }

    @classmethod
    def _build_narrative(
        cls, text: str, energy: EnergyLevel, urgency: Urgency,
        trust_delta: float,
    ) -> str:
        """Build a 1-sentence narrative summary."""
        parts = []
        if energy == EnergyLevel.LOW:
            parts.append("检测到疲惫/低能量信号")
        elif energy == EnergyLevel.HIGH:
            parts.append("用户显得兴奋/精力充沛")
        if urgency == Urgency.CRITICAL:
            parts.append("高紧迫度")
        elif urgency == Urgency.LEISURE:
            parts.append("轻松节奏")
        if trust_delta > 0:
            parts.append("信任信号")
        elif trust_delta < 0:
            parts.append("挫败信号")
        return "。".join(parts) + "。" if parts else "常规交互。"
