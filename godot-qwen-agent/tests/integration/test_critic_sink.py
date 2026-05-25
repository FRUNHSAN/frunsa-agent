"""Integration tests for critic.* trace key seeding in SQLiteSink (Phase 16)."""

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


class TestSinkCriticKeySeeding:
    """Critic key seeding in SQLiteTraceSink."""

    def test_critic_keys_seeded_with_correct_engine(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            critic_rows = [k for k in all_keys if k["key_name"].startswith("critic.")]
            assert len(critic_rows) == 2, f"Expected 2 critic keys, got {len(critic_rows)}"
            for row in critic_rows:
                assert row["engine"] == "critic", (
                    f"{row['key_name']} engine={row['engine']}, expected 'critic'"
                )
        finally:
            sink.close()

    def test_critic_keys_component_candidate_false(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            critic_rows = [k for k in all_keys if k["key_name"].startswith("critic.")]
            for row in critic_rows:
                assert row["component_candidate"] == 0, (
                    f"{row['key_name']} component_candidate={row['component_candidate']}"
                )
        finally:
            sink.close()

    def test_critic_score_value_type_is_float(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            score_row = [k for k in all_keys if k["key_name"] == "critic.score"][0]
            assert score_row["value_type"] == "float", (
                f"critic.score value_type={score_row['value_type']}"
            )
        finally:
            sink.close()

    def test_critic_verdict_value_type_is_str(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            verdict_row = [k for k in all_keys if k["key_name"] == "critic.verdict"][0]
            assert verdict_row["value_type"] == "str", (
                f"critic.verdict value_type={verdict_row['value_type']}"
            )
        finally:
            sink.close()

    def test_total_keys_after_phase_16_is_18(self, sink_path):
        sink = SQLiteTraceSink(sink_path)
        try:
            all_keys = sink.query_keys()
            expected = len(TRACE_KEY_REGISTRY) + len(COMPONENT_TRACE_KEYS)
            assert len(all_keys) == expected, (
                f"Expected {expected} keys, got {len(all_keys)}"
            )
        finally:
            sink.close()
