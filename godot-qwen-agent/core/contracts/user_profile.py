"""UserProfile — PLAN5 Loop 3: cross-session contract memory.

When the same temporary adaptation is triggered across multiple sessions,
it's not a "momentary response" — it's a personality trait. This module
tracks which fields are modified across sessions and proposes constitutional
amendments when a pattern crosses the repetition threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    amendment_threshold: int = 3  # sessions to trigger amendment
    _field_sessions: dict[str, set[int]] = field(default_factory=dict)
    _current_session: int = 0

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

    def sessions_modified(self, key: str) -> int:
        """How many distinct sessions has this field been modified in?"""
        return len(self._field_sessions.get(key, set()))

    def propose_amendment(self, key: str, value: str) -> dict | None:
        """If field modified >= threshold sessions, propose a constitutional upgrade.

        Returns a proposal dict, or None if threshold not met.
        """
        if key not in EVOLVABLE_FIELDS:
            return None
        count = self.sessions_modified(key)
        if count < self.amendment_threshold:
            return None

        return {
            "target_blueprint_key": key,
            "new_baseline": value,
            "trigger_condition": f"cross_session_pattern:{key}",
            "human_reason": (
                f"Permanent user trait detected: '{key}' was modified to "
                f"'{value}' in {count} different sessions. "
                f"This is no longer a temporary adaptation — it's who this user is."
            ),
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
