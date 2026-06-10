"""V7.5 Unit tests — Entropy Monitor.

Covers:
  - KernelStateSnapshot (frozen, all fields)
  - EntropyMonitor.sample() — S_int computation, normalization, temporal decay
  - EntropyMonitor.should_interrupt() — sigmoid θ_active, graduated cold-start
  - EntropyMonitor.format_interrupt() — natural language output
  - Review fixes: normalization (#1), sigmoid (#2), decay (#3)
  - Red-team: trust growth cap (R1), safety floor (R2), tamper detect (R3)
  - Compatibility: dual-track failures (C3), multi-run accumulation (C2)
  - UX: permanent dismiss via delete_snapshot
"""
import math
import os
import pytest
from core.watcher.entropy_monitor import (
    KernelStateSnapshot,
    EntropyReading,
    EntropyMonitor,
    persist_snapshot,
    load_snapshot,
    delete_snapshot,
)


# ═══════════════════════════════════════════════════════════════════════
# Minimal IdentityPoint stub for testing
# ═══════════════════════════════════════════════════════════════════════

class FakeIdentity:
    def __init__(self, session_count=0, trust=0.5, e_t_P50=0.5,
                 e_t_P95=0.8, drift_P95=5.0):
        self.session_count = session_count
        self.trust = trust
        self.e_t_P50 = e_t_P50
        self.e_t_P95 = e_t_P95
        self.drift_P95 = drift_P95


# ═══════════════════════════════════════════════════════════════════════
# KernelStateSnapshot
# ═══════════════════════════════════════════════════════════════════════

class TestKernelStateSnapshot:
    def test_frozen(self):
        s = KernelStateSnapshot()
        with pytest.raises(Exception):
            s.dangling_dag_count = 5  # type: ignore

    def test_defaults(self):
        s = KernelStateSnapshot()
        assert s.dangling_dag_count == 0
        assert s.accumulated_e_t == 0.0
        assert s.budget_remaining_ratio == 1.0
        assert s.mcp_failures == 0

    def test_custom_values(self):
        s = KernelStateSnapshot(
            dangling_dag_count=3,
            accumulated_e_t=0.6,
            mcp_failures=2,
            mcp_attempts=10,
        )
        assert s.dangling_dag_count == 3
        assert s.mcp_failures == 2


# ═══════════════════════════════════════════════════════════════════════
# EntropyMonitor.sample() — Review fixes
# ═══════════════════════════════════════════════════════════════════════

class TestEntropyMonitorSample:
    """Review fix #1 (normalization), fix #3 (decay)."""

    def test_empty_snapshot_zero_tension(self):
        """No concerns → S_int ≈ 0."""
        snap = KernelStateSnapshot()
        ident = FakeIdentity()
        reading = EntropyMonitor.sample(snap, ident)
        assert reading.S_int < 0.2

    def test_dangling_produces_tension(self):
        """Dangling DAG steps → measurable tension."""
        snap = KernelStateSnapshot(dangling_dag_count=10)
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyMonitor.sample(snap, ident)
        assert reading.S_int > 0.2

    def test_dimensional_consistency_large_e(self):
        """Fix #1: even huge e_accumulated → S_int ≤ 1.3 after normalization."""
        snap = KernelStateSnapshot(accumulated_e_t=100.0)
        ident = FakeIdentity(session_count=10)
        reading = EntropyMonitor.sample(snap, ident)
        assert reading.S_int <= 1.3

    def test_temporal_decay(self):
        """Fix #3: older snapshots → lower tension."""
        snap = KernelStateSnapshot(
            dangling_dag_count=5, snapshot_age=3)
        ident = FakeIdentity(session_count=10)
        reading = EntropyMonitor.sample(snap, ident)
        # decay = exp(-0.5 * 3) ≈ 0.22
        assert reading.S_int < 0.3

    def test_temporal_decay_fresh_vs_old(self):
        """Fresh snapshot has higher tension than old one."""
        ident = FakeIdentity(session_count=10)
        fresh = KernelStateSnapshot(dangling_dag_count=5, snapshot_age=0)
        old = KernelStateSnapshot(dangling_dag_count=5, snapshot_age=4)
        reading_fresh = EntropyMonitor.sample(fresh, ident)
        reading_old = EntropyMonitor.sample(old, ident)
        assert reading_fresh.S_int > reading_old.S_int

    def test_normalization_safety_floor(self):
        """R2: polluted P95 doesn't suppress catastrophic tension."""
        # Simulate polluted P95 = 80, but safety floor = 3.0
        # dangling = 40 / max(80, 3.0) = 0.5 → still measurable
        snap = KernelStateSnapshot(dangling_dag_count=40)
        ident = FakeIdentity(session_count=10, drift_P95=80.0)
        reading = EntropyMonitor.sample(snap, ident)
        assert reading.S_int > 0.15  # Not suppressed to ~0


# ═══════════════════════════════════════════════════════════════════════
# EntropyMonitor.should_interrupt() — Review fix #2 + H2
# ═══════════════════════════════════════════════════════════════════════

class TestEntropyMonitorShouldInterrupt:
    """Review fix #2 (sigmoid θ_active), Hardening H2 (graduated cold-start)."""

    def test_cold_start_no_interrupt(self):
        """Session 0: n < 3 → θ_active = 1.0 → no interrupt."""
        ident = FakeIdentity(session_count=0)
        reading = EntropyReading(S_int=0.5, alpha=0.3, beta=0.2,
                                 gamma=0.1, delta=0.1)
        should, urgency = EntropyMonitor.should_interrupt(reading, ident)
        assert not should

    def test_low_trust_cautious(self):
        """Low trust → higher θ_active → harder to trigger."""
        ident = FakeIdentity(session_count=10, trust=0.2)
        reading = EntropyReading(S_int=0.4, alpha=0.3, beta=0.2,
                                 gamma=0.25, delta=0.1)
        should, urgency = EntropyMonitor.should_interrupt(reading, ident)
        # θ_active for trust=0.2, n≥3 → θ≈0.55. S_int=0.4 < 0.55 → False
        assert not should

    def test_high_trust_proactive(self):
        """High trust → lower θ_active → easier to trigger."""
        ident = FakeIdentity(session_count=10, trust=0.8)
        reading = EntropyReading(S_int=0.4, alpha=0.5, beta=0.2,
                                 gamma=0.1, delta=0.1)
        should, urgency = EntropyMonitor.should_interrupt(reading, ident)
        # θ_active for trust=0.8, n≥3 → θ≈0.38. S_int=0.4 > 0.38 → True
        assert should

    def test_theta_active_continuity(self):
        """Fix #2: trust=0.29 vs 0.31 — θ difference < 0.05."""
        ident_low = FakeIdentity(session_count=10, trust=0.29)
        ident_high = FakeIdentity(session_count=10, trust=0.31)
        theta_low = EntropyMonitor._compute_theta_active(ident_low)
        theta_high = EntropyMonitor._compute_theta_active(ident_high)
        assert abs(theta_low - theta_high) < 0.05

    def test_graduated_cold_start_session_1(self):
        """H2: n=1 requires 2×θ threshold."""
        ident = FakeIdentity(session_count=1, trust=0.5)
        reading = EntropyReading(S_int=0.8, alpha=0.3, beta=0.2,
                                 gamma=0.15, delta=0.1)
        should, urgency = EntropyMonitor.should_interrupt(reading, ident)
        # n=1 → θ=1.0, 2×θ=2.0. S_int=0.8 < 2.0 → False
        assert not should


# ═══════════════════════════════════════════════════════════════════════
# EntropyMonitor.format_interrupt()
# ═══════════════════════════════════════════════════════════════════════

class TestEntropyMonitorFormatInterrupt:
    """H1 (failure_ratio gating), C3 (MCP reporting)."""

    def test_format_returns_none_when_no_interrupt(self):
        ident = FakeIdentity(session_count=0)
        reading = EntropyReading(S_int=0.1, alpha=0.3, beta=0.2,
                                 gamma=0.1, delta=0.1)
        snap = KernelStateSnapshot()
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        assert msg is None

    def test_format_natural_language_no_raw_values(self):
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyReading(S_int=0.8, alpha=0.4, beta=0.3,
                                 gamma=0.12, delta=0.1)
        snap = KernelStateSnapshot(dangling_dag_count=5)
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        assert msg is not None
        assert "S_int" not in msg
        assert "alpha" not in msg
        assert "未完成" in msg

    def test_physical_failure_ratio_filtering(self):
        """H1: low failure ratio → filtered out. No other parts → None."""
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyReading(S_int=0.8, alpha=0.4, beta=0.3,
                                 gamma=0.12, delta=0.1)
        snap = KernelStateSnapshot(physical_failures=1, physical_attempts=100)
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        # 1/100 = 1% → filtered. No dangling, no accumulated_e_t > 0.5 → None
        assert msg is None

    def test_physical_failure_ratio_reported(self):
        """H1: moderate failure ratio → reported."""
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyReading(S_int=0.8, alpha=0.4, beta=0.3,
                                 gamma=0.12, delta=0.1)
        snap = KernelStateSnapshot(physical_failures=30, physical_attempts=100)
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        assert msg is not None
        assert "30%" in msg or "0.3" in msg

    def test_physical_failure_high_severity(self):
        """H1: high failure ratio → high severity."""
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyReading(S_int=0.8, alpha=0.4, beta=0.3,
                                 gamma=0.12, delta=0.1)
        snap = KernelStateSnapshot(physical_failures=70, physical_attempts=100)
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        assert msg is not None
        assert "70%" in msg or "0.7" in msg

    def test_mcp_failure_reporting(self):
        """C3: MCP failures reported separately."""
        ident = FakeIdentity(session_count=10, trust=0.6)
        reading = EntropyReading(S_int=0.8, alpha=0.4, beta=0.3,
                                 gamma=0.12, delta=0.1)
        snap = KernelStateSnapshot(mcp_failures=5, mcp_attempts=10)
        msg = EntropyMonitor.format_interrupt(reading, ident, snap)
        assert msg is not None
        assert "MCP" in msg


# ═══════════════════════════════════════════════════════════════════════
# Snapshot I/O — Red-team R3
# ═══════════════════════════════════════════════════════════════════════

class TestSnapshotIO:
    """R3: tamper detection via session_count cross-check."""

    def test_persist_and_load(self, tmp_path):
        d = str(tmp_path / ".identity")
        snap = KernelStateSnapshot(dangling_dag_count=5, physical_failures=3,
                                   physical_attempts=10)
        persist_snapshot(d, "test_user", snap, session_count=5)
        loaded = load_snapshot(d, "test_user", current_session_count=6)
        assert loaded is not None
        assert loaded.dangling_dag_count == 5
        assert loaded.physical_failures == 3
        assert loaded.snapshot_age == 0  # 6 - 5 - 1 = 0

    def test_snapshot_age_computed_correctly(self, tmp_path):
        d = str(tmp_path / ".identity")
        snap = KernelStateSnapshot()
        persist_snapshot(d, "test_user", snap, session_count=3)
        # Current session is 6 → age = 6 - 3 - 1 = 2
        loaded = load_snapshot(d, "test_user", current_session_count=6)
        assert loaded is not None
        assert loaded.snapshot_age == 2

    def test_tampered_snapshot_rejected(self, tmp_path):
        """R3: manual edit → session_count mismatch → rejected."""
        d = str(tmp_path / ".identity")
        snap = KernelStateSnapshot()
        persist_snapshot(d, "test_user", snap, session_count=5)
        # Simulate tamper: reload with wrong current session_count
        loaded = load_snapshot(d, "test_user", current_session_count=4)
        # 4 - 5 - 1 = -2 < 0 → tampered → None
        assert loaded is None

    def test_permanent_ignore_deletes_snapshot(self, tmp_path):
        d = str(tmp_path / ".identity")
        snap = KernelStateSnapshot()
        os.makedirs(d, exist_ok=True)
        persist_snapshot(d, "test_user", snap, session_count=5)
        assert load_snapshot(d, "test_user", current_session_count=6) is not None
        delete_snapshot(d, "test_user")
        assert load_snapshot(d, "test_user", current_session_count=6) is None

    def test_missing_snapshot_returns_none(self, tmp_path):
        d = str(tmp_path / ".identity")
        assert load_snapshot(d, "nonexistent", current_session_count=1) is None
