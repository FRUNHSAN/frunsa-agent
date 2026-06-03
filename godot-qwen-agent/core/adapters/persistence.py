"""Relationship Memory Store — Phase 22c.

Persistent storage for contract health history. Stores transitions (diffs
between successive ContractHealthReports) rather than full snapshots — this
captures the "evolution trajectory" of a relationship, not just its state.

Think of it as the system's "long-term memory" for contracts. While
ContractAwareEventSink is working memory (current session events), this is
persistent memory (cross-session relationship history).

Design:
  - SQLite-backed (zero external dependencies beyond Python stdlib)
  - Thread-safe via threading.Lock (same pattern as ContractAwareEventSink)
  - Stores transitions: {baseline, delta, severity_change, timestamp}
  - Queryable by (blueprint_fingerprint, time_range)
  - Indexed for efficient trend queries

Future Phase 25+:
  - Cross-blueprint relationship queries ("show me all contracts with user X")
  - Time-series analysis of compliance trends
  - Trigger-based notifications (compliance drops below threshold)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from core.contracts.composition import ContractHealthReport


# ── Transition Record ─────────────────────────────────────────────────

class TransitionRecord:
    """A single transition between two health assessments.

    Captures the DELTA, not the full snapshot. Stored as a row in SQLite.

    Fields:
        blueprint_fingerprint: Which contract this transition belongs to
        timestamp:             epoch seconds when the transition was recorded
        compliance_delta:      Change in compliance_rate (+ = improving)
        severity_before:       Severity level before this transition
        severity_after:        Severity level after this transition
        dominant_violation:    Most frequent violation type at this point
        violation_snapshot:    JSON string of violation_counts dict
        lifecycle:             ContractLifecycle stage at transition time
    """

    def __init__(
        self,
        blueprint_fingerprint: str,
        timestamp: float,
        compliance_delta: float,
        severity_before: str,
        severity_after: str,
        dominant_violation: str | None,
        violation_snapshot: str,
        lifecycle: str = "active",
    ) -> None:
        self.blueprint_fingerprint = blueprint_fingerprint
        self.timestamp = timestamp
        self.compliance_delta = compliance_delta
        self.severity_before = severity_before
        self.severity_after = severity_after
        self.dominant_violation = dominant_violation
        self.violation_snapshot = violation_snapshot
        self.lifecycle = lifecycle

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blueprint_fingerprint": self.blueprint_fingerprint,
            "timestamp": self.timestamp,
            "compliance_delta": self.compliance_delta,
            "severity_before": self.severity_before,
            "severity_after": self.severity_after,
            "dominant_violation": self.dominant_violation,
            "violation_snapshot": self.violation_snapshot,
            "lifecycle": self.lifecycle,
        }


# ── Relationship Memory Store ─────────────────────────────────────────

class RelationshipMemoryStore:
    """Persistent store for contract health transitions.

    Usage:
        store = RelationshipMemoryStore(":memory:")  # or path for persistence
        store.record_transition(previous_report, current_report, fingerprint)
        history = store.get_history(fingerprint, days=7)
        latest = store.get_latest(fingerprint)
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS health_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blueprint_fingerprint TEXT NOT NULL,
            timestamp REAL NOT NULL,
            compliance_delta REAL NOT NULL,
            severity_before TEXT NOT NULL DEFAULT 'healthy',
            severity_after TEXT NOT NULL DEFAULT 'healthy',
            dominant_violation TEXT,
            violation_snapshot TEXT DEFAULT '{}',
            lifecycle TEXT NOT NULL DEFAULT 'active'
        );

        CREATE INDEX IF NOT EXISTS idx_fingerprint_time
            ON health_transitions(blueprint_fingerprint, timestamp);

        CREATE INDEX IF NOT EXISTS idx_lifecycle
            ON health_transitions(lifecycle);

        CREATE TABLE IF NOT EXISTS human_tickets (
            ticket_id TEXT PRIMARY KEY,
            blueprint_fingerprint TEXT NOT NULL,
            report_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY,
            blueprint_fingerprint TEXT NOT NULL,
            violation_type TEXT NOT NULL,
            deterioration_count INTEGER DEFAULT 0,
            suggested_action TEXT DEFAULT '',
            severity TEXT DEFAULT 'degraded',
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at REAL NOT NULL
        );
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Create schema and keep persistent connection.

        Uses a single persistent connection because :memory: databases
        are per-connection — a new connect() would see an empty database.
        For file-based databases this also avoids repeated open/close.
        """
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get the persistent connection (asserts it exists)."""
        if self._conn is None:
            raise RuntimeError("RelationshipMemoryStore not initialized")
        return self._conn

    # ── Write ──────────────────────────────────────────────────────

    def record_transition(
        self,
        previous: ContractHealthReport | None,
        current: ContractHealthReport,
        blueprint_fingerprint: str,
        lifecycle: str = "active",
    ) -> None:
        """Record a transition between two health assessments.

        If previous is None, this is the first assessment (baseline).
        The delta is computed as current - previous compliance_rate.
        """
        compliance_before = previous.compliance_rate if previous else 1.0
        compliance_delta = current.compliance_rate - compliance_before
        severity_before = previous.severity if previous else "healthy"

        record = TransitionRecord(
            blueprint_fingerprint=blueprint_fingerprint,
            timestamp=time.time(),
            compliance_delta=round(compliance_delta, 4),
            severity_before=severity_before,
            severity_after=current.severity,
            dominant_violation=current.dominant_violation_type,
            violation_snapshot=json.dumps(
                dict(current.violation_counts), sort_keys=True
            ),
            lifecycle=lifecycle,
        )

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO health_transitions
                   (blueprint_fingerprint, timestamp, compliance_delta,
                    severity_before, severity_after, dominant_violation,
                    violation_snapshot, lifecycle)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.blueprint_fingerprint,
                    record.timestamp,
                    record.compliance_delta,
                    record.severity_before,
                    record.severity_after,
                    record.dominant_violation,
                    record.violation_snapshot,
                    record.lifecycle,
                ),
            )
            conn.commit()

    # ── Read ───────────────────────────────────────────────────────

    def get_history(
        self,
        blueprint_fingerprint: str,
        days: int = 7,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get transition history for a blueprint, last N days."""
        cutoff = time.time() - (days * 86400)

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM health_transitions
                   WHERE blueprint_fingerprint = ?
                     AND timestamp >= ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (blueprint_fingerprint, cutoff, limit),
            ).fetchall()

        return [dict(r) for r in rows]

    def get_latest(
        self, blueprint_fingerprint: str
    ) -> Dict[str, Any] | None:
        """Get the most recent transition for a blueprint."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """SELECT * FROM health_transitions
                   WHERE blueprint_fingerprint = ?
                   ORDER BY timestamp DESC
                   LIMIT 1""",
                (blueprint_fingerprint,),
            ).fetchone()

        return dict(row) if row else None

    def count_transitions(
        self, blueprint_fingerprint: str, days: int = 7
    ) -> int:
        """Count transitions for a blueprint in the last N days."""
        cutoff = time.time() - (days * 86400)

        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """SELECT COUNT(*) FROM health_transitions
                   WHERE blueprint_fingerprint = ?
                     AND timestamp >= ?""",
                (blueprint_fingerprint, cutoff),
            ).fetchone()

        return row[0] if row else 0

    def get_chronic_violators(
        self, threshold: int = 3, days: int = 7
    ) -> list[dict]:
        """Find blueprints with sustained deterioration.

        Returns blueprints where deterioration_count >= threshold
        in the last N days. These are candidates for renegotiation.
        """
        cutoff = time.time() - (days * 86400)

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT blueprint_fingerprint,
                          COUNT(*) as deterioration_count,
                          MAX(dominant_violation) as top_violation,
                          MAX(severity_after) as current_severity
                   FROM health_transitions
                   WHERE timestamp >= ?
                     AND compliance_delta < 0
                   GROUP BY blueprint_fingerprint
                   HAVING COUNT(*) >= ?""",
                (cutoff, threshold),
            ).fetchall()

        return [dict(r) for r in rows]

    def get_deterioration_count(
        self, blueprint_fingerprint: str, days: int = 7
    ) -> int:
        """Count how many transitions showed deterioration (negative delta)."""
        cutoff = time.time() - (days * 86400)

        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """SELECT COUNT(*) FROM health_transitions
                   WHERE blueprint_fingerprint = ?
                     AND timestamp >= ?
                     AND compliance_delta < 0""",
                (blueprint_fingerprint, cutoff),
            ).fetchone()

        return row[0] if row else 0

    # ── Human Tickets (Phase 24) ──────────────────────────────────

    def create_ticket(
        self,
        ticket_id: str,
        blueprint_fingerprint: str,
        report_json: str,
        created_at: float,
    ) -> None:
        """Create a human intervention ticket."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO human_tickets
                   (ticket_id, blueprint_fingerprint, report_json, status, created_at)
                   VALUES (?, ?, ?, 'PENDING', ?)""",
                (ticket_id, blueprint_fingerprint, report_json, created_at),
            )
            conn.commit()

    def resolve_ticket(self, ticket_id: str, decision: str) -> None:
        """Resolve a ticket with a human decision (APPROVED/REJECTED)."""
        status = "RESOLVED" if decision.upper() in ("APPROVE", "APPROVED") else "IGNORED"
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE human_tickets SET status = ? WHERE ticket_id = ?",
                (status, ticket_id),
            )
            conn.commit()

    def get_pending_tickets(self) -> list[dict]:
        """Return all unresolved intervention tickets."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM human_tickets WHERE status = 'PENDING'"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Proposals (Phase 25) — separate from human_tickets ────────

    def create_proposal(
        self,
        proposal_id: str,
        blueprint_fingerprint: str,
        violation_type: str,
        deterioration_count: int,
        suggested_action: str,
        severity: str,
        created_at: float,
    ) -> None:
        """Create a non-blocking renegotiation proposal."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO proposals
                   (proposal_id, blueprint_fingerprint, violation_type,
                    deterioration_count, suggested_action, severity,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                (proposal_id, blueprint_fingerprint, violation_type,
                 deterioration_count, suggested_action, severity, created_at),
            )
            conn.commit()

    def resolve_proposal(self, proposal_id: str, approved: bool) -> None:
        """Resolve a proposal (approved or rejected)."""
        status = "APPROVED" if approved else "REJECTED"
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                (status, proposal_id),
            )
            conn.commit()

    def get_pending_proposals(self) -> list[dict]:
        """Return all unresolved proposals."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM proposals WHERE status = 'PENDING'"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Lifecycle ─────────────────────────────────────────────────

    def clear(self) -> None:
        """Reset all data (test isolation)."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM health_transitions")
            conn.commit()

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def transition_count(self) -> int:
        """Total transitions across all blueprints."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT COUNT(*) FROM health_transitions"
            ).fetchone()
        return row[0] if row else 0
