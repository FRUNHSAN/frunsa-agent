"""Integration tests for orchestration trace key seeding + queries in SQLiteSink (Phase 14)."""

import os
import tempfile

import pytest

from core.contracts.trace_keys import COMPONENT_TRACE_KEYS
from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY


@pytest.fixture
def sink_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test.db")


class TestSinkOrchestrationKeySeeding:
    """Orchestration key seeding in SQLiteTraceSink."""

    def test_orchestration_keys_seeded(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            orch_keys = sink.query_by_engine("orchestration")
            # query_by_engine returns trace_records, not trace_keys.
            # Use query_keys to verify seeding.
            all_keys = sink.query_keys()
            orch_key_rows = [k for k in all_keys if k["engine"] == "orchestration"]
            assert len(orch_key_rows) == 6
            orch_names = {r["key_name"] for r in orch_key_rows}
            assert orch_names == {
                "orchestration.dag_node_id",
                "orchestration.parallel_depth",
                "orchestration.merge_ordinal",
                "orchestration.branch_taken",
                "orchestration.retry_count",
                "orchestration.resource_pool_key",
            }
        finally:
            sink.close()

    def test_orchestration_keys_engine_field(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            orch_rows = [k for k in all_keys if k["key_name"].startswith("orchestration.")]
            assert len(orch_rows) == 6
            for row in orch_rows:
                assert row["engine"] == "orchestration", (
                    f"{row['key_name']}: engine={row['engine']}"
                )
        finally:
            sink.close()

    def test_orchestration_keys_not_component_candidate(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            orch_rows = [k for k in all_keys if k["key_name"].startswith("orchestration.")]
            for row in orch_rows:
                assert row["component_candidate"] == 0, (
                    f"{row['key_name']}: component_candidate={row['component_candidate']}"
                )
        finally:
            sink.close()

    def test_orchestration_keys_have_value_types(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            orch_rows = [k for k in all_keys if k["key_name"].startswith("orchestration.")]
            type_map = {r["key_name"]: r["value_type"] for r in orch_rows}
            assert type_map["orchestration.dag_node_id"] == "str"
            assert type_map["orchestration.parallel_depth"] == "int"
            assert type_map["orchestration.merge_ordinal"] == "int"
            assert type_map["orchestration.branch_taken"] == "str"
            assert type_map["orchestration.retry_count"] == "int"
            assert type_map["orchestration.resource_pool_key"] == "str"
        finally:
            sink.close()

    def test_no_duplicate_orchestration_seeding(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_before = sink.query_keys()
            orch_before = [k for k in all_before if k["engine"] == "orchestration"]
        finally:
            sink.close()

        sink2 = SQLiteTraceSink(sink_path)
        try:
            all_after = sink2.query_keys()
            orch_after = [k for k in all_after if k["engine"] == "orchestration"]
            assert len(orch_after) == len(orch_before)
        finally:
            sink2.close()


class TestSinkOrchestrationKeyQueries:
    """Query interface for orchestration keys."""

    def test_query_keys_includes_orchestration(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            orch_names = {k["key_name"] for k in all_keys if k["engine"] == "orchestration"}
            assert len(orch_names) == 6
        finally:
            sink.close()

    def test_component_candidate_filter_excludes_orchestration(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            candidates = sink.query_keys(component_candidate_only=True)
            orch_in_candidates = [
                k for k in candidates if k["key_name"].startswith("orchestration.")
            ]
            assert len(orch_in_candidates) == 0, (
                f"Orchestration keys should not appear in component_candidate_only: {orch_in_candidates}"
            )
        finally:
            sink.close()

    def test_query_by_engine_orchestration_no_traces(self, sink_path):
        """query_by_engine('orchestration') returns empty list when no traces written."""
        sink = SQLiteTraceSink(sink_path)
        try:
            rows = sink.query_by_engine("orchestration")
            assert rows == []
        finally:
            sink.close()

    def test_total_keys_after_phase_14(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            assert len(all_keys) == len(TRACE_KEY_REGISTRY) + len(COMPONENT_TRACE_KEYS)
        finally:
            sink.close()
