"""UserProfile — PLAN5 Loop 3: cross-session contract memory.

When the same temporary adaptation is triggered across multiple sessions,
it's not a "momentary response" — it's a personality trait. This module
tracks which fields are modified across sessions and proposes constitutional
amendments when a pattern crosses the repetition threshold.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Same fields tracked for meta-evolution as for decay
EVOLVABLE_FIELDS = frozenset({
    "response_verbose_level",
    "execution_autonomy",
    "proactive_suggestions",
    "explanation_style",
})


@dataclass
class UserProfile:
    """Cross-session contract memory.

    Tracks which fields were modified in each session, detects
    repeated patterns, and proposes upgrading temporary adaptations
    into permanent user traits.

    Usage:
        profile = UserProfile("user_001")
        profile.record_modification("response_verbose_level", "LOW", session_id=1)
        profile.record_modification("response_verbose_level", "LOW", session_id=2)
        profile.record_modification("response_verbose_level", "LOW", session_id=3)
        amendment = profile.propose_amendment("response_verbose_level", "LOW")
        # amendment is not None -> upgrade to user trait!
    """

    user_id: str
    amendment_threshold: int = 3
    outlier_field_count: int = 3
    outlier_trust_delta: float = 0.25
    storage_path: str = "user_profiles/"
    _field_sessions: dict[str, set[int]] = field(default_factory=dict)
    _current_session: int = 0
    _session_outlier: set[int] = field(default_factory=set)
    _session_mod_count: dict[int, int] = field(default_factory=dict)
    _session_trust_delta: dict[int, float] = field(default_factory=dict)

    # ── Persistence ───────────────────────────────────────────

    def save(self) -> str:
        """Persist profile to JSON. Returns file path."""
        self.storage_path_obj.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "user_id": self.user_id,
            "amendment_threshold": self.amendment_threshold,
            "outlier_field_count": self.outlier_field_count,
            "outlier_trust_delta": self.outlier_trust_delta,
            "current_session": self._current_session,
            "field_sessions": {k: sorted(v) for k, v in self._field_sessions.items()},
            "session_outlier": sorted(self._session_outlier),
            "session_mod_count": self._session_mod_count,
            "session_trust_delta": self._session_trust_delta,
        }
        self.storage_path_obj.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(self.storage_path_obj)

    @classmethod
    def load(cls, user_id: str, storage_path: str = ".user_profiles/") -> "UserProfile":
        """Load profile from JSON, or return fresh one if not found."""
        profile = cls(user_id=user_id, storage_path=storage_path)
        if profile.storage_path_obj.exists():
            data = json.loads(profile.storage_path_obj.read_text(encoding="utf-8"))
            profile.amendment_threshold = data.get("amendment_threshold", 3)
            profile.outlier_field_count = data.get("outlier_field_count", 3)
            profile.outlier_trust_delta = data.get("outlier_trust_delta", 0.25)
            profile._current_session = data.get("current_session", 0)
            profile._field_sessions = {k: set(v) for k, v in data.get("field_sessions", {}).items()}
            profile._session_outlier = set(data.get("session_outlier", []))
            profile._session_mod_count = data.get("session_mod_count", {})
            profile._session_trust_delta = data.get("session_trust_delta", {})
        return profile

    @property
    def storage_path_obj(self) -> Path:
        return Path(self.storage_path) / f"{self.user_id}.json"

    def start_session(self) -> int:
        """Begin a new session. Returns session ID."""
        self._current_session += 1
        return self._current_session

    def record_modification(self, key: str, value: str, session_id: int | None = None) -> None:
        """Record that a field was modified in a session."""
        sid = session_id or self._current_session
        if sid <= 0:
            return
        if key not in self._field_sessions:
            self._field_sessions[key] = set()
        self._field_sessions[key].add(sid)
        self._session_mod_count[sid] = self._session_mod_count.get(sid, 0) + 1

    def record_trust_delta(self, delta: float, session_id: int | None = None) -> None:
        """Record trust change for a session. Used for outlier detection."""
        sid = session_id or self._current_session
        self._session_trust_delta[sid] = max(
            abs(delta), self._session_trust_delta.get(sid, 0.0)
        )

    def mark_outlier(self, session_id: int | None = None) -> None:
        """Manually mark a session as outlier. It won't count toward amendments."""
        sid = session_id or self._current_session
        self._session_outlier.add(sid)

    def auto_detect_outliers(self) -> list[int]:
        """Scan all sessions and mark outliers. Returns list of outlier session IDs."""
        new_outliers: list[int] = []
        for sid in range(1, self._current_session + 1):
            if sid in self._session_outlier:
                continue
            mods = self._session_mod_count.get(sid, 0)
            delta = self._session_trust_delta.get(sid, 0.0)
            if mods >= self.outlier_field_count:
                self._session_outlier.add(sid)
                new_outliers.append(sid)
            elif delta >= self.outlier_trust_delta:
                self._session_outlier.add(sid)
                new_outliers.append(sid)
        return new_outliers

    def sessions_modified(self, key: str) -> int:
        """How many distinct sessions has this field been modified in?"""
        return len(self._field_sessions.get(key, set()))

    def propose_amendment(self, key: str, value: str) -> dict | None:
        """If field modified >= threshold sessions, propose a constitutional upgrade.

        Excludes outlier sessions from the count. An amendment requires
        consistent behavior across normal sessions — not a single extreme event.

        Returns a proposal dict, or None if threshold not met.
        """
        if key not in EVOLVABLE_FIELDS:
            return None
        raw_sessions = self._field_sessions.get(key, set())
        clean_sessions = raw_sessions - self._session_outlier
        count = len(clean_sessions)
        if count < self.amendment_threshold:
            return None

        excluded = len(raw_sessions) - count
        reason = (
            f"Permanent user trait detected: '{key}' was modified to "
            f"'{value}' in {count}/{len(raw_sessions)} normal sessions"
        )
        if excluded:
            reason += f" ({excluded} outlier sessions excluded)."
        reason += " This is no longer a temporary adaptation — it's who this user is."

        return {
            "target_blueprint_key": key,
            "new_baseline": value,
            "trigger_condition": f"cross_session_pattern:{key}",
            "human_reason": reason,
        }

    @property
    def session_count(self) -> int:
        return self._current_session

    def snapshot(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_count": self._current_session,
            "field_sessions": {k: sorted(v) for k, v in self._field_sessions.items()},
        }
