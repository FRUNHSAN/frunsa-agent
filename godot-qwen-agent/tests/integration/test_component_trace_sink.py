"""Integration tests for component trace key seeding + queries in SQLiteSink (Phase 13)."""

import os
import sqlite3
import tempfile

import pytest

from core.observability.sink_schema import CURRENT_SCHEMA_VERSION, TRACE_KEYS_TABLE_NAME
from core.observability.sqlite_sink import SQLiteTraceSink


@pytest.fixture
def sink_path():
    """Create a temporary SQLite database path."""
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test.db")


class TestSinkComponentKeySeeding:
    """Component key seeding in SQLiteTraceSink."""

    def test_component_keys_seeded(self, sink_path):
        """Opening a new sink seeds all 3 component trace keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            comp_keys = sink.query_component_keys()
            assert len(comp_keys) == 3
            comp_names = {r["key_name"] for r in comp_keys}
            assert "retrieval.chunk_id" in comp_names
            assert "retrieval.latency_ms" in comp_names
            assert "generation.cumulative_tokens" in comp_names
        finally:
            sink.close()

    def test_component_keys_have_component_type(self, sink_path):
        """Seeded component keys have component_type set, not NULL."""
        sink = SQLiteTraceSink(sink_path)
        try:
            comp_keys = sink.query_component_keys()
            for key in comp_keys:
                assert key["component_type"] is not None, (
                    f"Component key '{key['key_name']}' has NULL component_type"
                )
                assert key["component_type"] in ("retrieval", "generation", "scoring")
        finally:
            sink.close()

    def test_component_keys_have_empty_engine(self, sink_path):
        """Component keys have engine='' (engine-agnostic)."""
        sink = SQLiteTraceSink(sink_path)
        try:
            comp_keys = sink.query_component_keys()
            for key in comp_keys:
                assert key["engine"] == "", (
                    f"Component key '{key['key_name']}' has non-empty engine: {key['engine']}"
                )
        finally:
            sink.close()

    def test_engine_keys_still_present(self, sink_path):
        """Existing engine keys are still seeded alongside component keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            engine_keys = [k for k in all_keys if k["component_type"] is None]
            assert len(engine_keys) == 12  # 6 engine + 6 orchestration (all non-component keys)
        finally:
            sink.close()

    def test_no_duplicate_seeding(self, sink_path):
        """Re-opening the sink does not duplicate component keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            count_before = len(sink.query_component_keys())
        finally:
            sink.close()

        # Re-open — should be idempotent
        sink2 = SQLiteTraceSink(sink_path)
        try:
            count_after = len(sink2.query_component_keys())
            assert count_after == count_before
        finally:
            sink2.close()

    def test_total_keys_after_phase_13(self, sink_path):
        """After Phase 13 seeding: 6 engine + 3 component = 9 keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            assert len(all_keys) == 15  # Phase 14: 6 engine + 3 component + 6 orchestration
        finally:
            sink.close()


class TestSinkComponentKeyQueries:
    """Query interface for component keys."""

    def test_query_component_keys_all(self, sink_path):
        """query_component_keys() returns all 3 component keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            keys = sink.query_component_keys()
            assert len(keys) == 3
        finally:
            sink.close()

    def test_query_component_keys_by_type(self, sink_path):
        """query_component_keys('retrieval') returns 2 retrieval keys."""
        sink = SQLiteTraceSink(sink_path)
        try:
            retrieval = sink.query_component_keys("retrieval")
            assert len(retrieval) == 2
            assert all(r["component_type"] == "retrieval" for r in retrieval)
        finally:
            sink.close()

    def test_query_component_keys_generation(self, sink_path):
        """query_component_keys('generation') returns 1 generation key."""
        sink = SQLiteTraceSink(sink_path)
        try:
            gen = sink.query_component_keys("generation")
            assert len(gen) == 1
            assert gen[0]["key_name"] == "generation.cumulative_tokens"
        finally:
            sink.close()

    def test_query_keys_with_component_type_param(self, sink_path):
        """query_keys(component_type='retrieval') works as filter."""
        sink = SQLiteTraceSink(sink_path)
        try:
            retrieval = sink.query_keys(component_type="retrieval")
            assert len(retrieval) == 2
        finally:
            sink.close()

    def test_query_keys_component_candidate_still_works(self, sink_path):
        """query_keys(component_candidate_only=True) still works (backward compat)."""
        sink = SQLiteTraceSink(sink_path)
        try:
            candidates = sink.query_keys(component_candidate_only=True)
            # 3 engine component_candidate + 3 component keys (also component_candidate=1)
            assert len(candidates) == 6
        finally:
            sink.close()


class TestSinkV2Migration:
    """Schema v1 → v2 migration."""

    def test_v2_schema_version_recorded(self, sink_path):
        """New databases record CURRENT_SCHEMA_VERSION=2."""
        sink = SQLiteTraceSink(sink_path)
        try:
            conn = sink._conn
            rows = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            ).fetchall()
            assert len(rows) >= 1
            assert rows[0][0] == 2
            assert CURRENT_SCHEMA_VERSION == 2
        finally:
            sink.close()

    def test_v1_to_v2_column_addition(self, sink_path):
        """Creating a v1 database manually, then opening with v2 adds the column."""
        # Create a v1 database manually (simulate pre-Phase 13 state)
        conn = sqlite3.connect(sink_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trace_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                run_id TEXT NOT NULL,
                step TEXT NOT NULL,
                dependency TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_ms REAL,
                engine TEXT NOT NULL,
                trace_context_json TEXT,
                item_index INTEGER,
                item_delta_preview TEXT,
                is_terminal INTEGER
            );
            CREATE TABLE IF NOT EXISTS trace_keys (
                key_name TEXT PRIMARY KEY,
                engine TEXT NOT NULL,
                value_type TEXT NOT NULL,
                semantics TEXT NOT NULL,
                unit TEXT,
                component_candidate INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at, description)
            VALUES (1, '2026-01-01T00:00:00Z', 'Initial Phase 12 schema');
        """)
        conn.commit()
        conn.close()

        # Open with v2 sink — migration should run
        sink = SQLiteTraceSink(sink_path)
        try:
            # Verify component_type column now exists
            pragma = sink._conn.execute(
                f"PRAGMA table_info('{TRACE_KEYS_TABLE_NAME}')"
            ).fetchall()
            col_names = {row[1] for row in pragma}
            assert "component_type" in col_names, (
                "component_type column was not added by migration"
            )

            # Verify component keys were seeded
            comp_keys = sink.query_component_keys()
            assert len(comp_keys) == 3
        finally:
            sink.close()

    def test_migration_idempotent(self, sink_path):
        """Opening a v2 database twice does not fail."""
        sink = SQLiteTraceSink(sink_path)
        sink.close()
        # Re-open — should be fine
        sink2 = SQLiteTraceSink(sink_path)
        try:
            assert len(sink2.query_component_keys()) == 3
        finally:
            sink2.close()
