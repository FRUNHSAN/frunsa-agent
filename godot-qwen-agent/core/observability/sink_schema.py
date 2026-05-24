"""Declarative schema for SQLite trace sink (Phase 12).

Schema-first design: every table column, index, and type constraint is
defined here before any SQL is written. The sink_schema_consistency
guardrail (Phase 12) validates that runtime CREATE TABLE statements
match these declarations.

Explicitly UNSUPPORTED:
  - No full-text search (FTS5 is compile-time optional, Phase 12 doesn't need it)
  - No streaming raw StreamItem payload storage (item_delta_preview only)
  - No real-time alerting or visualization (sink is at-rest archival)
  - No cross-run query optimization (single SQLite file, single run_id scope)
  - No WAL mode (default journal_mode is acceptable for Phase 12 append workload)
  - No concurrent write safety (single-writer assumption)
"""

from __future__ import annotations

from typing import List, Literal, TypedDict


# ── Column type alias ───────────────────────────────────────────────

SQLiteAffinity = Literal[
    "INTEGER", "REAL", "TEXT", "BLOB",
    "NULLABLE_TEXT", "NULLABLE_REAL", "NULLABLE_INTEGER",
]


# ── Column definition ───────────────────────────────────────────────

class ColumnDef(TypedDict):
    """Declarative column definition matching SQLite storage classes."""
    name: str
    affinity: SQLiteAffinity
    nullable: bool
    primary_key: bool
    description: str


# ── Index definition ────────────────────────────────────────────────

class IndexDef(TypedDict):
    """Declarative index definition."""
    name: str
    table: str
    columns: List[str]
    unique: bool
    description: str


# ── Trace Records table ─────────────────────────────────────────────

TRACE_RECORDS_TABLE_NAME = "trace_records"

TRACE_RECORDS_COLUMNS: List[ColumnDef] = [
    {"name": "id",              "affinity": "INTEGER",        "nullable": False, "primary_key": True,  "description": "Auto-increment row ID"},
    {"name": "ts",              "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "ISO 8601 timestamp of record creation"},
    {"name": "run_id",          "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "Pipeline run identifier"},
    {"name": "step",            "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "Pipeline step name"},
    {"name": "dependency",      "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "Dependency name within the step"},
    {"name": "status",          "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "Call status: success | timeout | error | overflow"},
    {"name": "duration_ms",     "affinity": "NULLABLE_REAL",  "nullable": True,  "primary_key": False, "description": "Dependency call duration in milliseconds"},
    {"name": "engine",          "affinity": "TEXT",           "nullable": False, "primary_key": False, "description": "Engine name inferred from trace_context keys"},
    {"name": "trace_context_json","affinity": "NULLABLE_TEXT","nullable": True,  "primary_key": False, "description": "Full trace_context dict serialized as JSON string"},
    {"name": "item_index",      "affinity": "NULLABLE_INTEGER","nullable": True,"primary_key": False, "description": "StreamItem index for per-item records; NULL for summary records"},
    {"name": "item_delta_preview","affinity": "NULLABLE_TEXT","nullable": True,  "primary_key": False, "description": "First 200 chars of StreamItem.delta; NULL for summary"},
    {"name": "is_terminal",     "affinity": "NULLABLE_INTEGER","nullable": True,"primary_key": False, "description": "1 if terminal StreamItem, 0 otherwise; NULL for summary"},
]

TRACE_RECORDS_INDEXES: List[IndexDef] = [
    {"name": "idx_run_id",      "table": TRACE_RECORDS_TABLE_NAME, "columns": ["run_id"],         "unique": False, "description": "Fast lookup by pipeline run"},
    {"name": "idx_engine",      "table": TRACE_RECORDS_TABLE_NAME, "columns": ["engine"],         "unique": False, "description": "Filter by engine type"},
    {"name": "idx_status",      "table": TRACE_RECORDS_TABLE_NAME, "columns": ["status"],         "unique": False, "description": "Filter by call status"},
    {"name": "idx_step",        "table": TRACE_RECORDS_TABLE_NAME, "columns": ["step"],           "unique": False, "description": "Filter by pipeline step"},
    {"name": "idx_run_step",    "table": TRACE_RECORDS_TABLE_NAME, "columns": ["run_id", "step"], "unique": False, "description": "Per-run per-step queries (common pattern)"},
    {"name": "idx_item_index",  "table": TRACE_RECORDS_TABLE_NAME, "columns": ["run_id", "dependency", "item_index"], "unique": False, "description": "Per-item ordering queries"},
]


# ── Trace Keys catalog table ────────────────────────────────────────

TRACE_KEYS_TABLE_NAME = "trace_keys"

TRACE_KEYS_COLUMNS: List[ColumnDef] = [
    {"name": "key_name",            "affinity": "TEXT",    "nullable": False, "primary_key": True,  "description": "Full dotted key name (e.g. 'planning.step_index')"},
    {"name": "engine",              "affinity": "TEXT",    "nullable": False, "primary_key": False, "description": "Owning engine name"},
    {"name": "value_type",          "affinity": "TEXT",    "nullable": False, "primary_key": False, "description": "Python type name (int, str, float)"},
    {"name": "semantics",           "affinity": "TEXT",    "nullable": False, "primary_key": False, "description": "Human-readable semantics"},
    {"name": "unit",                "affinity": "NULLABLE_TEXT", "nullable": True,  "primary_key": False, "description": "Unit of measurement (tokens, ms, empty string)"},
    {"name": "component_candidate", "affinity": "INTEGER", "nullable": False, "primary_key": False, "description": "1 if marked component_candidate=True"},
    {"name": "component_type",   "affinity": "NULLABLE_TEXT", "nullable": True,  "primary_key": False, "description": "Component type for component-level keys (retrieval/generation/scoring); NULL for engine keys"},
]

TRACE_KEYS_INDEXES: List[IndexDef] = [
    {"name": "idx_keys_engine", "table": TRACE_KEYS_TABLE_NAME, "columns": ["engine"], "unique": False, "description": "Keys grouped by engine"},
    {"name": "idx_keys_component_type", "table": TRACE_KEYS_TABLE_NAME, "columns": ["component_type"], "unique": False, "description": "Filter component keys by type"},
]


# ── Schema version tracking ─────────────────────────────────────────

SCHEMA_VERSION_TABLE_NAME = "schema_version"

SCHEMA_VERSION_COLUMNS: List[ColumnDef] = [
    {"name": "version",     "affinity": "INTEGER", "nullable": False, "primary_key": True,  "description": "Monotonic schema version number"},
    {"name": "applied_at",  "affinity": "TEXT",    "nullable": False, "primary_key": False, "description": "ISO 8601 timestamp of when this version was applied"},
    {"name": "description", "affinity": "TEXT",    "nullable": False, "primary_key": False, "description": "Human-readable description of schema change"},
]

CURRENT_SCHEMA_VERSION = 2


# ── Unsupported features (explicit) ─────────────────────────────────

SINK_UNSUPPORTED_FEATURES: List[str] = [
    "Full-text search (FTS5 is compile-time optional in SQLite)",
    "Streaming raw StreamItem payload storage (item_delta_preview is 200-char truncation)",
    "Real-time alerting or visualization (sink is at-rest archival, not live dashboard)",
    "Cross-run query optimization (single SQLite file, no sharding or partitioning)",
    "WAL mode (default journal_mode is acceptable for Phase 12 append-only workload)",
    "Concurrent write safety (single-writer assumption; multiple writers require application-level locking)",
]
