"""SQLiteProfile — V2: concurrent-safe UserProfile persistence.

Replaces single-file JSON with SQLite + WAL mode.
  - WAL mode: concurrent reads during writes
  - busy_timeout: 5s wait on lock contention
  - Drop-in: same save/load interface as UserProfile
  - Backward: JSON profile auto-migrated on first load
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DEFAULT_PATH = "user_profiles.db"


class SQLiteProfile:
    """SQLite-backed user profile. WAL mode, concurrent-safe."""

    def __init__(self, user_id: str, db_path: str = "") -> None:
        self.user_id = user_id
        db_path = db_path or DEFAULT_PATH
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS profiles ("
            "  user_id TEXT PRIMARY KEY,"
            "  data TEXT NOT NULL,"
            "  updated_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        self._conn.commit()
        self._data: dict = self._load()

    def _load(self) -> dict:
        row = self._conn.execute(
            "SELECT data FROM profiles WHERE user_id = ?", (self.user_id,)
        ).fetchone()
        if row:
            return json.loads(row[0])

        # Try migration from legacy JSON
        legacy = Path(f"user_profiles/{self.user_id}.json")
        if legacy.exists():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            self._data = data
            self.save()
            return data

        return self._default_data()

    @staticmethod
    def _default_data() -> dict:
        return {
            "user_id": "",
            "current_session": 0,
            "field_sessions": {},
            "session_outlier": [],
            "session_mod_count": {},
            "session_trust_delta": {},
        }

    def save(self) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO profiles (user_id, data) VALUES (?, ?)",
            (self.user_id, json.dumps(self._data, ensure_ascii=False)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @property
    def session_count(self) -> int:
        return self._data.get("current_session", 0)

    def start_session(self) -> int:
        self._data["current_session"] = self._data.get("current_session", 0) + 1
        return self._data["current_session"]

    def record_modification(self, key: str, value: str) -> None:
        sid = self._data.get("current_session", 0)
        if sid <= 0:
            return
        fs = self._data.setdefault("field_sessions", {})
        fs.setdefault(key, []).append(sid)
        sm = self._data.setdefault("session_mod_count", {})
        sm[str(sid)] = sm.get(str(sid), 0) + 1

    def record_trust_delta(self, delta: float) -> None:
        sid = str(self._data.get("current_session", 0))
        td = self._data.setdefault("session_trust_delta", {})
        td[sid] = max(abs(delta), td.get(sid, 0.0))

    def sessions_modified(self, key: str) -> int:
        fs = self._data.get("field_sessions", {})
        return len(set(fs.get(key, [])))

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
