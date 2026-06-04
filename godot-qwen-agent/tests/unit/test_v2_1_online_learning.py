"""V2.1 Online Learning tests: EMA math, guardrails, persistence, interface."""

import os
import tempfile
import pytest
from core.adapters.threshold_learner import EMALearner, DEFAULT_THRESHOLDS, GUARDRAILS
from core.adapters.feedback_listener import FeedbackListener


class TestEMALearner:
    """EMA math and guardrails."""

    def test_default_threshold_returned_before_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        assert learner.get("fatigue") == DEFAULT_THRESHOLDS["fatigue"]

    def test_ema_reduces_threshold_on_low_trigger(self):
        """User triggered at 0.42 → threshold should shift down from 0.55."""
        learner = EMALearner("test", db_path=":memory:")
        new_t = learner.update("fatigue", 0.42, alpha=0.2)
        expected = 0.8 * 0.55 + 0.2 * 0.42  # 0.524
        assert abs(new_t - expected) < 0.001

    def test_ema_increases_threshold_on_high_trigger(self):
        """User triggered at 0.70 → threshold should shift up from 0.55."""
        learner = EMALearner("test", db_path=":memory:")
        new_t = learner.update("fatigue", 0.70, alpha=0.2)
        expected = 0.8 * 0.55 + 0.2 * 0.70  # 0.580
        assert abs(new_t - expected) < 0.001

    def test_ema_converges_over_many_updates(self):
        """Repeated updates at same value should converge."""
        learner = EMALearner("test", db_path=":memory:")
        for _ in range(20):
            learner.update("fatigue", 0.42, alpha=0.2)
        final = learner.get("fatigue")
        assert abs(final - 0.42) < 0.02  # Converged near 0.42

    def test_guardrail_lower_bound(self):
        """Threshold must not go below minimum."""
        learner = EMALearner("test", db_path=":memory:")
        for _ in range(50):
            learner.update("fatigue", 0.01, alpha=0.5)
        assert learner.get("fatigue") >= GUARDRAILS["fatigue"][0]

    def test_guardrail_upper_bound(self):
        """Threshold must not go above maximum."""
        learner = EMALearner("test", db_path=":memory:")
        for _ in range(50):
            learner.update("fatigue", 0.99, alpha=0.5)
        assert learner.get("fatigue") <= GUARDRAILS["fatigue"][1]

    def test_sample_count_increments(self):
        learner = EMALearner("test", db_path=":memory:")
        assert learner.sample_count("fatigue") == 0
        learner.update("fatigue", 0.5)
        assert learner.sample_count("fatigue") == 1
        learner.update("fatigue", 0.6)
        assert learner.sample_count("fatigue") == 2

    def test_persistence_across_instances(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            l1 = EMALearner("user_a", db_path=db)
            l1.update("fatigue", 0.42, alpha=0.2)
            l1.close()

            l2 = EMALearner("user_a", db_path=db)
            assert abs(l2.get("fatigue") - 0.524) < 0.01
            l2.close()
        finally:
            os.unlink(db)

    def test_independent_per_user(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            a = EMALearner("user_a", db_path=db)
            b = EMALearner("user_b", db_path=db)
            a.update("fatigue", 0.42, alpha=0.5)
            assert a.get("fatigue") != b.get("fatigue")
            a.close()
            b.close()
        finally:
            os.unlink(db)

    def test_independent_per_dimension(self):
        learner = EMALearner("test", db_path=":memory:")
        learner.update("fatigue", 0.42)
        assert abs(learner.get("fatigue") - 0.524) < 0.01
        assert learner.get("frustration") == DEFAULT_THRESHOLDS["frustration"]

    def test_get_all_thresholds(self):
        learner = EMALearner("test", db_path=":memory:")
        all_t = learner.get_all_thresholds()
        assert "fatigue" in all_t
        assert "frustration" in all_t
        assert "gratitude" in all_t
        assert "curiosity" in all_t

    def test_all_dimensions_have_guardrails(self):
        """Every default dimension must have guardrail limits."""
        for dim in DEFAULT_THRESHOLDS:
            assert dim in GUARDRAILS, f"{dim} missing guardrails"
            lo, hi = GUARDRAILS[dim]
            assert lo < hi
            assert lo >= 0.0
            assert hi <= 1.0


class TestFeedbackListener:
    """Explicit and implicit feedback routing."""

    def test_explicit_down_triggers_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "字少点，太啰嗦了",
            {"dimension": "fatigue", "score": 0.42},
        )
        assert result is not None
        assert result["dimension"] == "fatigue"
        assert result["alpha"] == 0.25

    def test_explicit_up_triggers_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "详细点，展开讲讲",
            {"dimension": "frustration", "score": 0.60},
        )
        assert result is not None
        assert result["alpha"] == 0.20

    def test_implicit_bored_triggers_weak_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "哦",
            {"dimension": "fatigue", "score": 0.50},
            prev_response_len=500,
        )
        assert result is not None
        assert result["alpha"] == 0.05

    def test_implicit_engaged_triggers_weak_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "然后呢",
            {"dimension": "curiosity", "score": 0.60},
            prev_response_len=30,
        )
        assert result is not None
        assert result["alpha"] == 0.05

    def test_short_response_no_long_output_no_learning(self):
        """'哦' to short response → not boredom, no learning."""
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "哦",
            {"dimension": "fatigue", "score": 0.50},
            prev_response_len=50,
        )
        assert result is None

    def test_no_signal_no_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "字少点",
            {"dimension": None, "score": 0.0},
        )
        assert result is None

    def test_neutral_input_no_learning(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        result = listener.on_user_input(
            "今天天气不错",
            {"dimension": "fatigue", "score": 0.60},
        )
        assert result is None

    def test_stats_count(self):
        learner = EMALearner("test", db_path=":memory:")
        listener = FeedbackListener(learner)
        listener.on_user_input("字少点", {"dimension": "fatigue", "score": 0.42})
        listener.on_user_input("哦", {"dimension": "fatigue", "score": 0.50}, prev_response_len=300)
        assert listener.stats.get("explicit", 0) >= 1
        assert listener.stats.get("implicit", 0) >= 1
