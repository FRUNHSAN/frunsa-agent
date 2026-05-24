"""SQLiteTraceSink: at-rest trace archival with schema-first design.

Phase 12: Pure B-tree indexes, no FTS5. Implements both TraceWriter
(summary records) and StreamingTraceWriter (per-item records with
cost boundary enforcement).

Schema is validated against sink_schema.py declarations by the
sink_schema_consistency guardrail (Phase 12 Step 6).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from core.contracts.trace_keys import COMPONENT_TRACE_KEYS
from core.observability.sink_schema import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_COLUMNS,
    SCHEMA_VERSION_TABLE_NAME,
    TRACE_KEYS_COLUMNS,
    TRACE_KEYS_INDEXES,
    TRACE_KEYS_TABLE_NAME,
    TRACE_RECORDS_COLUMNS,
    TRACE_RECORDS_INDEXES,
    TRACE_RECORDS_TABLE_NAME,
    ColumnDef,
    IndexDef,
    SQLiteAffinity,
)
from core.pipeline.tracing import (
    StreamingTraceRecord,
    StreamingTraceWriter,
    StreamingWriteResult,
    TraceLog,
    TraceWriter,
)

# Map declarative affinity names to SQLite type keywords
_AFFINITY_TO_SQL: Dict[SQLiteAffinity, str] = {
    "INTEGER": "INTEGER",
    "REAL": "REAL",
    "TEXT": "TEXT",
    "BLOB": "BLOB",
    "NULLABLE_TEXT": "TEXT",
    "NULLABLE_REAL": "REAL",
    "NULLABLE_INTEGER": "INTEGER",
}

_TRACE_RECORDS_COLUMN_NAMES = [c["name"] for c in TRACE_RECORDS_COLUMNS]
_NON_PK_COLUMN_NAMES = [c["name"] for c in TRACE_RECORDS_COLUMNS if not c["primary_key"]]


def _build_create_table_sql(table_name: str, columns: List[ColumnDef]) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL from declarative ColumnDef list."""
    col_specs: List[str] = []
    for col in columns:
        sql_type = _AFFINITY_TO_SQL[col["affinity"]]
        parts = [col["name"], sql_type]
        if not col["nullable"]:
            parts.append("NOT NULL")
        if col["primary_key"]:
            if col["affinity"] == "INTEGER" and col["name"] == "id":
                parts.append("PRIMARY KEY AUTOINCREMENT")
            else:
                parts.append("PRIMARY KEY")
        col_specs.append(" ".join(parts))
    return (
        f"CREATE TABLE IF NOT EXISTS {table_name} (\n    "
        + ",\n    ".join(col_specs)
        + "\n)"
    )


def _build_create_index_sql(index: IndexDef) -> str:
    """Generate CREATE INDEX IF NOT EXISTS SQL from declarative IndexDef."""
    unique = "UNIQUE " if index["unique"] else ""
    col_list = ", ".join(index["columns"])
    return (
        f"CREATE {unique}INDEX IF NOT EXISTS {index['name']} "
        f"ON {index['table']} ({col_list})"
    )


class SQLiteTraceSink:
    """At-rest trace sink backed by SQLite (pure B-tree, no FTS5).

    Implements both TraceWriter (summary records, item_index=NULL) and
    StreamingTraceWriter (per-item records with cost boundary enforcement).

    Cost boundary enforcement lives HERE (the sink), not in adapters.
    Adapters blindly collect ALL StreamingTraceRecords and pass them to
    write_streaming(). The sink truncates to max_items_per_call, appends
    overflow sentinel, and returns StreamingWriteResult.
    """

    def __init__(
        self,
        path: str,
        max_items_per_call: int = 100,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_items_per_call = max_items_per_call
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._create_tables()
        self._migrate_v1_to_v2()
        self._create_indexes()
        self._seed_trace_keys()
        self._record_schema_version()

    # ── Protocol properties ──────────────────────────────────────────

    @property
    def max_items_per_call(self) -> int:
        return self._max_items_per_call

    # ── TraceWriter (summary records) ─────────────────────────────────

    def write(self, traces: List[TraceLog]) -> None:
        """Write summary trace records (item_index=NULL) from TraceLog list.

        Mirrors FileTraceExporter output shape: one row per DependencyCallTrace,
        with trace_context from the LAST StreamItem in the call.
        """
        rows: List[tuple] = []
        ts = datetime.now(timezone.utc).isoformat()

        for trace_log in traces:
            for step in trace_log.steps:
                for dep_call in step.dependency_calls:
                    ctx = dep_call.trace_context
                    ctx_json = (
                        json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))
                        if ctx is not None
                        else None
                    )
                    engine = self._infer_engine(ctx) if ctx else ""

                    rows.append((
                        ts,
                        trace_log.pipeline_run_id,
                        step.step_name,
                        dep_call.dependency_name,
                        dep_call.status,
                        dep_call.duration_ms,
                        engine,
                        ctx_json,
                        None,  # item_index=NULL for summary
                        None,  # item_delta_preview=NULL
                        None,  # is_terminal=NULL
                    ))

        if rows:
            self._insert_rows(rows)
            self._conn.commit()

    # ── StreamingTraceWriter (per-item records) ───────────────────────

    def write_streaming(
        self, records: List[StreamingTraceRecord]
    ) -> StreamingWriteResult:
        """Write per-item streaming trace records with cost boundary enforcement.

        Truncation logic (lives here, NOT in adapter):
        - max_items_per_call == -1: unlimited, all records stored
        - max_items_per_call == 0: count-only, sentinel with overflow_count
        - max_items_per_call > 0: store at most N, truncate + sentinel if overflow
        """
        total = len(records)
        cap = self._max_items_per_call

        if total == 0:
            return StreamingWriteResult(
                accepted_count=0, overflow_count=0, sentinel_written=False
            )

        if cap == -1:
            self._insert_per_item_records(records)
            return StreamingWriteResult(
                accepted_count=total, overflow_count=0, sentinel_written=False
            )

        if cap == 0:
            self._insert_overflow_sentinel(overflow_count=total, total=total)
            return StreamingWriteResult(
                accepted_count=0, overflow_count=total, sentinel_written=True
            )

        # cap > 0: store at most N, truncate + sentinel if overflow
        accepted = records[:cap]
        overflow = records[cap:]

        if accepted:
            self._insert_per_item_records(accepted)

        if overflow:
            self._insert_overflow_sentinel(overflow_count=len(overflow), total=total)
            return StreamingWriteResult(
                accepted_count=len(accepted),
                overflow_count=len(overflow),
                sentinel_written=True,
            )

        return StreamingWriteResult(
            accepted_count=len(accepted),
            overflow_count=0,
            sentinel_written=False,
        )

    def _insert_per_item_records(self, records: List[StreamingTraceRecord]) -> None:
        """Insert per-item trace records into trace_records table."""
        rows: List[tuple] = []
        for r in records:
            ctx_json = (
                json.dumps(r.trace_context, ensure_ascii=False, separators=(",", ":"))
                if r.trace_context is not None
                else None
            )
            engine = r.engine or (
                self._infer_engine(r.trace_context) if r.trace_context else ""
            )

            rows.append((
                r.ts_iso,
                r.pipeline_run_id,
                r.step_name,
                r.dependency_name,
                "success",
                None,  # duration_ms is on summary, not per-item
                engine,
                ctx_json,
                r.item_index,
                r.item_delta_preview,
                1 if r.is_terminal else 0,
            ))

        if rows:
            self._insert_rows(rows)
            self._conn.commit()

    def _insert_overflow_sentinel(self, overflow_count: int, total: int) -> None:
        """Insert sentinel row indicating truncation occurred."""
        ts = datetime.now(timezone.utc).isoformat()
        ctx_json = json.dumps(
            {"overflow_count": overflow_count, "total": total},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cols = ", ".join(_NON_PK_COLUMN_NAMES)
        placeholders = ", ".join("?" * len(_NON_PK_COLUMN_NAMES))
        self._conn.execute(
            f"INSERT INTO {TRACE_RECORDS_TABLE_NAME} ({cols}) VALUES ({placeholders})",
            (ts, "", "", "", "overflow", None, "", ctx_json, -1, None, None),
        )
        self._conn.commit()

    # ── Query interface ───────────────────────────────────────────────

    def query_by_engine(self, engine: str) -> List[Dict[str, Any]]:
        """Return all trace records for a given engine."""
        rows = self._conn.execute(
            f"SELECT * FROM {TRACE_RECORDS_TABLE_NAME} WHERE engine = ? ORDER BY ts",
            (engine,),
        ).fetchall()
        return [dict(zip(_TRACE_RECORDS_COLUMN_NAMES, row)) for row in rows]

    def query_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Return all trace records for a given pipeline run."""
        rows = self._conn.execute(
            f"SELECT * FROM {TRACE_RECORDS_TABLE_NAME} WHERE run_id = ? ORDER BY ts",
            (run_id,),
        ).fetchall()
        return [dict(zip(_TRACE_RECORDS_COLUMN_NAMES, row)) for row in rows]

    def query_keys(
        self,
        component_candidate_only: bool = False,
        component_type: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Return trace key definitions.

        Args:
            component_candidate_only: If True, filter to component_candidate=1.
            component_type: If set, filter to matching component_type
                (e.g. "retrieval"). Overrides component_candidate_only.
        """
        key_columns = [c["name"] for c in TRACE_KEYS_COLUMNS]

        if component_type is not None:
            rows = self._conn.execute(
                f"SELECT * FROM {TRACE_KEYS_TABLE_NAME} WHERE component_type = ?",
                (component_type,),
            ).fetchall()
        elif component_candidate_only:
            rows = self._conn.execute(
                f"SELECT * FROM {TRACE_KEYS_TABLE_NAME} WHERE component_candidate = 1"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {TRACE_KEYS_TABLE_NAME}"
            ).fetchall()

        return [dict(zip(key_columns, row)) for row in rows]

    def query_component_keys(
        self, component_type: str | None = None
    ) -> List[Dict[str, Any]]:
        """Return component trace key definitions, optionally filtered by type.

        This is distinct from query_keys() which returns all keys (engine +
        component). query_component_keys() returns only keys where
        component_type IS NOT NULL.
        """
        key_columns = [c["name"] for c in TRACE_KEYS_COLUMNS]

        if component_type is not None:
            rows = self._conn.execute(
                f"SELECT * FROM {TRACE_KEYS_TABLE_NAME} WHERE component_type = ?",
                (component_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {TRACE_KEYS_TABLE_NAME} WHERE component_type IS NOT NULL"
            ).fetchall()

        return [dict(zip(key_columns, row)) for row in rows]

    def query_item_counts_by_dependency(self, run_id: str) -> List[Dict[str, Any]]:
        """Return per-dependency item counts for a given run."""
        rows = self._conn.execute(
            f"""SELECT dependency, COUNT(*) as item_count
               FROM {TRACE_RECORDS_TABLE_NAME}
               WHERE run_id = ? AND item_index IS NOT NULL AND item_index >= 0
               GROUP BY dependency""",
            (run_id,),
        ).fetchall()
        return [{"dependency": row[0], "item_count": row[1]} for row in rows]

    # ── Engine inference (same pattern as FileTraceExporter) ──────────

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_engine_prefix_map() -> Dict[str, str]:
        """Build reverse lookup: key_prefix -> engine name from registry."""
        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        return {
            key.split(".")[0]: defn.engine
            for key, defn in TRACE_KEY_REGISTRY.items()
        }

    @staticmethod
    def _infer_engine(ctx: Dict[str, Any]) -> str:
        prefix_map = SQLiteTraceSink._get_engine_prefix_map()
        for key in ctx:
            prefix = key.split(".", 1)[0]
            if prefix in prefix_map:
                return prefix_map[prefix]
        return next((k.split(".", 1)[0] for k in ctx if "." in k), "unknown")

    # ── Schema management ─────────────────────────────────────────────

    def _insert_rows(self, rows: List[tuple]) -> None:
        """Insert pre-built row tuples into trace_records table.

        Does NOT call commit() — callers control transaction boundaries.
        Uses _NON_PK_COLUMN_NAMES for column list; rows must be tuples
        with values in the same order.
        """
        if not rows:
            return
        cols = ", ".join(_NON_PK_COLUMN_NAMES)
        placeholders = ", ".join("?" * len(_NON_PK_COLUMN_NAMES))
        self._conn.executemany(
            f"INSERT INTO {TRACE_RECORDS_TABLE_NAME} ({cols}) VALUES ({placeholders})",
            rows,
        )

    def _create_tables(self) -> None:
        """Create all tables from declarative schema definitions."""
        for table_name, columns in [
            (TRACE_RECORDS_TABLE_NAME, TRACE_RECORDS_COLUMNS),
            (TRACE_KEYS_TABLE_NAME, TRACE_KEYS_COLUMNS),
            (SCHEMA_VERSION_TABLE_NAME, SCHEMA_VERSION_COLUMNS),
        ]:
            self._conn.execute(_build_create_table_sql(table_name, columns))
        self._conn.commit()

    def _create_indexes(self) -> None:
        """Create all indexes from declarative schema definitions.

        Called after _create_tables() and _migrate_v1_to_v2() to ensure
        all columns (including component_type from migration) exist.
        """
        for index_def in TRACE_RECORDS_INDEXES + TRACE_KEYS_INDEXES:
            self._conn.execute(_build_create_index_sql(index_def))
        self._conn.commit()

    def _migrate_v1_to_v2(self) -> None:
        """Add component_type column if missing (Phase 13 v1→v2 migration).

        Checks PRAGMA table_info for the trace_keys table. If the
        component_type column is absent (v1 database), adds it via
        ALTER TABLE.

        Called after _create_tables() (which ensures trace_keys exists)
        and before _create_indexes() (which creates the index on the
        new column). Fresh databases created by _create_tables() already
        have the column — this is a no-op for new databases.
        """
        pragma_rows = self._conn.execute(
            f"PRAGMA table_info('{TRACE_KEYS_TABLE_NAME}')"
        ).fetchall()
        existing_cols = {row[1] for row in pragma_rows}

        if "component_type" not in existing_cols:
            self._conn.execute(
                f"ALTER TABLE {TRACE_KEYS_TABLE_NAME} "
                "ADD COLUMN component_type TEXT"
            )
            self._conn.commit()

    def _seed_trace_keys(self) -> None:
        """Populate trace_keys table from TRACE_KEY_REGISTRY if empty."""
        count = self._conn.execute(
            f"SELECT COUNT(*) FROM {TRACE_KEYS_TABLE_NAME}"
        ).fetchone()[0]

        if count > 0:
            return

        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        rows = [
            (
                key_name,
                defn.engine,
                defn.type.__name__,
                defn.semantics,
                defn.unit or None,
                1 if defn.component_candidate else 0,
            )
            for key_name, defn in TRACE_KEY_REGISTRY.items()
        ]

        self._conn.executemany(
            f"""INSERT INTO {TRACE_KEYS_TABLE_NAME}
               (key_name, engine, value_type, semantics, unit, component_candidate)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

        # Seed component trace keys (Phase 13)
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP

        component_key_names = set(ENGINE_TO_COMPONENT_MAP.values())
        existing_component = self._conn.execute(
            f"SELECT key_name FROM {TRACE_KEYS_TABLE_NAME} "
            "WHERE component_type IS NOT NULL"
        ).fetchall()
        existing_component_names = {row[0] for row in existing_component}

        component_rows = []
        for defn in COMPONENT_TRACE_KEYS.values():
            if defn.full_key not in existing_component_names:
                component_rows.append((
                    defn.full_key,
                    "",  # engine: empty for component keys (engine-agnostic)
                    defn.type.__name__,
                    defn.semantics,
                    defn.unit or None,
                    1,  # component_candidate=True for backward compatibility
                    defn.component_type,
                ))

        if component_rows:
            self._conn.executemany(
                f"""INSERT INTO {TRACE_KEYS_TABLE_NAME}
                   (key_name, engine, value_type, semantics, unit,
                    component_candidate, component_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                component_rows,
            )
            self._conn.commit()

        # Seed orchestration engine keys (Phase 14)
        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        orchestration_key_names = {
            k for k, v in TRACE_KEY_REGISTRY.items() if v.engine == "orchestration"
        }
        existing_orch = self._conn.execute(
            f"SELECT key_name FROM {TRACE_KEYS_TABLE_NAME} WHERE engine = ?",
            ("orchestration",),
        ).fetchall()
        existing_orch_names = {row[0] for row in existing_orch}

        orchestration_rows = []
        for key_name in sorted(orchestration_key_names):
            if key_name not in existing_orch_names:
                defn = TRACE_KEY_REGISTRY[key_name]
                orchestration_rows.append((
                    key_name,
                    defn.engine,
                    defn.type.__name__,
                    defn.semantics,
                    defn.unit or None,
                    0,  # component_candidate=False
                ))

        if orchestration_rows:
            self._conn.executemany(
                f"""INSERT INTO {TRACE_KEYS_TABLE_NAME}
                   (key_name, engine, value_type, semantics, unit, component_candidate)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                orchestration_rows,
            )
            self._conn.commit()

    def _record_schema_version(self) -> None:
        """Record current schema version if not already recorded."""
        existing = self._conn.execute(
            f"SELECT version FROM {SCHEMA_VERSION_TABLE_NAME} WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        ).fetchone()

        if existing is None:
            self._conn.execute(
                f"INSERT INTO {SCHEMA_VERSION_TABLE_NAME} (version, applied_at, description) VALUES (?, ?, ?)",
                (
                    CURRENT_SCHEMA_VERSION,
                    datetime.now(timezone.utc).isoformat(),
                    "Phase 14: seeded 6 orchestration engine trace keys",
                ),
            )
            self._conn.commit()

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "SQLiteTraceSink":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
