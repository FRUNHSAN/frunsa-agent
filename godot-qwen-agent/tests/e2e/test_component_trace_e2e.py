"""E2E tests for component trace contracts end-to-end (Phase 13)."""

import os
import tempfile

import pytest

from core.contracts.trace_keys import (
    COMPONENT_TRACE_KEYS,
    validate_component_trace,
)
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP


class TestComponentTraceE2E:
    """End-to-end: sink seeds + queries component keys."""

    def test_sink_seeds_and_queries_component_keys(self):
        """Full chain: new sink → seeds 3 component keys → queries work."""
        with tempfile.TemporaryDirectory() as tmp:
            sink = SQLiteTraceSink(os.path.join(tmp, "test.db"))
            try:
                comp_keys = sink.query_component_keys()
                assert len(comp_keys) == 3

                # Each key matches its COMPONENT_TRACE_KEYS definition
                for row in comp_keys:
                    full_key = row["key_name"]
                    assert full_key in COMPONENT_TRACE_KEYS
                    defn = COMPONENT_TRACE_KEYS[full_key]
                    assert row["value_type"] == defn.type.__name__
                    assert row["component_type"] == defn.component_type
            finally:
                sink.close()

    def test_engine_keys_resolve_to_component_keys(self):
        """Engine keys resolve through ENGINE_TO_COMPONENT_MAP to component keys."""
        # Verify every mapping points to an existing component key
        for engine_key, component_key in ENGINE_TO_COMPONENT_MAP.items():
            assert component_key in COMPONENT_TRACE_KEYS, (
                f"'{engine_key}' maps to '{component_key}' "
                f"which is not in COMPONENT_TRACE_KEYS"
            )

    def test_validate_with_planning_engine_context(self):
        """Planning engine's component keys validate against generation contract.

        Note: validate_component_trace checks component key names
        (e.g. generation.cumulative_tokens), NOT engine key names.
        Engine→component resolution uses ENGINE_TO_COMPONENT_MAP separately.
        """
        ctx = {
            "generation.cumulative_tokens": 84,
        }
        result = validate_component_trace(ctx, "generation")
        assert result.passed
        assert len(result.errors) == 0

    def test_validate_with_rag_engine_context(self):
        """RAG engine's component keys validate against retrieval contract.

        Uses component key names (retrieval.chunk_id, retrieval.latency_ms),
        not engine key names (rag.chunk_id, rag.retrieval_latency_ms).
        """
        ctx = {
            "retrieval.chunk_id": "c001",
            "retrieval.latency_ms": 12.3,
        }
        result = validate_component_trace(ctx, "retrieval")
        assert result.passed
        assert len(result.errors) == 0

    def test_schema_version_is_v2(self):
        """New sink records schema version 2."""
        with tempfile.TemporaryDirectory() as tmp:
            sink = SQLiteTraceSink(os.path.join(tmp, "test.db"))
            try:
                from core.observability.sink_schema import CURRENT_SCHEMA_VERSION
                assert CURRENT_SCHEMA_VERSION == 2
                rows = sink._conn.execute(
                    "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                ).fetchall()
                assert rows[0][0] == 2
            finally:
                sink.close()
