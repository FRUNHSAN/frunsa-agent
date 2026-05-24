"""Rule: runtime SQLite schema must match declarative sink_schema.py definitions.

Phase 12: WARNING level. Schema drift doesn't break correctness but should
be visible. Missing indexes cause silent query performance degradation —
this is the primary value of the check.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation

from core.observability.sink_schema import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_TABLE_NAME,
    TRACE_KEYS_COLUMNS,
    TRACE_KEYS_INDEXES,
    TRACE_KEYS_TABLE_NAME,
    TRACE_RECORDS_COLUMNS,
    TRACE_RECORDS_INDEXES,
    TRACE_RECORDS_TABLE_NAME,
    ColumnDef,
    IndexDef,
)


def sink_schema_consistency(root: Path) -> List[Violation]:
    """Validate that runtime SQLite schema matches declarative definitions.

    Creates a temporary in-memory SQLite database, instantiates
    SQLiteTraceSink (which executes all CREATE TABLE/INDEX statements),
    then compares the resulting schema against the declarations in
    sink_schema.py.

    Checks:
      1. Every declared table has all expected columns
      2. Every declared index exists at runtime
      3. Schema version matches CURRENT_SCHEMA_VERSION
    """
    violations: List[Violation] = []

    try:
        from core.observability.sqlite_sink import SQLiteTraceSink
    except ImportError as exc:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.ERROR,
            message=f"Cannot import SQLiteTraceSink: {exc}",
            file="core/observability/sqlite_sink.py",
        ))
        return violations

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "_guardrail_check.db")
        try:
            sink = SQLiteTraceSink(db_path)
        except Exception as exc:
            violations.append(Violation(
                rule_id="sink-schema-consistency-001",
                severity=Severity.ERROR,
                message=f"SQLiteTraceSink construction failed: {exc}",
                file="core/observability/sqlite_sink.py",
            ))
            return violations

        try:
            conn = sink._conn

            # 1. Column validation per declared table
            for table_name, declared_cols in [
                (TRACE_RECORDS_TABLE_NAME, TRACE_RECORDS_COLUMNS),
                (TRACE_KEYS_TABLE_NAME, TRACE_KEYS_COLUMNS),
                (SCHEMA_VERSION_TABLE_NAME, []),  # version table checked via version query
            ]:
                if declared_cols:
                    violations.extend(
                        _check_table_columns(conn, table_name, declared_cols)
                    )

            # 2. Index validation
            for index_def in TRACE_RECORDS_INDEXES + TRACE_KEYS_INDEXES:
                violations.extend(_check_index_exists(conn, index_def))

            # 3. Schema version check
            violations.extend(_check_schema_version(conn))

        finally:
            sink.close()

    return violations


def _check_table_columns(
    conn: sqlite3.Connection,
    table_name: str,
    declared_cols: List[ColumnDef],
) -> List[Violation]:
    """Validate that all declared columns exist in the runtime table."""
    violations: List[Violation] = []

    try:
        pragma_rows = conn.execute(
            f"PRAGMA table_info('{table_name}')"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.ERROR,
            message=f"Table '{table_name}' declared in sink_schema.py but not found at runtime: {exc}",
            file="core/observability/sink_schema.py",
        ))
        return violations

    runtime_cols = {row[1] for row in pragma_rows}  # PRAGMA table_info: col 1 = name

    for col in declared_cols:
        if col["name"] not in runtime_cols:
            violations.append(Violation(
                rule_id="sink-schema-consistency-001",
                severity=Severity.WARNING,
                message=(
                    f"Column '{table_name}.{col['name']}' declared in sink_schema.py "
                    f"but missing at runtime. Run CREATE TABLE migration."
                ),
                file="core/observability/sink_schema.py",
            ))

    return violations


def _check_index_exists(
    conn: sqlite3.Connection,
    index_def: IndexDef,
) -> List[Violation]:
    """Validate that a declared index exists in sqlite_master."""
    violations: List[Violation] = []

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name = ?",
        (index_def["name"],),
    ).fetchone()

    if row is None:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.WARNING,
            message=(
                f"Index '{index_def['name']}' on '{index_def['table']}' "
                f"declared in sink_schema.py but missing at runtime. "
                f"Query performance may be degraded. Run CREATE INDEX migration."
            ),
            file="core/observability/sink_schema.py",
        ))

    return violations


def _check_schema_version(conn: sqlite3.Connection) -> List[Violation]:
    """Validate that the runtime schema_version matches CURRENT_SCHEMA_VERSION."""
    violations: List[Violation] = []

    try:
        row = conn.execute(
            f"SELECT MAX(version) FROM {SCHEMA_VERSION_TABLE_NAME}"
        ).fetchone()
        runtime_version = row[0] if row else None
    except sqlite3.OperationalError:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.WARNING,
            message=(
                f"Schema version table '{SCHEMA_VERSION_TABLE_NAME}' not found. "
                f"Run schema migration."
            ),
            file="core/observability/sink_schema.py",
        ))
        return violations

    if runtime_version is None:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.WARNING,
            message="No schema version recorded. Run schema migration.",
            file="core/observability/sink_schema.py",
        ))
    elif runtime_version != CURRENT_SCHEMA_VERSION:
        violations.append(Violation(
            rule_id="sink-schema-consistency-001",
            severity=Severity.WARNING,
            message=(
                f"Schema version mismatch: runtime={runtime_version}, "
                f"declared={CURRENT_SCHEMA_VERSION}. Run schema migration."
            ),
            file="core/observability/sink_schema.py",
        ))

    return violations
