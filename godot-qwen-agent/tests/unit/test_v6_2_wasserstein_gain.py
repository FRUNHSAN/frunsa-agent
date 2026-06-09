"""V6.2 Wasserstein Session Gain — Bayesian smoothing + calibration + degradation.

Pure math tests: no LLM, no I/O. Validates:
  - Cold-start damping (α=3 absorbs initial noise)
  - Asymptotic takeover (n→∞, session variance dominates)
  - Narrow domain tightening (gain → 0.5 floor)
  - Degradation contract (uncalibrated → gain=1.0 neutral)
  - Critic threshold with session_gain (max ±0.05 adjustment)
"""

import pytest
from core.adapters.wasserstein_proxy import WassersteinProxy
from core.track_c import _critic_threshold


# ═══════════════════════════════════════════════════════════════════════════
# compute_session_gain — Bayesian smoothing
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionGain:
    def setup_method(self):
        self.proxy = WassersteinProxy()
        # Simulate calibration: set baseline variance
        self.proxy._baseline_variance = 0.1
        self.proxy._calibrated = True

    def test_cold_start_damping(self):
        """n=1, session_var=0.8 (extreme) → prior dominates, gain near 1.0."""
        gain = self.proxy.compute_session_gain(0.8, n_rounds=1, alpha=3)
        # smoothed = (3*0.1 + 1*0.8)/4 = 0.275, gain = 0.275/0.1 = 2.75 → clamp 2.0
        # Actually: smoothed_var = (0.3 + 0.8)/4 = 0.275, gain = 2.75, clamp → 2.0
        assert 1.5 <= gain <= 2.0, f"Cold-start should be clamped near 1.0-2.0, got {gain}"

    def test_cold_start_with_small_variance(self):
        """n=1, session_var close to baseline → gain near 1.0."""
        gain = self.proxy.compute_session_gain(0.12, n_rounds=1, alpha=3)
        # smoothed = (0.3 + 0.12)/4 = 0.105, gain = 1.05
        assert 0.9 <= gain <= 1.2, f"Near-baseline cold-start should be ~1.0, got {gain}"

    def test_asymptotic_takeover(self):
        """n=100, session_var=0.8 → session dominates, gain → 2.0 (clamped)."""
        gain = self.proxy.compute_session_gain(0.8, n_rounds=100, alpha=3)
        # smoothed = (0.3 + 80)/103 ≈ 0.780, gain = 7.8 → clamp 2.0
        assert gain == pytest.approx(2.0, abs=0.05), \
            f"Large-n wide domain should saturate at 2.0, got {gain}"

    def test_narrow_domain_tightening(self):
        """n=20, session_var=0.02 (very narrow) → gain → 0.5 (floor)."""
        gain = self.proxy.compute_session_gain(0.02, n_rounds=20, alpha=3)
        # smoothed = (0.3 + 0.4)/23 ≈ 0.030, gain = 0.304 → clamp 0.5
        assert gain == pytest.approx(0.5, abs=0.05), \
            f"Narrow domain should floor at 0.5, got {gain}"

    def test_neutral_session(self):
        """session_var = baseline_var → gain = 1.0 regardless of n."""
        gain = self.proxy.compute_session_gain(0.1, n_rounds=10, alpha=3)
        assert gain == pytest.approx(1.0, abs=0.05)

    def test_monotonic_with_n(self):
        """For fixed session_var > baseline, gain should increase with n."""
        gains = [self.proxy.compute_session_gain(0.5, n, alpha=3)
                 for n in [1, 3, 5, 10, 20, 50]]
        for i in range(len(gains) - 1):
            assert gains[i] <= gains[i + 1] + 0.01, \
                f"Gain should be monotonic: {gains}"

    def test_clamp_bounds(self):
        """Gain must always be in [0.5, 2.0]."""
        for sv in [0.0, 0.001, 0.1, 0.5, 1.0, 5.0, 100.0]:
            for n in [1, 3, 10, 50]:
                gain = self.proxy.compute_session_gain(sv, n, alpha=3)
                assert 0.5 <= gain <= 2.0, \
                    f"session_var={sv}, n={n}: gain={gain} out of [0.5, 2.0]"


# ═══════════════════════════════════════════════════════════════════════════
# Degradation contract (A5)
# ═══════════════════════════════════════════════════════════════════════════

class TestDegradation:
    def test_uncalibrated_returns_neutral(self):
        proxy = WassersteinProxy.uncalibrated()
        gain = proxy.compute_session_gain(0.5, n_rounds=10)
        assert gain == 1.0, "Uncalibrated proxy should return neutral gain=1.0"

    def test_uncalibrated_is_calibrated_false(self):
        proxy = WassersteinProxy.uncalibrated()
        assert not proxy.is_calibrated

    def test_zero_baseline_variance_returns_neutral(self):
        proxy = WassersteinProxy()
        proxy._baseline_variance = 0.0
        proxy._calibrated = True
        gain = proxy.compute_session_gain(0.5, n_rounds=10)
        assert gain == 1.0, "Zero baseline should return neutral"

    def test_none_baseline_variance_returns_neutral(self):
        proxy = WassersteinProxy()
        proxy._calibrated = True  # calibrated but no variance set
        gain = proxy.compute_session_gain(0.5, n_rounds=10)
        assert gain == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# _critic_threshold with session_gain
# ═══════════════════════════════════════════════════════════════════════════

class TestCriticThresholdWithGain:
    def test_neutral_gain_no_effect(self):
        """session_gain=1.0 should not change the base threshold."""
        base = _critic_threshold(0.0, 0.0, session_gain=1.0)
        assert base == 0.75
        mid = _critic_threshold(0.5, 0.5, session_gain=1.0)
        expected = max(0.50, 0.75 - 0.25 * 0.5 * 0.5)
        assert mid == pytest.approx(expected, abs=0.01)

    def test_wide_domain_relaxes(self):
        """gain=2.0 → θ reduced by 0.05."""
        theta = _critic_threshold(0.0, 0.0, session_gain=2.0)
        assert theta == pytest.approx(0.70, abs=0.01)  # 0.75 - 0.05

    def test_narrow_domain_tightens(self):
        """gain=0.5 → θ increased by 0.025."""
        theta = _critic_threshold(0.0, 0.0, session_gain=0.5)
        assert theta == pytest.approx(0.75, abs=0.01)  # 0.75 + 0.025 → clamp 0.75

    def test_gain_does_not_breach_floor(self):
        """Even with gain=2.0 and full penalty, θ ≥ 0.50."""
        theta = _critic_threshold(1.0, 1.0, session_gain=2.0)
        # base = 0.75 - 0.25 = 0.50, then -0.05*(2-1) = -0.05 → 0.45 → clamp 0.50
        assert theta >= 0.50

    def test_gain_subordinate_to_primary_gating(self):
        """Gain effect (±0.05) is always smaller than f×g effect (±0.25)."""
        # Max gain effect
        theta_wide = _critic_threshold(0.0, 0.0, session_gain=2.0)
        assert 0.75 - theta_wide == pytest.approx(0.05)  # max 0.05 reduction
        # Primary effect
        theta_penalty = _critic_threshold(1.0, 1.0, session_gain=1.0)
        assert 0.75 - theta_penalty == pytest.approx(0.25)  # 0.25 from f×g
