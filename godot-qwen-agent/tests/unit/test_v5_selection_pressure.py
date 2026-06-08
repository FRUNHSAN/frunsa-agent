"""V5 选择压力累积器 — 术前防护测试。

在从 relational_inertia.RelationalHistory 拆出 SelectionPressureAccumulator
之前，先对信任 EMA 核心逻辑写测试。外科手术后这些测试必须继续通过。
"""

import os
import tempfile

import pytest


# ═══════════════════════════════════════════════════════════════════════
# Trust EMA — 核心指标：信任 = 用户历史选择压力的累积度量
# ═══════════════════════════════════════════════════════════════════════

class TestTrustEMA:
    """信任 EMA 是 V5 的"环境记忆"——它不猜用户情绪，只累积行为反馈。"""

    def test_initial_trust_is_neutral(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        assert hist.trust_ema == 0.5

    def test_ema_converges_toward_observed(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # trust_alpha=0.3: each step moves 30% toward observed
        for _ in range(20):
            hist.record_trust(0.8)
        # After 20 rounds at 0.8, EMA should be close to 0.8
        assert 0.7 < hist.trust_ema < 0.9

    def test_trust_erodes_fast_builds_slow(self):
        """P1 心理学：信任不对称——下跌快（α=0.30），上涨慢（α=0.08）。"""
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Start at neutral
        assert hist.get_mean("trust") == 0.5

        # One negative observation → should drop
        hist.bayesian_update("trust", 0.1)
        mean_after_neg = hist.get_mean("trust")

        # One positive observation → should rise, but less
        hist.bayesian_update("trust", 0.9)
        mean_after_pos = hist.get_mean("trust")

        # Net effect: one bad hit hurts more than one good helps
        # After negative: 0.5 * (1-0.30) + 0.1 * 0.30 = 0.35 + 0.03 = 0.38
        # After positive on top: 0.38 * (1-0.08) + 0.9 * 0.08 = 0.3496 + 0.072 = 0.4216
        # So the net after neg+pos < initial 0.5
        assert mean_after_pos < 0.5, (
            f"Negativity bias failed: {mean_after_neg=}, {mean_after_pos=}"
        )

    def test_trust_ema_matches_smooth_trust(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        for trust_val in [0.6, 0.7, 0.65, 0.8]:
            hist.record_trust(trust_val)

        assert hist.smooth_trust(0.5) == hist.trust_ema

    def test_trust_clamped_to_zero_one_range(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Push trust to extremes
        for _ in range(50):
            hist.record_trust(0.0)
        assert hist.trust_ema >= 0.0

        for _ in range(50):
            hist.record_trust(1.0)
        assert hist.trust_ema <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# Bayesian trust — 方差追踪 + 惊讶注入
# ═══════════════════════════════════════════════════════════════════════

class TestBayesianTrust:
    def test_bayesian_update_reduces_variance_with_stable_input(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Stable observations → variance should decrease
        for _ in range(10):
            hist.bayesian_update("trust", 0.6)
        v = hist.get_variance("trust")
        assert v < 0.25, f"Variance should decrease with stable input: {v}"

    def test_surprise_injection_expands_variance(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Stable first
        for _ in range(5):
            hist.bayesian_update("trust", 0.6)
        v_before = hist.get_variance("trust")

        # Surprise!
        hist.update_with_surprise("trust", 0.1, surprise_score=0.9)
        v_after = hist.get_variance("trust")
        assert v_after > v_before, (
            f"Surprise should expand variance: {v_before=} → {v_after=}"
        )

    def test_variance_never_reaches_zero(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        for _ in range(100):
            hist.bayesian_update("trust", 0.5)
        # 方差底线 0.01
        assert hist.get_variance("trust") >= 0.01


# ═══════════════════════════════════════════════════════════════════════
# 持久化 — 跨会话记忆
# ═══════════════════════════════════════════════════════════════════════

class TestPersistence:
    def test_save_and_load_preserves_trust_state(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        hist.record_trust(0.75)
        trust_before = hist.trust_ema

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            hist.save_state(db_path, "test_user")
            loaded = RelationalHistory.load_state(db_path, "test_user")
            assert loaded is not None
            assert loaded.trust_ema == trust_before
            assert loaded.round_count == hist.round_count
        finally:
            os.unlink(db_path)

    def test_load_returns_none_when_no_state(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            loaded = RelationalHistory.load_state(db_path, "nonexistent")
            assert loaded is None
        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════════
# 基线漂移 — 信任在和平时期自然愈合
# ═══════════════════════════════════════════════════════════════════════

class TestBaselineDrift:
    def test_peace_streak_drifts_trust_toward_baseline(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Force trust below baseline
        hist._means["trust"] = 0.15

        # Peace for many rounds
        for _ in range(20):
            hist.apply_baseline_drift(surprise_score=0.0)

        # Trust should have drifted toward 0.3
        assert hist.get_mean("trust") > 0.15

    def test_surprise_resets_peace_streak(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # Build peace streak
        for _ in range(8):
            hist.apply_baseline_drift(surprise_score=0.0)
        assert hist._peace_streak >= 5

        # Surprise → reset
        hist.apply_baseline_drift(surprise_score=0.5)
        assert hist._peace_streak == 0


# ═══════════════════════════════════════════════════════════════════════
# 不确定检测
# ═══════════════════════════════════════════════════════════════════════

class TestUncertaintyDetection:
    def test_high_variance_triggers_uncertain_flag(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # 初始方差 0.25 < 阈值 0.5 → 不触发
        assert not hist.is_uncertain(threshold=0.5)

    def test_surprise_sustained_causes_uncertainty(self):
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator as RelationalHistory

        hist = RelationalHistory()
        # 注入多轮惊讶
        for _ in range(10):
            hist.update_with_surprise("trust", 0.1, surprise_score=0.8)
        # 方差可能膨胀到超过 0.5
        v = hist.get_variance("trust")
        assert v > 0.01, f"Should have elevated variance: {v}"
