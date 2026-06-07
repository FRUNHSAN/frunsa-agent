"""PersonalizedThresholdLearner — V2.1: online learning without neural nets.

EMA-based threshold personalization. Learns per-user trigger points
from explicit and implicit feedback. No PyTorch, no GPU, just math.

Architecture:
  Learner (this file) ← FeedbackListener ← run_live.py
       ↓                                        ↑
  SQLite persistence ←────────────────── user feedback signals

Interface:
  ThresholdLearner (Protocol) — decoupled for future NN replacement.
  EMALearner (implementation) — current production learner.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol


# ── Frozen interface — decoupled for future NN/RL replacement ──

class ThresholdLearner(Protocol):
    """Decoupled interface for personalized threshold learning.

    Replace with NeuralLearner, RLLearner, or any future implementation.
    Only requirement: implement update() and get().
    """

    def update(self, dimension: str, triggered_score: float, alpha: float = 0.2) -> float:
        """Learn from a trigger event. Returns new threshold."""
        ...

    def get(self, dimension: str) -> float:
        """Get current personalized threshold for this dimension."""
        ...

    def save(self) -> None:
        """Persist learned thresholds."""
        ...


# ── EMA implementation ──

DEFAULT_THRESHOLDS = {
    "fatigue": 0.55,
    "frustration": 0.55,
    "gratitude": 0.45,
    "curiosity": 0.40,
}

GUARDRAILS = {
    "fatigue": (0.30, 0.80),
    "frustration": (0.30, 0.80),
    "gratitude": (0.30, 0.70),
    "curiosity": (0.25, 0.65),
}


class EMALearner:
    """EMA-based personalized threshold learner.

    new_threshold = (1 - alpha) * old + alpha * triggered_score
    Then clamped to guardrails.

    Usage:
        learner = EMALearner(user_id="frunhsan", db_path="profiles.db")
        new_t = learner.update("fatigue", 0.42, alpha=0.2)
        # → 0.524 (shifted down from 0.55 because user was triggered at 0.42)
    """

    def __init__(self, user_id: str, db_path: str = "thresholds.db") -> None:
        self._user_id = user_id
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS personalized_thresholds ("
            "  user_id TEXT NOT NULL,"
            "  dimension TEXT NOT NULL,"
            "  threshold REAL NOT NULL,"
            "  samples INTEGER DEFAULT 0,"
            "  updated_at TEXT DEFAULT (datetime('now')),"
            "  PRIMARY KEY (user_id, dimension)"
            ")"
        )
        self._conn.commit()

    def get(self, dimension: str) -> float:
        row = self._conn.execute(
            "SELECT threshold FROM personalized_thresholds "
            "WHERE user_id = ? AND dimension = ?",
            (self._user_id, dimension),
        ).fetchone()
        if row:
            return float(row[0])
        return DEFAULT_THRESHOLDS.get(dimension, 0.50)

    def update(self, dimension: str, triggered_score: float, alpha: float = 0.2) -> float:
        current = self.get(dimension)
        # EMA formula
        new_threshold = (1 - alpha) * current + alpha * triggered_score
        # Apply guardrails
        lo, hi = GUARDRAILS.get(dimension, (0.20, 0.90))
        new_threshold = max(lo, min(hi, new_threshold))

        self._conn.execute(
            "INSERT OR REPLACE INTO personalized_thresholds "
            "(user_id, dimension, threshold, samples) "
            "VALUES (?, ?, ?, "
            " COALESCE((SELECT samples FROM personalized_thresholds "
            "  WHERE user_id = ? AND dimension = ?), 0) + 1"
            ")",
            (self._user_id, dimension, new_threshold, self._user_id, dimension),
        )
        self._conn.commit()
        return new_threshold

    def sample_count(self, dimension: str) -> int:
        row = self._conn.execute(
            "SELECT samples FROM personalized_thresholds "
            "WHERE user_id = ? AND dimension = ?",
            (self._user_id, dimension),
        ).fetchone()
        return int(row[0]) if row else 0

    def save(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def restore_thresholds(self, saved: dict[str, float]) -> None:
        """Phase 8b: restore thresholds from a previous session snapshot."""
        for dim, val in saved.items():
            lo, hi = GUARDRAILS.get(dim, (0.20, 0.90))
            val = max(lo, min(hi, float(val)))
            self._conn.execute(
                "INSERT OR REPLACE INTO personalized_thresholds "
                "(user_id, dimension, threshold, samples, updated_at) "
                "VALUES (?, ?, ?, 1, datetime('now'))",
                (self._user_id, dim, val),
            )
        self._conn.commit()

    def get_all_thresholds(self) -> dict[str, float]:
        return {dim: self.get(dim) for dim in DEFAULT_THRESHOLDS}
