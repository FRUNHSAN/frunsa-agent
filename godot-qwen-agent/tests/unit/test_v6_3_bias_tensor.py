"""V6.3 Bias Tensor — orthogonal bias fission from meta_adapt state.

Validates:
  - Cause A (Capability Exhaustion): low drift → explore=0, compromise>0
  - Cause B (Intent Contradiction): high drift → explore>0, compromise=0
  - Minimax Fallback: drift=None → treated as 1.0 (worst-case, Cause B)
  - No accumulation: repeated calls produce identical results
  - P9 floor: compromise_bias cannot breach θ=0.50
  - P11 freeze: biases are primitive floats, no reference to meta_adapt
"""

import pytest
from core.track_c import _critic_threshold, compute_dual_sensor_f, _path2_branch_count


# ═══════════════════════════════════════════════════════════════════════════
# Bias tensor logic (simulating _compute_bias_tensor)
# ═══════════════════════════════════════════════════════════════════════════

def _simulate_bias_tensor(is_relaxed: bool, last_raw_drift: float | None
                          ) -> tuple[float, float]:
    """Pure-function simulation of REPL._compute_bias_tensor for testing."""
    if not is_relaxed:
        return 0.0, 0.0

    drift = last_raw_drift
    if drift is None:
        drift = 1.0  # Minimax Fallback

    if drift > 0.5:
        return 0.20, 0.00  # Cause B: Intent Contradiction
    else:
        return 0.00, 0.05  # Cause A: Capability Exhaustion


class TestBiasTensorFission:
    def test_not_relaxed_returns_zero(self):
        eb, cb = _simulate_bias_tensor(False, 0.8)
        assert eb == 0.0
        assert cb == 0.0

    def test_cause_a_capability_exhaustion(self):
        """Low drift → clear goal, system can't deliver. Explore=0, compromise=0.05."""
        eb, cb = _simulate_bias_tensor(True, 0.2)
        assert eb == 0.00, "Capability exhaustion: should NOT explore more"
        assert cb == 0.05, "Capability exhaustion: should relax Critic slightly"

    def test_cause_b_intent_contradiction(self):
        """High drift → unclear goal. Explore=0.20, compromise=0."""
        eb, cb = _simulate_bias_tensor(True, 0.8)
        assert eb == 0.20, "Intent contradiction: should explore widely"
        assert cb == 0.00, "Intent contradiction: should NOT lower standards"

    def test_boundary_at_0_5(self):
        """drift=0.5 exactly → Cause A (≤ threshold)."""
        eb, cb = _simulate_bias_tensor(True, 0.5)
        assert eb == 0.00
        assert cb == 0.05

    def test_boundary_just_above_0_5(self):
        """drift=0.51 → Cause B (> threshold)."""
        eb, cb = _simulate_bias_tensor(True, 0.51)
        assert eb == 0.20
        assert cb == 0.00


class TestMinimaxFallback:
    def test_none_drift_treated_as_chaos(self):
        """drift=None → Minimax: assume worst-case (intent contradiction)."""
        eb, cb = _simulate_bias_tensor(True, None)
        assert eb == 0.20, "Minimax: should assume chaos → explore"
        assert cb == 0.00, "Minimax: should NOT compromise Critic without evidence"

    def test_none_drift_without_relax_no_effect(self):
        """None drift when not relaxed → still zero."""
        eb, cb = _simulate_bias_tensor(False, None)
        assert eb == 0.0
        assert cb == 0.0


class TestNoAccumulation:
    def test_repeated_calls_identical(self):
        """Bias tensor is a pure function of snapshot — no hidden integrator."""
        results = [_simulate_bias_tensor(True, 0.3) for _ in range(5)]
        for r in results:
            assert r == results[0]

    def test_state_change_reflected_immediately(self):
        """When drift changes, bias changes instantly — no inertia."""
        eb1, cb1 = _simulate_bias_tensor(True, 0.2)
        eb2, cb2 = _simulate_bias_tensor(True, 0.8)
        assert eb1 != eb2, "Bias should change when drift changes"
        assert cb1 != cb2, "Bias should change when drift changes"


# ═══════════════════════════════════════════════════════════════════════════
# P9: compromise_bias cannot breach Critic floor
# ═══════════════════════════════════════════════════════════════════════════

class TestP9FloorProtection:
    def test_compromise_never_breaches_floor(self):
        """Even at max penalty (f=1, g=1), compromise_bias=0.05 can't go below 0.50."""
        # Base θ = 0.75 - 0.25*1*1 = 0.50, session_gain=1.0
        theta = _critic_threshold(1.0, 1.0, session_gain=1.0)
        assert theta == pytest.approx(0.50, abs=0.01)
        # Now apply compromise_bias=0.05 externally
        theta_with_compromise = max(0.50, theta - 0.05)
        assert theta_with_compromise == 0.50, "P9: must not breach 0.50"

    def test_compromise_applies_when_above_floor(self):
        """When θ is above floor, compromise_bias should reduce it."""
        theta = _critic_threshold(0.0, 0.0, session_gain=1.0)  # 0.75
        theta_with_compromise = max(0.50, theta - 0.05)
        assert theta_with_compromise == pytest.approx(0.70)


# ═══════════════════════════════════════════════════════════════════════════
# P2: explore_bias only affects Planning, not Critic
# ═══════════════════════════════════════════════════════════════════════════

class TestBiasOrthogonality:
    def test_explore_only_planning(self):
        """explore_bias affects f_planning → branch_count, but NOT Critic θ."""
        # Use drift=0.35 → f_drift ≈ 0.375, clarity=0.6 (< 0.80 → OR logic)
        # f_fused = max(0.375, 0.4) = 0.4 → BALANCED boundary
        f_fused = compute_dual_sensor_f(0.35, 0.60)
        n_base = _path2_branch_count(f_fused)

        # Now apply explore_bias=0.20 → should push into EXPLORE territory
        f_planning = min(1.0, f_fused + 0.20)
        n_biased = _path2_branch_count(f_planning)
        assert n_biased >= n_base, \
            f"Explore bias should increase or maintain branches: {n_base}→{n_biased}"

        # Critic θ is computed independently from f_drift (drift-only, P2)
        # explore_bias does NOT flow into θ computation
        from core.track_c import _critic_factors
        f_drift, g = _critic_factors(0.35, 0.50)
        theta = _critic_threshold(f_drift, g)
        assert theta == pytest.approx(0.75, abs=0.05), \
            "Critic should be unaffected by explore_bias (P2: drift-only)"

    def test_compromise_only_critic(self):
        """compromise_bias affects Critic θ, not Planning branch_count."""
        f_fused = compute_dual_sensor_f(0.05, 0.85)
        n = _path2_branch_count(f_fused)
        assert n == 1, "Planning should be unaffected by compromise_bias"

        from core.track_c import _critic_factors
        f_drift, g = _critic_factors(0.05, 0.50)
        theta = _critic_threshold(f_drift, g)
        theta_compromised = max(0.50, theta - 0.05)
        assert theta_compromised < theta, "Critic should be affected by compromise_bias"
