"""Integration tests for agent.identity trace key seeding + queries in SQLiteSink (Phase 15)."""

import os
import tempfile

import pytest

from core.observability.sqlite_sink import SQLiteTraceSink
from core.observability.trace_registry import TRACE_KEY_REGISTRY


@pytest.fixture
def sink_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "test.db")


class TestSinkAgentIdentityKeySeeding:
    """Agent identity key seeding in SQLiteTraceSink."""

    def test_agent_identity_seeded(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            agent_rows = [k for k in all_keys if k["key_name"].startswith("agent.")]
            assert len(agent_rows) == 1
            assert agent_rows[0]["key_name"] == "agent.identity"
        finally:
            sink.close()

    def test_agent_identity_engine_is_planning(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            agent_row = [k for k in all_keys if k["key_name"] == "agent.identity"][0]
            assert agent_row["engine"] == "planning", (
                f"agent.identity engine={agent_row['engine']}, expected 'planning'"
            )
        finally:
            sink.close()

    def test_agent_identity_component_candidate_false(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            agent_row = [k for k in all_keys if k["key_name"] == "agent.identity"][0]
            assert agent_row["component_candidate"] == 0, (
                f"agent.identity component_candidate={agent_row['component_candidate']}"
            )
        finally:
            sink.close()

    def test_agent_identity_value_type_is_dict(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            agent_row = [k for k in all_keys if k["key_name"] == "agent.identity"][0]
            assert agent_row["value_type"] == "dict", (
                f"agent.identity value_type={agent_row['value_type']}"
            )
        finally:
            sink.close()

    def test_no_duplicate_agent_seeding(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_before = sink.query_keys()
            agent_before = [k for k in all_before if k["key_name"].startswith("agent.")]
        finally:
            sink.close()

        sink2 = SQLiteTraceSink(sink_path)
        try:
            all_after = sink2.query_keys()
            agent_after = [k for k in all_after if k["key_name"].startswith("agent.")]
            assert len(agent_after) == len(agent_before)
        finally:
            sink2.close()


class TestSinkAgentIdentityQueries:
    """Query interface for agent identity keys."""

    def test_query_keys_includes_agent_identity(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            agent_names = {k["key_name"] for k in all_keys if k["key_name"].startswith("agent.")}
            assert agent_names == {"agent.identity"}
        finally:
            sink.close()

    def test_component_candidate_filter_excludes_agent(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            candidates = sink.query_keys(component_candidate_only=True)
            agent_in_candidates = [
                k for k in candidates if k["key_name"].startswith("agent.")
            ]
            assert len(agent_in_candidates) == 0, (
                f"agent keys should not appear in component_candidate_only: {agent_in_candidates}"
            )
        finally:
            sink.close()

    def test_total_keys_after_phase_15(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            assert len(all_keys) == 16  # 6 engine + 3 component + 6 orchestration + 1 agent
        finally:
            sink.close()
