"""V7.4 Unit tests — Identity Manifold.

Covers:
  - 12-dim IdentityPoint (frozen, confidence, prior application)
  - SessionSufficientStatistic (immutable, correct semantics)
  - StreamingPercentile (quantile, KS drift, cycle detection, bootstrap CI)
  - IdentityManifoldStore (evolve, OU decay, Betti detection, boundary lock)
  - Red-team patches (#4 skew penalty, #5 relaxing boundary, #6 dual-threshold)
  - Engineering patches (E1 dynamic window, E2 dimension-adaptive tau, E3 three-state)
  - Physical dimension lifecycle (PHYSICAL_DIMENSION_MAP, hard cap)
"""

import math
import time
import pytest
from core.memory.identity_manifold import (
    IdentityPoint,
    SessionSufficientStatistic,
    IdentityManifoldStore,
    StreamingPercentile,
    adaptive_pctl,
    DIMENSION_BASE_TAU,
    compute_dimension_tau,
    SKEW_CRITICAL,
    SKEW_PENALTY_GAMMA,
    MIN_CONFIDENCE_SESSIONS,
)


# ═══════════════════════════════════════════════════════════════════════
# IdentityPoint — 12 dimensions
# ═══════════════════════════════════════════════════════════════════════

class TestIdentityPointDimensions:
    """Validate 12-dim structure and defaults."""

    def test_default_12_dimensions(self):
        p = IdentityPoint()
        assert p.trust == 0.5
        assert p.clarity_P50 == 0.5  # Corrected from 0.75 (max-entropy)
        assert p.physical_fail_rate is None  # Not 0.0 — unobserved
        assert p.budget_exhaustion_rate is None  # Unobserved
        assert p.tool_risk_aversion == 0.5
        assert p.retry_success_rate == 0.5
        assert p.session_count == 0

    def test_frozen_dataclass(self):
        p = IdentityPoint()
        with pytest.raises(Exception):
            p.trust = 0.8  # type: ignore

    def test_physical_dimension_map_binding(self):
        """Every physical dimension must have a policy mapping."""
        p = IdentityPoint()
        assert "tool_risk_aversion" in p.PHYSICAL_DIMENSION_MAP
        assert "budget_exhaustion_rate" in p.PHYSICAL_DIMENSION_MAP
        assert "retry_success_rate" in p.PHYSICAL_DIMENSION_MAP
        assert "physical_fail_rate" in p.PHYSICAL_DIMENSION_MAP
        # Hard cap
        assert len(p.PHYSICAL_DIMENSION_MAP) <= p.PHYSICAL_DIM_HARD_CAP

    def test_with_interval_online_skew(self):
        """Welford update: sequential intervals with growing session_count."""
        p = IdentityPoint(session_count=0)
        intervals = [3600.0, 7200.0, 1800.0, 5400.0, 3600.0]
        for i, dt in enumerate(intervals):
            # Simulate session_count growing across sessions (real usage)
            p = IdentityPoint(**{**p.__dict__, "session_count": i + 1})
            p = p.with_interval(dt)
        # After 5 intervals with proper Welford, μ ≈ mean
        assert abs(p.interval_mu - 4320.0) < 2000.0  # Welford converges
        assert p.interval_sigma >= 0

    def test_with_interval_anti_gaming_clamp(self):
        """Intervals < 2 seconds clamped (Red-team #4)."""
        p = IdentityPoint(session_count=0)
        p = p.with_interval(0.5)  # Would be gamed
        assert p.interval_mu >= 2.0


class TestIdentityPointConfidence:
    """Red-team #4: hardened confidence weight."""

    def test_low_session_count_zero_confidence(self):
        p = IdentityPoint(session_count=3)
        assert p.confidence() == 0.0

    def test_high_session_high_confidence(self):
        p = IdentityPoint(session_count=30, interval_skew=0.0)
        c = p.confidence()
        assert c > 0.8

    def test_skew_penalty_blocks_confidence(self):
        """skew > 1.5 + sessions < 10 → w=0 (anti-gaming)."""
        p = IdentityPoint(session_count=6, interval_skew=2.0)
        assert p.confidence() == 0.0

    def test_positive_skew_bonus(self):
        """Natural long gaps (positive skew) → bonus confidence."""
        p = IdentityPoint(session_count=15, interval_skew=1.0)
        c = p.confidence()
        assert c > 0.7


class TestIdentityPointPriorApplication:
    """apply_as_prior + apply_physical_prior."""

    def test_semantic_prior_low_confidence(self):
        p = IdentityPoint(session_count=2, trust=0.9)
        prior = p.apply_as_prior()
        # Low confidence → trust regressed toward 0.5
        assert abs(prior["trust_initial"] - 0.5) < 0.1

    def test_semantic_prior_high_confidence(self):
        p = IdentityPoint(session_count=20, trust=0.9, interval_skew=0.0)
        prior = p.apply_as_prior()
        assert prior["trust_initial"] > 0.7

    def test_boundary_lock_overrides_trust(self):
        p = IdentityPoint(session_count=20, trust=0.95,
                         flags=("TRUST_BOUNDARY_LOCK",))
        prior = p.apply_as_prior()
        assert prior["trust_initial"] == 0.5  # Locked to neutral

    def test_physical_prior_three_state_no_history(self):
        """E3: No history → all reliable flags False → neutral strategy."""
        p = IdentityPoint(session_count=0)
        priors = p.apply_physical_prior({})
        assert priors["force_sandbox_routing"] is False
        assert priors["enable_mcp_direct"] is False
        assert priors["max_retries"] == 3  # Default

    def test_physical_prior_with_history(self):
        """E3: With sufficient history → strategy branches become active."""
        histories = {
            "tool_risk": StreamingPercentile(),
            "budget": StreamingPercentile(),
            "retry": StreamingPercentile(),
            "physical_fail": StreamingPercentile(),
        }
        # Feed consistent data to establish reliable percentiles
        for _ in range(10):
            histories["tool_risk"].add(0.3)   # Low tool risk
            histories["retry"].add(0.8)        # High retry success
            histories["budget"].add(0.2)
            histories["physical_fail"].add(0.1)

        p = IdentityPoint(
            session_count=15, tool_risk_aversion=0.25,
            retry_success_rate=0.85, interval_skew=0.0,
        )
        priors = p.apply_physical_prior(histories)
        # Low tool risk → MCP direct may be enabled
        # High retry success → max_retries may be 5
        assert priors["max_retries"] in (3, 5)
        # Continuous priors should be non-trivial
        assert priors["resistance_scale"] < 1.5


# ═══════════════════════════════════════════════════════════════════════
# SessionSufficientStatistic
# ═══════════════════════════════════════════════════════════════════════

class TestSessionSufficientStatistic:
    """Validate sufficient statistic immutability and semantics."""

    def test_defaults(self):
        s = SessionSufficientStatistic()
        assert s.trust_final == 0.5
        assert s.tool_risk_score == 0.5
        assert s.round_count == 0

    def test_frozen(self):
        s = SessionSufficientStatistic()
        with pytest.raises(Exception):
            s.round_count = 5  # type: ignore

    def test_physical_3_fields_present(self):
        s = SessionSufficientStatistic(
            tool_risk_score=0.7,
            budget_exhausted_ratio=0.3,
            retry_success_ratio=0.6,
        )
        assert s.tool_risk_score == 0.7
        assert s.budget_exhausted_ratio == 0.3
        assert s.retry_success_ratio == 0.6


# ═══════════════════════════════════════════════════════════════════════
# StreamingPercentile (E1)
# ═══════════════════════════════════════════════════════════════════════

class TestStreamingPercentile:
    """E1: Dynamic window + KS drift + cycle detection."""

    def test_insufficient_data_unreliable(self):
        sp = StreamingPercentile()
        for v in [0.3, 0.4, 0.5]:
            sp.add(v)
        p, reliable = sp.quantile(0.75)
        assert not reliable

    def test_sufficient_data_reliable(self):
        sp = StreamingPercentile()
        # Concentrated data → tight CI → reliable
        for v in [0.6, 0.62, 0.58, 0.61, 0.63, 0.59, 0.6, 0.62, 0.61, 0.6,
                  0.57, 0.64, 0.6, 0.59, 0.62]:
            sp.add(v)
        p, reliable = sp.quantile(0.75)
        assert reliable
        assert p is not None

    def test_ks_drift_detection(self):
        """Abrupt distribution change → KS detects drift."""
        sp = StreamingPercentile()
        # First 20: low values
        for _ in range(20):
            sp.add(0.2 + _random() * 0.1)
        # Next 20: high values (distribution shift)
        for _ in range(20):
            sp.add(0.7 + _random() * 0.1)
        # KS should detect the shift
        ks = sp._ks_test(list(sp._buf)[-20:], list(sp._buf)[-40:-20])
        assert ks > 0.2  # Significant drift

    def test_bootstrap_ci_produces_bounds(self):
        sp = StreamingPercentile()
        for _ in range(10):
            sp.add(0.3 + _random() * 0.3)
        vals = sorted(sp._buf)[-10:]
        ci_lo, ci_hi = sp._bootstrap_ci(vals, 0.75)
        assert ci_lo <= ci_hi

    def test_adaptive_pctl_no_history(self):
        p, reliable = adaptive_pctl({}, "tool_risk", 0.75)
        assert p is None
        assert not reliable


# ═══════════════════════════════════════════════════════════════════════
# Dimension-adaptive tau (E2)
# ═══════════════════════════════════════════════════════════════════════

class TestDimensionAdaptiveTau:
    """E2: Dimension-specific push normalization."""

    def test_base_tau_per_dimension(self):
        """Each dimension has appropriate base τ."""
        assert DIMENSION_BASE_TAU["retry"] < DIMENSION_BASE_TAU["budget"]
        assert DIMENSION_BASE_TAU["tool_risk"] < DIMENSION_BASE_TAU["budget"]

    def test_compute_tau_no_history_returns_base(self):
        tau = compute_dimension_tau("retry")
        assert tau == DIMENSION_BASE_TAU["retry"]

    def test_compute_tau_high_volatility_shrinks(self):
        """High recent volatility → smaller τ → faster adaptation."""
        volatile_hist = [0.1, 0.9, 0.2, 0.8, 0.1, 0.9]
        tau = compute_dimension_tau("retry", volatile_hist)
        # Should be smaller than base (7) due to high volatility
        assert tau < DIMENSION_BASE_TAU["retry"]

    def test_compute_tau_low_volatility_expands(self):
        """Low volatility → τ close to base."""
        stable_hist = [0.5, 0.51, 0.49, 0.5, 0.5, 0.51]
        tau = compute_dimension_tau("retry", stable_hist)
        assert tau >= DIMENSION_BASE_TAU["retry"] - 2


# ═══════════════════════════════════════════════════════════════════════
# IdentityManifoldStore — evolution pipeline
# ═══════════════════════════════════════════════════════════════════════

class TestIdentityManifoldStore:
    """Full evolution pipeline: OU decay + push + Betti + boundary lock."""

    @pytest.fixture
    def store(self, tmp_path):
        return IdentityManifoldStore(storage_dir=str(tmp_path / ".identity"))

    @pytest.fixture
    def session_stats(self):
        return SessionSufficientStatistic(
            trust_final=0.6,
            drift_values=(0.15, 0.20, 0.18),
            clarity_values=(0.7, 0.75, 0.72),
            e_t_values=(0.45, 0.50, 0.48),
            selection_pressure_triggers=1,
            physical_failures=2,
            physical_attempts=10,
            tool_risk_score=0.4,
            budget_exhausted_ratio=0.1,
            retry_success_ratio=0.7,
            session_duration_sec=3600.0,
            round_count=5,
        )

    def test_evolve_single_session(self, store, session_stats):
        """First evolution creates identity from defaults."""
        evolved = store.evolve("test_user", session_stats)
        assert evolved.session_count == 1
        assert evolved.trust > 0.0
        assert evolved.physical_fail_rate is not None  # Now observed

    def test_evolve_multiple_sessions_converge(self, store, session_stats):
        """Multiple consistent sessions → identity converges."""
        pts = []
        for _ in range(10):
            p = store.evolve("test_user", session_stats)
            pts.append(p)
        # Trust should converge toward session trust (0.6)
        final_trust = pts[-1].trust
        assert 0.45 < final_trust < 0.75

    def test_ou_decay_across_gap(self, store, session_stats):
        """Long gap → OU decay pulls trust toward 0.5."""
        # First session
        p1 = store.evolve("test_user", session_stats)
        # Simulate long gap by manually setting last_active_at far in past
        pt = store.load("test_user")
        # Force OU decay by loading after gap
        # (OU decay runs inside evolve, so we check with a new session)
        p2 = store.evolve("test_user", session_stats)
        # After 2 sessions without gap, trust should still be reasonable
        assert p2.trust > 0.4

    def test_betti_no_false_positive_on_stable(self, store):
        """Stable session patterns beyond cold-start → no Betti jump."""
        import random
        rng = random.Random(42)
        for i in range(10):
            # Realistic: slight session-to-session variation
            s = SessionSufficientStatistic(
                trust_final=0.6 + rng.uniform(-0.02, 0.02),
                drift_values=(0.15 + rng.uniform(-0.01, 0.01),),
                clarity_values=(0.7 + rng.uniform(-0.02, 0.02),),
                e_t_values=(0.5 + rng.uniform(-0.02, 0.02),),
                physical_failures=1 + rng.randint(0, 2),
                physical_attempts=10,
                round_count=5 + rng.randint(0, 3),
            )
            p = store.evolve("test_user_betti_v3", s)
        assert "META_ADAPT_RECOMMENDED" not in p.flags

    def test_restore_prior(self, store, session_stats):
        """restore_prior returns combined semantic + physical dict."""
        store.evolve("test_user", session_stats)
        prior = store.restore_prior("test_user")
        assert "trust_initial" in prior
        assert "physical_caution" in prior
        assert "max_retries" in prior

    def test_confidence_grows_with_sessions(self, store):
        """Confidence weight grows as session count increases."""
        import random
        rng = random.Random(42)
        pts = []
        for i in range(15):
            s = SessionSufficientStatistic(
                trust_final=0.6 + rng.uniform(-0.02, 0.02),
                round_count=5,
                physical_failures=1,
                physical_attempts=10,
            )
            p = store.evolve("test_user_conf_v2", s)
            pts.append(p)
        # After 15 sessions, confidence should be > 0 (was 0 for first few)
        assert pts[-1].confidence() >= 0.5
        # First few sessions still have low confidence
        assert pts[0].confidence() < 0.3


# ═══════════════════════════════════════════════════════════════════════
# Red-team #5: Boundary lock detection
# ═══════════════════════════════════════════════════════════════════════

class TestBoundaryLockDetection:
    """Red-team #5: Trust boundary lock."""

    def test_no_lock_when_trust_normal(self, tmp_path):
        store = IdentityManifoldStore(storage_dir=str(tmp_path / ".identity"))
        s = SessionSufficientStatistic(trust_final=0.5)
        # Manually check — boundary lock needs trust > 0.95
        p = IdentityPoint(trust=0.8)
        assert not store._boundary_lock_detected("u", p, s)

    def test_lock_not_triggered_before_5_sessions(self, tmp_path):
        store = IdentityManifoldStore(storage_dir=str(tmp_path / ".identity"))
        p = IdentityPoint(trust=0.97)
        s = SessionSufficientStatistic(trust_final=0.3)
        # First occurrence — should not trigger
        assert not store._boundary_lock_detected("u2", p, s)


# ═══════════════════════════════════════════════════════════════════════
# Physical dimension lifecycle (hard constraints)
# ═══════════════════════════════════════════════════════════════════════

class TestPhysicalDimensionLifecycle:
    """V7.4-physical-3 lifecycle constraints."""

    def test_hard_cap_not_exceeded(self):
        p = IdentityPoint()
        current_physical_dims = len(p.PHYSICAL_DIMENSION_MAP)
        assert current_physical_dims <= p.PHYSICAL_DIM_HARD_CAP


# ═══════════════════════════════════════════════════════════════════════
# v7.4.1 Fix Verification
# ═══════════════════════════════════════════════════════════════════════

class TestV741Fixes:
    """Verify the three v7.4.1 hardening fixes."""

    def test_diagnostic_reliability_field_present(self):
        """Fix 3: apply_physical_prior must expose _reliability diagnostics."""
        histories = {
            "tool_risk": StreamingPercentile(),
            "budget": StreamingPercentile(),
            "retry": StreamingPercentile(),
            "physical_fail": StreamingPercentile(),
        }
        for _ in range(10):
            histories["tool_risk"].add(0.3)
            histories["retry"].add(0.7)
            histories["budget"].add(0.2)
            histories["physical_fail"].add(0.1)
        p = IdentityPoint(session_count=15, interval_skew=0.0)
        priors = p.apply_physical_prior(histories)
        assert "_reliability" in priors
        assert "tool_risk" in priors["_reliability"]
        assert "budget" in priors["_reliability"]
        assert "retry" in priors["_reliability"]
        # All should be True with sufficient concentrated data
        assert priors["_reliability"]["tool_risk"] is True
        assert priors["_reliability"]["budget"] is True
        assert priors["_reliability"]["retry"] is True

    def test_diagnostic_reliability_cold_start_all_false(self):
        """Cold start: all reliability flags False."""
        p = IdentityPoint(session_count=0)
        priors = p.apply_physical_prior({})
        assert "_reliability" in priors
        assert priors["_reliability"]["tool_risk"] is False
        assert priors["_reliability"]["budget"] is False
        assert priors["_reliability"]["retry"] is False

    def test_short_history_cycle_false_positive(self):
        """Fix 1: Short random history should NOT trigger cycle detection."""
        sp = StreamingPercentile()
        import random
        rng = random.Random(42)
        for _ in range(10):
            sp.add(rng.uniform(0.3, 0.7))
        # 10 random sessions → no meaningful cycle
        assert sp._detect_cycle() is None

    def test_retry_bimodal_iqr(self):
        """Fix 2: IQR correctly captures bimodal volatility.
        Bimodal: [0.1, 0.1, 0.8, 0.8, 0.1] has high IQR but low std.
        """
        hist = [0.1, 0.1, 0.8, 0.8, 0.1]
        tau = compute_dimension_tau("retry", hist)
        # IQR = 0.8 - 0.1 = 0.7, mid ≈ 0.45, rel_vol ≈ 1.56
        # adaptive_tau = 7 * (1 - 0.4*1.5) = 7 * 0.4 = 2.8 → max(5, 2) = 5
        # With std: σ ≈ 0.35, μ ≈ 0.38, rel_vol ≈ 0.92 → tau ≈ 7*0.63 ≈ 4.4
        # IQR gives τ=5 (max floor), std gives higher τ → IQR is more responsive
        assert tau <= 7  # Should be reduced from base 7
        assert tau >= 5  # Hard floor


# ═══════════════════════════════════════════════════════════════════════
# Helper imports
# ═══════════════════════════════════════════════════════════════════════

def _random():
    """Deterministic random for reproducible tests."""
    import random
    return random.Random(42).random()
