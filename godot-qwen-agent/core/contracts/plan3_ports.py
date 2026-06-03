"""PLAN3/4 Ports — anti-corruption layer for relational engine.

Defines the Protocols that decouple PLAN3/4 components.
Existing implementations (RelationalStateAggregator, PromptGenerator,
RelationalHistory) already satisfy these via duck typing.
Adding explicit Protocols enables:
  - PLAN4 TensorAggregator (tensor-based, replaces dict-based)
  - Alternative SeedGenerators (LLM-based, template-based, tensor-decode)
  - Alternative InertiaTrackers (Bayesian, Kalman, pure EMA)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StateAggregator(Protocol):
    """Contract: produce a relational context from raw data sources.

    Current impl: RelationalStateAggregator (dict-based, PLAN3).
    Future impl: TensorStateAggregator (matrix-based, PLAN4).
    """

    def aggregate(
        self,
        field: Any,
        report: Any,
        sink: Any,
        memory: Any,
        blueprint_fingerprint: str,
        history: Any = None,
    ) -> Any:
        """Produce a context object from field + report + sink + memory."""
        ...


@runtime_checkable
class SeedGenerator(Protocol):
    """Contract: grow a relational seed from a context.

    Current impl: PromptGenerator (rule-based, PLAN3).
    Future impl: TensorPromptGenerator (attention+decode, PLAN4).
    """

    def grow(self, ctx: Any, history: Any = None) -> str:
        """Grow a ~50-word relational seed from context + optional history."""
        ...


@runtime_checkable
class InertiaTracker(Protocol):
    """Contract: track relational history with smoothing.

    Current impl: RelationalHistory (EMA + Bayesian, PLAN3/4).
    Future impl: KalmanTracker, PureBayesianTracker.
    """

    def record(
        self, energy: str, urgency: str, trust: float, tone: str,
    ) -> None:
        """Record a round's raw state."""
        ...

    def smooth(
        self, raw_energy: str, raw_urgency: str,
        raw_trust: float, raw_tone: str,
    ) -> tuple[str, str, float, str]:
        """Apply inertia smoothing to raw readings."""
        ...

    def bayesian_update(
        self, dim: str, observed: float,
    ) -> tuple[float, float]:
        """Update Bayesian mean+variance for a dimension."""
        ...

    def is_uncertain(self, threshold: float = 0.5) -> bool:
        """Check if any core dimension has high variance."""
        ...

    def get_all_states(self) -> dict[str, dict[str, float]]:
        """Return all dimensions with mean+variance for telemetry."""
        ...
