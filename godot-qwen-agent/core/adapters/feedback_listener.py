"""FeedbackListener — V2.1: capture explicit + implicit feedback for learning.

Feeds the EMALearner with (signal_score, user_reaction) pairs.
  Explicit: user says "字少点" / "别啰嗦" — strong signal, alpha=0.25
  Implicit: user replies "哦" / "嗯" to long output — weak signal, alpha=0.05

Architecture:
  SignalInterpreter → EMALearner ← FeedbackListener ← run_live.py
"""

from __future__ import annotations

from core.adapters.threshold_learner import EMALearner

# ── Explicit feedback: user commands that indicate threshold mismatch ──
EXPLICIT_DOWN_TRIGGERS = ["字少点", "别啰嗦", "太长了", "简单点", "别废话", "简洁", "精简", "少说点"]
EXPLICIT_UP_TRIGGERS = ["详细点", "展开", "多说点", "字多点", "多一点", "再讲讲"]

# ── Implicit feedback: short responses to long output suggest dissatisfaction ──
IMPLICIT_BORED = ["哦", "嗯", "行", "好", "ok", "..", "..."]
IMPLICIT_ENGAGED = ["然后呢", "继续", "有意思", "再讲讲", "展开", "为什么"]


class FeedbackListener:
    """Listens for user feedback signals and routes them to the learner.

    Usage:
        listener = FeedbackListener(learner, user_id="frunhsan")
        listener.on_user_input("字少点", prev_signal={"dimension": "fatigue", "score": 0.42})
        # → learner.update("fatigue", 0.42, alpha=0.25)
        # → fatigue threshold drops toward 0.42
    """

    def __init__(self, learner: EMALearner) -> None:
        self._learner = learner
        self._stats: dict[str, int] = {"explicit": 0, "implicit": 0}

    def on_user_input(
        self, user_text: str, prev_signal: dict, prev_response_len: int = 0,
    ) -> dict | None:
        """Process user input for feedback signals.

        Returns dict with learned threshold if update occurred, else None.
        """
        t = user_text.strip()

        # ── Explicit feedback ──
        if any(w in t for w in EXPLICIT_DOWN_TRIGGERS):
            return self._learn(prev_signal, alpha=0.25, reason="explicit_down")

        if any(w in t for w in EXPLICIT_UP_TRIGGERS):
            return self._learn(prev_signal, alpha=0.20, reason="explicit_up")

        # ── Implicit feedback ──
        if prev_response_len > 200 and t in IMPLICIT_BORED:
            # Long response → bored reply → threshold may be too high
            return self._learn(prev_signal, alpha=0.05, reason="implicit_bored")

        if prev_response_len < 50 and any(w in t.lower() for w in IMPLICIT_ENGAGED):
            # Short response → engaged reply → threshold may be too low
            return self._learn(prev_signal, alpha=0.05, reason="implicit_engaged")

        return None

    def _learn(self, signal: dict, alpha: float, reason: str) -> dict | None:
        dim = signal.get("dimension")
        score = signal.get("score", 0.0)
        if not dim or score < 0.3:
            return None
        new_t = self._learner.update(dim, score, alpha=alpha)
        self._stats[reason.split("_")[0]] += 1
        return {
            "dimension": dim,
            "old_threshold": round(self._learner.get(dim) - (new_t - self._learner.get(dim)), 4),
            "new_threshold": round(new_t, 4),
            "trigger_score": score,
            "alpha": alpha,
            "reason": reason,
        }

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)
