"""V5.3 Dual-Sensor Fusion — unit tests for compute_dual_sensor_f + _path2_branch_count.

These are pure math tests — no LLM, no embedding, no I/O.
Validates the four control regimes: deadzone, lucid suppression, OR logic, saturation.
"""

import pytest
from core.track_c import compute_dual_sensor_f, _path2_branch_count, _compute_drift_factor


# ═══════════════════════════════════════════════════════════════════════════
# compute_dual_sensor_f — 双传感器融合
# ═══════════════════════════════════════════════════════════════════════════

class TestDualSensorFusion:
    """Parameterized tests for the dual-sensor fusion function Φ(d, c)."""

    @pytest.mark.parametrize("drift, clarity, expected_f, label", [
        # Scene 3 R1: cold-start absurd request → high f from confusion only
        (0.000, 0.15, 0.85, "coldstart-absurd"),
        # Scene 4 R2: lucid topic switch → suppressed to deadzone edge (0.20)
        (0.687, 0.95, 0.20, "lucid-switch"),
        # Scene 1: normal stable interaction → deadzone
        (0.050, 0.85, 0.00, "normal-stable"),
        # Extreme drift + extreme confusion → saturated (both ceiling at 1.0)
        (0.900, 0.30, 1.00, "extreme-chaos"),
        # Boundary: clarity AT 0.80 → no suppression (not >0.80), OR logic
        # f_drift = (0.4-0.2)/0.4 = 0.5, f_clarity = 1-0.8 = 0.2
        # OR: max(0.5, 0.2) = 0.5
        (0.400, 0.80, 0.50, "boundary-clarity-at-threshold"),
        # Boundary: drift at deadzone edge, high clarity → f_drift=0, suppressed
        (0.200, 0.90, 0.00, "boundary-drift-deadzone-edge"),
        # Mid-drift + mid-clarity → OR logic, both contribute
        (0.400, 0.60, 0.50, "mid-both"),
        # High drift + clarity just above threshold → lucid suppression
        (0.700, 0.81, 0.20, "lucid-suppression-boundary"),
        # Zero clarity → f_clarity = 1.0 → f = 1.0 (OR logic, no drift needed)
        (0.000, 0.00, 1.00, "zero-clarity-max-confusion"),
        # Perfect clarity → f_clarity = 0.0, lucid suppression if drift present
        (0.500, 1.00, 0.20, "perfect-clarity-lucid"),
        # Low drift + moderate clarity → OR, mid-range f
        (0.250, 0.50, 0.50, "low-drift-mid-clarity"),
        # Moderate drift + high clarity → lucid suppression
        (0.450, 0.90, 0.20, "moderate-drift-high-clarity"),
    ])
    def test_dual_sensor_fusion(self, drift, clarity, expected_f, label):
        result = compute_dual_sensor_f(drift, clarity)
        assert result == pytest.approx(expected_f, abs=0.05), \
            f"[{label}] drift={drift}, clarity={clarity} → expected f≈{expected_f}, got {result}"

    def test_clarity_0_81_suppresses(self):
        """clarity > 0.80 must trigger lucid suppression, clamping f ≤ 0.20."""
        # drift=0.9 → f_drift=1.0 (saturated)
        f = compute_dual_sensor_f(0.9, 0.81)
        assert f <= 0.20, f"clarity=0.81 should suppress drift=0.9, got f={f}"

    def test_clarity_0_79_does_not_suppress(self):
        """clarity ≤ 0.80 must NOT trigger lucid suppression. Uses OR logic."""
        # drift=0.9 → f_drift=1.0, clarity=0.79 → f_clarity=0.21
        f = compute_dual_sensor_f(0.9, 0.79)
        assert f > 0.20, f"clarity=0.79 should NOT suppress, got f={f}"
        assert f == pytest.approx(1.0, abs=0.05)  # max(1.0, 0.21)

    def test_or_logic_takes_maximum(self):
        """Under OR logic (clarity ≤ 0.80), f = max(f_drift, 1-clarity)."""
        # drift=0.3 → f_drift=0.25, clarity=0.5 → f_clarity=0.5
        f = compute_dual_sensor_f(0.3, 0.5)
        assert f == pytest.approx(0.5, abs=0.05)  # max(0.25, 0.5)

    def test_monotonic_in_drift(self):
        """For fixed clarity, f should be non-decreasing with drift (OR mode)."""
        base = compute_dual_sensor_f(0.1, 0.5)
        mid = compute_dual_sensor_f(0.3, 0.5)
        high = compute_dual_sensor_f(0.5, 0.5)
        assert base <= mid <= high, \
            f"Monotonicity violated: f(0.1)={base}, f(0.3)={mid}, f(0.5)={high}"

    def test_monotonic_in_clarity_under_or(self):
        """For fixed drift (non-zero), lower clarity should NOT decrease f under OR."""
        # drift=0.3 → f_drift=0.25
        f_clear = compute_dual_sensor_f(0.3, 0.9)  # clarity high → suppression
        # Actually for clarity=0.9, suppression kicks in, so monotonic fails.
        # Test only in OR regime (clarity ≤ 0.80):
        f_avg = compute_dual_sensor_f(0.3, 0.7)  # 1-0.7=0.3
        f_low = compute_dual_sensor_f(0.3, 0.5)  # 1-0.5=0.5
        assert f_low >= f_avg, \
            f"Lower clarity should increase f (more confusion): f(0.5)={f_low}, f(0.7)={f_avg}"


# ═══════════════════════════════════════════════════════════════════════════
# _compute_drift_factor — 死区+斜坡+饱和 (unchanged, regression guard)
# ═══════════════════════════════════════════════════════════════════════════

class TestDriftFactor:
    def test_deadzone(self):
        assert _compute_drift_factor(0.0) == 0.0
        assert _compute_drift_factor(0.10) == 0.0
        assert _compute_drift_factor(0.19) == 0.0

    def test_ramp(self):
        # At raw_drift=0.20: (0.20-0.20)/0.40 = 0.0
        assert _compute_drift_factor(0.20) == 0.0
        # Mid-ramp: (0.40-0.20)/0.40 = 0.5
        assert _compute_drift_factor(0.40) == 0.5
        # Top of ramp: (0.60-0.20)/0.40 = 1.0 (float precision)
        assert _compute_drift_factor(0.60) == pytest.approx(1.0)

    def test_saturation(self):
        assert _compute_drift_factor(0.61) == 1.0
        assert _compute_drift_factor(1.00) == 1.0
        assert _compute_drift_factor(2.00) == 1.0  # max cosine distance

    def test_monotonic(self):
        values = [_compute_drift_factor(d) for d in
                  [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1], \
                f"Drift factor not monotonic: {values}"


# ═══════════════════════════════════════════════════════════════════════════
# _path2_branch_count — fused factor → branch count (pure math, zero keywords)
# ═══════════════════════════════════════════════════════════════════════════

class TestPath2BranchCount:
    """_path2_branch_count is a pure function of f — no user_text, no keyword lists."""

    def test_exploit_boundaries(self):
        """f ≤ 0.30 → 1 branch (EXPLOIT)."""
        assert _path2_branch_count(0.00) == 1
        assert _path2_branch_count(0.10) == 1
        assert _path2_branch_count(0.20) == 1
        assert _path2_branch_count(0.30) == 1  # boundary inclusive

    def test_balanced_boundaries(self):
        """0.30 < f ≤ 0.50 → 2 branches (BALANCED)."""
        assert _path2_branch_count(0.31) == 2
        assert _path2_branch_count(0.40) == 2
        assert _path2_branch_count(0.50) == 2  # boundary inclusive

    def test_explore_boundaries(self):
        """f > 0.50 → 3 branches (EXPLORE)."""
        assert _path2_branch_count(0.51) == 3
        assert _path2_branch_count(0.75) == 3
        assert _path2_branch_count(1.00) == 3  # saturated
        assert _path2_branch_count(5.00) == 3  # way out of range, still 3

    def test_monotonic(self):
        """More fused uncertainty → same or more branches, never fewer."""
        values = [_path2_branch_count(f) for f in
                  [0.0, 0.1, 0.2, 0.3, 0.31, 0.4, 0.5, 0.51, 0.7, 0.9, 1.0]]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1], \
                f"Branch count not monotonic: {values}"

    def test_no_keyword_dependency(self):
        """_path2_branch_count must accept a single float (no user_text parameter)."""
        import inspect
        sig = inspect.signature(_path2_branch_count)
        params = list(sig.parameters.keys())
        assert params == ["f"], \
            f"_path2_branch_count should take only 'f', got {params}"
        assert "user_text" not in params, \
            "Keyword gate parameter 'user_text' must NOT exist"
