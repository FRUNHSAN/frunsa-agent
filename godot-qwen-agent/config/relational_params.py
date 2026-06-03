"""PLAN4 Relational Parameters — Single Source of Truth.

ALL tunable constants live here. Code imports from here.
Docs are auto-generated from here. Change a number in one place.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RelationalParams:
    """Master config for the Bayesian relational engine.

    This is the ONLY place where thresholds, weights, and coefficients
    are defined. Code reads from this. Docs are rendered from this.
    Change one number -> tests verify -> docs auto-update.
    """

    # ── Bayesian EMA (relational_inertia.py) ──────────────────
    trust_alpha_negative: float = 0.30  # Trust erodes fast (negativity bias)
    trust_alpha_positive: float = 0.08  # Trust builds slow (requires evidence)
    energy_alpha_base: float = 0.20     # Base EMA for energy (non-trust dims)
    variance_beta: float = 0.10         # Variance EMA smoothing coefficient

    # ── Smart Decay (relational_inertia.py) ───────────────────
    variance_decay_gamma: float = 0.85  # Per-round variance multiplier when calm
    surprise_decay_threshold: float = 0.30  # Surprise above this blocks decay
    variance_floor: float = 0.01        # Variance never reaches zero

    # ── Baseline Drift (relational_inertia.py) ────────────────
    peace_threshold: int = 5            # Consecutive calm rounds to start drift
    drift_rate: float = 0.01            # Trust gain per round during peace
    drift_target: float = 0.30          # Trust naturally drifts toward this baseline
    trust_repair_amount: float = 0.02   # Trust gain from intentional violation

    # ── Energy / Urgency (relational_inertia.py) ──────────────
    energy_confirm_window: int = 2      # Consecutive readings to confirm transition
    urgency_decay_rounds: int = 3       # Rounds before urgency returns to normal

    # ── Uncertainty (relational_inertia.py) ───────────────────
    uncertain_threshold: float = 0.50   # Variance above this -> conservative mode

    # ── Stage Directions (prompt_generator.py) ────────────────
    stage_confident_max_var: float = 0.05    # < this: direct, confident
    stage_cautious_max_var: float = 0.15     # < this: cautious openness
    stage_alert_max_var: float = 0.25        # < this: alert but functional
    # > 0.25: highly uncertain

    # ── Renegotiation (renegotiation_watcher.py) ──────────────
    renegotiation_violation_threshold: int = 3  # Violations to trigger proposal
    renegotiation_trust_threshold: float = 0.55  # Min trust to propose (calibrated)

    # ── Behavioral Signals (relational_evaluator.py) ──────────
    trust_delta_positive: float = 0.02   # Trust gain per positive keyword
    trust_delta_negative: float = -0.03  # Trust loss per negative keyword
    trust_delta_max: float = 0.10        # Max trust delta per round
    trust_delta_min: float = -0.10       # Min trust delta per round

    # ── Golden Parameters (from blind test, 2026-05-29) ──────
    fatigue_response_compression: float = 0.78  # 78% reduction when fatigue detected


# ── Global singleton ──────────────────────────────────────────

PARAMS = RelationalParams()
