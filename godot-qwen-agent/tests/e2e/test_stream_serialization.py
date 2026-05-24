"""E2E tests: StreamItem serialization — JSON-RPC 2.0 round-trip and PaceConfig contract.

TDD anchor: test_serialize_invalid_state_raises is written BEFORE
JsonRpc20Serializer implementation to enforce the state machine guard.
"""

from __future__ import annotations

import asyncio
import pytest

from core.contracts import PaceConfig, StreamItem
from core.adapters.stream_adapter import JsonRpc20Serializer


# ── Helpers ──────────────────────────────────────────────────────────

def _data_item(delta: str = "hello", index: int = 0) -> StreamItem:
    return StreamItem(delta=delta, index=index, model="test/model")


def _terminal_item(finish_reason: str = "stop", index: int = 5) -> StreamItem:
    return StreamItem(
        delta="", index=index, finish_reason=finish_reason,
        model="test/model", is_terminal=True,
    )


def _error_terminal(error: str = "upstream_timeout", index: int = -1) -> StreamItem:
    return StreamItem(
        delta="", index=index, finish_reason="error",
        is_terminal=True, error=error, model="test/model",
    )


# ── TestJsonRpcSerializer ────────────────────────────────────────────


class TestJsonRpcSerializer:
    """JSON-RPC 2.0 serializer: all 4 StreamItem states + round-trip fidelity."""

    def test_serialize_data_item(self):
        """Data items use method=stream.item."""
        serializer = JsonRpc20Serializer()
        item = _data_item("hello world", 3)
        data = serializer.serialize(item)

        assert b"stream.item" in data
        assert b"hello world" in data
        assert b'"index":3' in data

    def test_serialize_normal_terminal(self):
        """Normal terminal uses method=stream.finish."""
        serializer = JsonRpc20Serializer()
        item = _terminal_item("stop", 10)
        data = serializer.serialize(item)

        assert b"stream.finish" in data
        assert b'"is_terminal":true' in data

    def test_serialize_error_terminal(self):
        """Error terminal uses method=stream.error."""
        serializer = JsonRpc20Serializer()
        item = _error_terminal("connection_refused")
        data = serializer.serialize(item)

        assert b"stream.error" in data
        assert b"connection_refused" in data

    def test_serialize_invalid_state_raises(self):
        """Illegal state (is_terminal=False, error!=None) MUST be caught.

        TDD anchor — this test forces serialize() to validate state
        BEFORE any serialization logic.
        """
        serializer = JsonRpc20Serializer()
        invalid_item = StreamItem(
            delta="some chunk", index=0,
            is_terminal=False,
            error="unexpected error",
        )
        with pytest.raises(ValueError, match="Non-terminal item cannot carry error"):
            serializer.serialize(invalid_item)

    def test_round_trip_data_item(self):
        """Data item survives serialize → deserialize round-trip."""
        serializer = JsonRpc20Serializer()
        original = _data_item("hello world", 7)
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.delta == original.delta
        assert deserialized.index == original.index
        assert deserialized.finish_reason == original.finish_reason
        assert deserialized.model == original.model
        assert deserialized.is_terminal == original.is_terminal
        assert deserialized.error == original.error

    def test_round_trip_terminal(self):
        """Terminal item survives round-trip."""
        serializer = JsonRpc20Serializer()
        original = _terminal_item("stop", 42)
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.is_terminal is True
        assert deserialized.finish_reason == "stop"
        assert deserialized.index == 42

    def test_round_trip_error_terminal(self):
        """Error terminal survives round-trip with error preserved."""
        serializer = JsonRpc20Serializer()
        original = _error_terminal("k8s_oom_killed")
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.is_terminal is True
        assert deserialized.finish_reason == "error"
        assert deserialized.error == "k8s_oom_killed"

    def test_round_trip_with_trace_context(self):
        """trace_context opaque bag survives round-trip (Phase 9.1)."""
        serializer = JsonRpc20Serializer()
        ctx = {"step_index": 3, "reasoning_depth": 2, "parent_step_id": "abc123"}
        original = StreamItem(
            delta="reasoning result", index=1, model="test/planning",
            trace_context=ctx,
        )
        deserialized = serializer.deserialize(serializer.serialize(original))
        assert deserialized.trace_context == ctx

    def test_round_trip_no_trace_context(self):
        """trace_context=None round-trips correctly (backward compat)."""
        serializer = JsonRpc20Serializer()
        original = _data_item("hello", 0)
        deserialized = serializer.deserialize(serializer.serialize(original))
        assert deserialized.trace_context is None

    def test_round_trip_empty_delta(self):
        """Empty delta round-trip works (used for terminal items)."""
        serializer = JsonRpc20Serializer()
        original = StreamItem(delta="", index=0, is_terminal=True, finish_reason="stop")
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.delta == ""
        assert deserialized.is_terminal is True

    def test_round_trip_unicode(self):
        """Unicode content survives round-trip without corruption."""
        serializer = JsonRpc20Serializer()
        original = _data_item("你好世界 🌍", 1)
        deserialized = serializer.deserialize(serializer.serialize(original))

        assert deserialized.delta == "你好世界 🌍"

    def test_serialize_produces_valid_utf8(self):
        """Output is always valid UTF-8 bytes."""
        serializer = JsonRpc20Serializer()
        data = serializer.serialize(_data_item("hello", 0))
        data.decode("utf-8")  # no UnicodeDecodeError


# ── TestPaceConfig ───────────────────────────────────────────────────


class TestPaceConfig:
    """PaceConfig frozen dataclass contract."""

    def test_defaults(self):
        config = PaceConfig()
        assert config.item_throughput is None
        assert config.burst_size == 0
        assert config.adaptive is False
        assert config.adaptive_strategy is None

    def test_frozen_prevents_mutation(self):
        config = PaceConfig(item_throughput=10.0)
        with pytest.raises(Exception):
            config.item_throughput = 20.0  # type: ignore

    def test_negative_throughput_raises(self):
        with pytest.raises(ValueError, match="item_throughput must be >= 0"):
            PaceConfig(item_throughput=-1.0)

    def test_negative_burst_size_raises(self):
        with pytest.raises(ValueError, match="burst_size must be >= 0"):
            PaceConfig(burst_size=-1)

    def test_custom_values(self):
        config = PaceConfig(item_throughput=50.0, burst_size=10, adaptive=True)
        assert config.item_throughput == 50.0
        assert config.burst_size == 10
        assert config.adaptive is True

    def test_adaptive_strategy_extension_point(self):
        """adaptive_strategy is an open extension point — any string is valid."""
        config = PaceConfig(
            item_throughput=10.0, adaptive=True, adaptive_strategy="jitter"
        )
        assert config.adaptive_strategy == "jitter"

    def test_adaptive_strategy_default_none(self):
        """Default adaptive_strategy is None (linear scaling)."""
        config = PaceConfig(adaptive=True)
        assert config.adaptive_strategy is None


# ── TestProtocolConformance ──────────────────────────────────────────


class TestProtocolConformance:
    """Verify SerializationFormat protocol conformance."""

    def test_json_rpc_serializer_has_required_methods(self):
        serializer = JsonRpc20Serializer()
        assert hasattr(serializer, "serialize")
        assert hasattr(serializer, "deserialize")
        assert callable(serializer.serialize)
        assert callable(serializer.deserialize)


# ── TestEdgeCases ────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions for serialization."""

    def test_very_long_delta(self):
        """Very long delta text does not crash serialization."""
        serializer = JsonRpc20Serializer()
        long_text = "x" * 100_000
        item = _data_item(long_text, 0)
        data = serializer.serialize(item)
        deserialized = serializer.deserialize(data)
        assert deserialized.delta == long_text

    def test_finish_reason_length(self):
        """Various finish_reason values survive round-trip."""
        serializer = JsonRpc20Serializer()
        for reason in ["stop", "length", "content_filter", "error", None]:
            item = StreamItem(
                delta="test", index=0, finish_reason=reason,
                is_terminal=(reason is not None),
            )
            deserialized = serializer.deserialize(serializer.serialize(item))
            assert deserialized.finish_reason == reason
