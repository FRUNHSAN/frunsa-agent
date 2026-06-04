"""RelationalPatterns — V2.2: cross-session behavior pattern library.

NOT a vector database. NOT LLM-powered. Just a SQLite table and
deterministic heuristics. This is the "relationship engine" that
transforms the agent from a thermostat into something that remembers.

CBO Model: Context → Behavior → Outcome
  - Context: time-of-day, day-of-week, recent signal history
  - Behavior: what the user did (fatigue signal, explicit command)
  - Outcome: did the contract change improve the interaction?

Design:
  - Zero LLM calls. Zero vector embeddings. Zero external dependencies.
  - SQLite WAL. O(1) query. 100% deterministic.
  - Confidence threshold: >= 3 occurrences AND success > 0.8
  - Decay: patterns not triggered in 28 days have success score reduced.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime


def _context_tags() -> str:
    """Generate context tags from current time. Pure heuristics, no LLM."""
    now = datetime.now()
    tags = []
    hour = now.hour
    if 5 <= hour < 9:
        tags.append("morning")
    elif 9 <= hour < 12:
        tags.append("late_morning")
    elif 12 <= hour < 14:
        tags.append("afternoon")
    elif 14 <= hour < 18:
        tags.append("late_afternoon")
    elif 18 <= hour < 22:
        tags.append("evening")
    else:
        tags.append("night")

    dow = now.strftime("%A")  # Monday, Tuesday...
    tags.append(dow)

    if dow in ("Saturday", "Sunday"):
        tags.append("weekend")
    else:
        tags.append("weekday")

    return ",".join(tags)


class RelationalPatterns:
    """Cross-session behavior pattern storage and query.

    Usage:
        rp = RelationalPatterns("patterns.db")
        rp.record(user_id="frunhsan", behavior="fatigue_brevity",
                   action="verbose_low", success=True)
        # Later, before session start:
        hints = rp.query_active(user_id="frunhsan")
        if hints:
            print(f"Proactive hint: {hints[0]}")
    """

    def __init__(self, db_path: str = "relational_patterns.db") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS patterns ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  user_id TEXT NOT NULL,"
            "  context_tags TEXT NOT NULL,"
            "  behavior TEXT NOT NULL,"
            "  action TEXT NOT NULL,"
            "  occurrence_count INTEGER DEFAULT 1,"
            "  success_count INTEGER DEFAULT 0,"
            "  last_triggered REAL DEFAULT 0,"
            "  UNIQUE(user_id, context_tags, behavior, action)"
            ")"
        )
        self._conn.commit()

    def record(
        self, user_id: str, behavior: str, action: str,
        success: bool = True, tags: str = "",
    ) -> bool:
        """Record a behavior pattern. Returns True if newly created."""
        tags = tags or _context_tags()
        now = time.time()

        existing = self._conn.execute(
            "SELECT id, occurrence_count, success_count FROM patterns "
            "WHERE user_id = ? AND context_tags = ? AND behavior = ? AND action = ?",
            (user_id, tags, behavior, action),
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE patterns SET occurrence_count = ?, "
                "success_count = ?, last_triggered = ? WHERE id = ?",
                (existing[1] + 1,
                 existing[2] + (1 if success else 0),
                 now, existing[0]),
            )
            self._conn.commit()
            return False
        else:
            self._conn.execute(
                "INSERT INTO patterns (user_id, context_tags, behavior, action, "
                "occurrence_count, success_count, last_triggered) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (user_id, tags, behavior, action, 1 if success else 0, now),
            )
            self._conn.commit()
            return True

    def query_active(self, user_id: str, min_occurrence: int = 3,
                     min_confidence: float = 0.8) -> list[dict]:
        """Get patterns ready for proactive anticipation.

        Returns patterns where:
          - Occurred >= min_occurrence times
          - Success rate >= min_confidence
          - Matches current time context
        """
        tags = _context_tags()
        tag_list = tags.split(",")
        now = time.time()
        decay_cutoff = now - (28 * 86400)  # 28 days

        results = []
        rows = self._conn.execute(
            "SELECT context_tags, behavior, action, occurrence_count, "
            "success_count, last_triggered FROM patterns "
            "WHERE user_id = ? AND occurrence_count >= ? "
            "AND CAST(success_count AS REAL) / occurrence_count >= ?",
            (user_id, min_occurrence, min_confidence),
        ).fetchall()

        for row in rows:
            ctx, behavior, action, count, success, last = row
            # Check context overlap: at least one tag matches
            ctx_tags = set(ctx.split(","))
            current_tags = set(tag_list)
            if not ctx_tags & current_tags:
                continue
            # Decay check: if not triggered in 28 days, reduce confidence
            adjusted_confidence = success / count
            if last < decay_cutoff:
                adjusted_confidence *= 0.5  # Decayed
                if adjusted_confidence < min_confidence:
                    continue

            results.append({
                "context": ctx,
                "behavior": behavior,
                "action": action,
                "occurrence": count,
                "confidence": round(adjusted_confidence, 3),
                "last_triggered_days_ago": round((now - last) / 86400, 1),
            })

        return sorted(results, key=lambda r: r["confidence"], reverse=True)

    def generate_hint(self, user_id: str) -> str | None:
        """Generate a proactive hint if a high-confidence pattern exists.

        Returns a natural-language string to inject into the system prompt,
        or None if no high-confidence pattern is active.
        """
        patterns = self.query_active(user_id)
        if not patterns:
            return None

        best = patterns[0]
        hint_map = {
            "fatigue_brevity": "用户在当前时段通常很疲惫，偏好简短回复。可以在不询问的情况下直接采用简洁模式。",
            "fatigue_explicit": "用户在当前时段经常主动要求缩短回复。",
            "verbose_upgrade": "用户在当前时段通常精力充沛，可以适当展开讨论。",
        }
        hint = hint_map.get(best["behavior"], "")
        if not hint:
            return None
        return (
            f"[关系预判] (置信度: {best['confidence']:.0%}, "
            f"已发生 {best['occurrence']} 次) {hint}"
        )

    def decay_all(self, user_id: str, days: int = 28) -> int:
        """Apply decay to old patterns. Returns count of decayed rows."""
        cutoff = time.time() - (days * 86400)
        cursor = self._conn.execute(
            "UPDATE patterns SET success_count = MAX(0, success_count - 1) "
            "WHERE user_id = ? AND last_triggered < ? "
            "AND success_count > 0",
            (user_id, cutoff),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
