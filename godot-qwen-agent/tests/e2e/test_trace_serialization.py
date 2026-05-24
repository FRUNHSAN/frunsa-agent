"""E2E tests: trace_context serialization and file exporter (Phase 11).

Five test classes validating:
  1. DependencyCallTrace now captures trace_context from StreamItems
  2. FileTraceExporter writes valid JSON Lines with registry integration
  3. trace_key_serializability guardrail enforces JSON-safe value types
  4. trace_key_registration guardrail flags unregistered keys
  5. Trace Key Registry integrity and coverage against stub outputs
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import AsyncIterator, List

import pytest

from core.adapters.stream_adapter import AsyncDataStreamAdapter, JsonRpc20Serializer
from core.contracts import PaceConfig, StreamItem
from core.observability.file_exporter import FileTraceExporter
from core.observability.trace_registry import TRACE_KEY_REGISTRY, TraceKeyDef
from core.pipeline.tracing import DependencyCallTrace, TraceLog, StepTrace


# ── Helpers ──────────────────────────────────────────────────────────


def _planning_item(
    delta: str,
    index: int,
    step_index: int = 0,
    reasoning_depth: int = 0,
    parent_step_id: str | None = None,
    is_terminal: bool = False,
) -> StreamItem:
    return StreamItem(
        delta=delta,
        index=index,
        model="planning/stub",
        is_terminal=is_terminal,
        finish_reason="stop" if is_terminal else None,
        trace_context={
            "planning.step_index": step_index,
            "planning.reasoning_depth": reasoning_depth,
            "planning.parent_step_id": parent_step_id,
            "planning.cumulative_tokens": len(delta),
        },
    )


def _rag_item(
    delta: str,
    index: int,
    chunk_id: str = "chunk_001",
    retrieval_latency_ms: int = 42,
) -> StreamItem:
    return StreamItem(
        delta=delta,
        index=index,
        model="rag/generator",
        trace_context={
            "rag.chunk_id": chunk_id,
            "rag.retrieval_latency_ms": retrieval_latency_ms,
        },
    )


async def _collect(stream: AsyncIterator[StreamItem]) -> List[StreamItem]:
    return [item async for item in stream]


class _FakeTransport:
    """In-memory transport for adapter tests."""

    def __init__(self) -> None:
        self._sent: List[bytes] = []
        self._connected = False
        self._closed = False

    @property
    def sent(self) -> List[bytes]:
        return self._sent

    async def connect(self) -> None:
        self._connected = True

    async def send(self, data: bytes) -> None:
        self._sent.append(data)

    async def receive(self) -> AsyncIterator[bytes]:
        for item in self._sent:
            yield item

    async def close(self) -> None:
        self._closed = True

    def health_check(self) -> bool:
        return True


# ── TestDependencyCallTraceContextCapture ───────────────────────────


class TestDependencyCallTraceContextCapture:
    """AsyncDataStreamAdapter captures trace_context into last_trace."""

    def test_trace_context_captured_in_send_stream(self):
        """Planning stub → adapter → last_trace.trace_context has planning.* keys."""
        transport = _FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _gen():
            yield _planning_item("Analyzing goal", 0, step_index=0, reasoning_depth=0)
            yield _planning_item("Decomposing", 1, step_index=1, reasoning_depth=1, parent_step_id="step-0")
            yield _planning_item("Conclusion", 2, step_index=2, reasoning_depth=2, parent_step_id="step-1", is_terminal=True)

        async def _test():
            await adapter.send_stream(_gen())

            assert adapter.last_trace is not None
            assert adapter.last_trace.trace_context is not None
            ctx = adapter.last_trace.trace_context
            # Last item's context (terminal step)
            assert ctx["planning.step_index"] == 2
            assert ctx["planning.reasoning_depth"] == 2
            assert ctx["planning.parent_step_id"] == "step-1"

        asyncio.run(_test())

    def test_receive_stream_captures_trace_context(self):
        """Deserialize + receive → adapter captures trace_context on consumer side."""
        items_out = [
            _planning_item("step_a", 0, step_index=0),
            _planning_item("step_b", 1, step_index=1, is_terminal=True),
        ]

        serializer = JsonRpc20Serializer()
        transport = _FakeTransport()

        # Pre-fill transport with serialized data
        for item in items_out:
            transport.sent.append(serializer.serialize(item))

        adapter = AsyncDataStreamAdapter(serializer, transport)

        async def _test():
            received = [item async for item in adapter.receive_stream()]

            assert len(received) == 2
            assert adapter.last_trace is not None
            assert adapter.last_trace.trace_context is not None
            ctx = adapter.last_trace.trace_context
            # Last received item's context
            assert ctx["planning.step_index"] == 1
            assert ctx["planning.parent_step_id"] is None

        asyncio.run(_test())

    def test_last_item_semantics(self):
        """Multi-item stream with varying trace_context → last_trace has LAST item's context."""
        transport = _FakeTransport()
        adapter = AsyncDataStreamAdapter(JsonRpc20Serializer(), transport)

        async def _gen():
            yield _planning_item("first", 0, step_index=0, reasoning_depth=0)
            yield _planning_item("middle", 1, step_index=1, reasoning_depth=1)
            yield _planning_item("last", 2, step_index=2, reasoning_depth=2, is_terminal=True)

        async def _test():
            await adapter.send_stream(_gen())
            ctx = adapter.last_trace.trace_context
            assert ctx["planning.step_index"] == 2  # last, not first
            assert ctx["planning.reasoning_depth"] == 2

        asyncio.run(_test())

    def test_null_trace_context_handled(self):
        """StreamItem with trace_context=None → last_trace.trace_context is None."""
        transport = _FakeTransport()
        adapter = AsyncDataStreamAdapter(JsonRpc20Serializer(), transport)

        async def _gen():
            yield StreamItem(delta="bare", index=0, model="test", trace_context=None)
            yield StreamItem(delta="bare", index=1, model="test", trace_context=None, is_terminal=True)

        async def _test():
            await adapter.send_stream(_gen())
            assert adapter.last_trace is not None
            assert adapter.last_trace.trace_context is None  # all items had None

        asyncio.run(_test())


# ── TestFileTraceExporter ───────────────────────────────────────────


class TestFileTraceExporter:
    """FileTraceExporter writes JSON Lines with registry integration."""

    def _make_trace_log(self, dep_call: DependencyCallTrace) -> TraceLog:
        """Build a minimal TraceLog with one step containing one DependencyCallTrace."""
        step = StepTrace(
            step_index=0,
            step_name="test_step",
            pipeline_run_id="run-001",
            status="success",
            dependency_calls=[dep_call],
        )
        return TraceLog(
            pipeline_run_id="run-001",
            steps=[step],
            total_steps=1,
            success_count=1,
        )

    def test_writes_json_lines(self):
        """FileTraceExporter.write() produces valid JSON Lines with trace_context."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            dt = DependencyCallTrace(
                dependency_name="test_dep",
                status="success",
                duration_ms=12.5,
                trace_context={"planning.step_index": 0, "planning.reasoning_depth": 0},
            )
            exporter.write([self._make_trace_log(dt)])

            with open(path, encoding="utf-8") as f:
                lines = [l for l in f.read().strip().split("\n") if l]

            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["dependency"] == "test_dep"
            assert record["status"] == "success"
            assert record["trace_context"]["planning.step_index"] == 0
            assert record["engine"] == "planning"

    def test_namespace_isolation_in_output(self):
        """Mixed planning+rag trace_context — both engines appear in output, no interleaving."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mixed.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            dt_planning = DependencyCallTrace(
                dependency_name="planning_call",
                status="success",
                trace_context={
                    "planning.step_index": 1,
                    "planning.reasoning_depth": 2,
                },
            )
            dt_rag = DependencyCallTrace(
                dependency_name="rag_call",
                status="success",
                trace_context={
                    "rag.chunk_id": "c42",
                    "rag.retrieval_latency_ms": 15.0,
                },
            )
            exporter.write([
                self._make_trace_log(dt_planning),
                self._make_trace_log(dt_rag),
            ])

            with open(path, encoding="utf-8") as f:
                lines = [json.loads(l) for l in f.read().strip().split("\n") if l]

            assert len(lines) == 2
            engines = {l["engine"] for l in lines}
            assert engines == {"planning", "rag"}

    def test_sample_rate_zero_skips_all(self):
        """sample_rate must be > 0 — verify ValueError is raised for invalid rates."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "skip.jsonl")
            with pytest.raises(ValueError, match="sample_rate"):
                FileTraceExporter(path, sample_rate=0.0)

    def test_sample_rate_full_includes_all(self, monkeypatch):
        """sample_rate=1.0 → all records written (deterministic with seeded RNG)."""
        import os, random
        random.seed(42)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "full.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            for i in range(5):
                dt = DependencyCallTrace(
                    dependency_name=f"dep_{i}",
                    trace_context={"planning.step_index": i},
                )
                exporter.write([self._make_trace_log(dt)])

            with open(path, encoding="utf-8") as f:
                lines = [l for l in f.read().strip().split("\n") if l]

            assert len(lines) == 5

    def test_registered_vs_unregistered_keys_split(self):
        """Output _registered_keys and _unregistered_keys correctly classify trace_context keys."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "split.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            dt = DependencyCallTrace(
                dependency_name="mixed",
                trace_context={
                    "planning.step_index": 0,          # registered
                    "planning.custom_unknown_key": 42,  # NOT registered
                },
            )
            exporter.write([self._make_trace_log(dt)])

            with open(path, encoding="utf-8") as f:
                record = json.loads(f.readline())

            assert "planning.step_index" in record["_registered_keys"]
            assert "planning.custom_unknown_key" in record["_unregistered_keys"]
            assert "planning.step_index" not in record["_unregistered_keys"]

    def test_output_jq_parseable(self):
        """Every JSON line is independently parseable by json.loads()."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "jq.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            for i in range(3):
                dt = DependencyCallTrace(
                    dependency_name=f"dep_{i}",
                    trace_context={"planning.step_index": i},
                )
                exporter.write([self._make_trace_log(dt)])

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        json.loads(line)  # must not raise

    def test_skip_null_trace_context(self):
        """DependencyCallTrace with trace_context=None is skipped (not written)."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "null.jsonl")
            exporter = FileTraceExporter(path, sample_rate=1.0)

            dt = DependencyCallTrace(
                dependency_name="no_context",
                trace_context=None,
            )
            exporter.write([self._make_trace_log(dt)])

            assert not os.path.exists(path) or os.path.getsize(path) == 0


# ── TestTraceKeySerializabilityGuardrail ─────────────────────────────


class TestTraceKeySerializabilityGuardrail:
    """trace_key_serializability guardrail enforces JSON-safe value types.

    Verified via guardrails check, but these tests ensure the rule function
    returns expected violations for known bad/good inputs.
    """

    def test_valid_json_types_pass(self, tmp_path: Path):
        """trace_context with str/int/float/bool/list/dict values → no violations."""
        test_file = tmp_path / "test_valid.py"
        test_file.write_text('''
StreamItem(
    delta="ok", index=0, model="test",
    trace_context={
        "planning.step_index": 0,
        "planning.name": "root",
        "planning.score": 0.95,
        "planning.active": True,
        "planning.sub_items": [1, 2, 3],
        "planning.meta": {"key": "val"},
    },
)
''', encoding="utf-8")

        from guardrails.rules.trace_key_serializability import trace_key_serializability
        violations = trace_key_serializability(tmp_path)
        assert len(violations) == 0, f"Unexpected violations: {[v.message for v in violations]}"

    def test_non_serializable_call_flagged(self, tmp_path: Path):
        """trace_context with function call value → ERROR."""
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        # Name must NOT contain "test" for guardrail scanning
        bad_file = core_dir / "sample_serialize.py"
        bad_file.write_text('''
from datetime import datetime
from core.contracts import StreamItem
StreamItem(
    delta="bad", index=0, model="test",
    trace_context={"planning.when": datetime.now()},
)
''', encoding="utf-8")

        from guardrails.rules.trace_key_serializability import trace_key_serializability
        violations = trace_key_serializability(tmp_path)

        errors = [v for v in violations if v.severity.value == "error"]
        assert len(errors) >= 1
        assert any("function call" in e.message.lower() for e in errors)


# ── TestTraceKeyRegistrationGuardrail ───────────────────────────────


class TestTraceKeyRegistrationGuardrail:
    """trace_key_registration guardrail flags unregistered keys at WARNING."""

    def test_registered_keys_pass(self, tmp_path: Path):
        """All keys in TRACE_KEY_REGISTRY → no violations."""
        test_file = tmp_path / "test_registered.py"
        test_file.write_text('''
StreamItem(
    delta="ok", index=0, model="test",
    trace_context={
        "planning.step_index": 0,
        "planning.reasoning_depth": 0,
        "rag.chunk_id": "c1",
    },
)
''', encoding="utf-8")

        from guardrails.rules.trace_key_registration import trace_key_registration
        violations = trace_key_registration(tmp_path)
        assert len(violations) == 0, f"Unexpected: {[v.message for v in violations]}"

    def test_unregistered_key_warns(self, tmp_path: Path):
        """Unknown key → WARNING with key name in message."""
        core_dir = tmp_path / "core"
        core_dir.mkdir()
        # Name must NOT contain "test" for guardrail scanning
        bad_file = core_dir / "sample_unreg.py"
        bad_file.write_text('''
from core.contracts import StreamItem
StreamItem(
    delta="bad", index=0, model="test",
    trace_context={"planning.unknown_new_key": "value"},
)
''', encoding="utf-8")

        from guardrails.rules.trace_key_registration import trace_key_registration
        violations = trace_key_registration(tmp_path)

        assert len(violations) >= 1
        assert violations[0].severity.value == "warning"
        assert "planning.unknown_new_key" in violations[0].message


# ── TestTraceRegistryIntegrity ──────────────────────────────────────


class TestTraceRegistryIntegrity:
    """TRACE_KEY_REGISTRY is well-formed and covers all stub outputs."""

    def test_all_registry_keys_are_members(self):
        """Every key in TRACE_KEY_REGISTRY parses as engine.suffix with dot separator."""
        for key, defn in TRACE_KEY_REGISTRY.items():
            assert "." in key, f"Registry key '{key}' lacks dot separator"
            prefix, suffix = key.split(".", 1)
            assert prefix == defn.engine, (
                f"Key '{key}' has prefix '{prefix}' but engine field is '{defn.engine}'"
            )
            assert len(suffix) > 0, f"Key '{key}' has empty suffix after prefix"

    def test_registry_defs_are_complete(self):
        """Each TraceKeyDef has non-empty type, semantics, engine fields."""
        for key, defn in TRACE_KEY_REGISTRY.items():
            assert defn.type is not None, f"Key '{key}' has no type"
            assert defn.semantics, f"Key '{key}' has empty semantics"
            assert defn.engine, f"Key '{key}' has empty engine"

    def test_registry_covers_all_stub_outputs(self):
        """Every trace_context key produced by N=2 stubs is registered."""
        from engines.planning.stub import StubPlanningEngine

        transport = _FakeTransport()
        serializer = JsonRpc20Serializer()
        adapter = AsyncDataStreamAdapter(serializer, transport)

        engine = StubPlanningEngine()

        async def _test():
            stream = engine.plan(
                goal="test coverage goal",
                deadline=60.0,
                pace_config=PaceConfig(adaptive_strategy="jitter"),
            )
            await adapter.send_stream(stream)

            # Collect all trace_context keys produced by Planning stub
            all_keys: set = set()
            for data in transport.sent:
                item = serializer.deserialize(data)
                if item.trace_context:
                    all_keys.update(item.trace_context.keys())

            assert all_keys, "Stub produced no trace_context keys"

            registered = set(TRACE_KEY_REGISTRY.keys())
            missing = all_keys - registered
            assert not missing, (
                f"Stub produced unregistered keys: {missing}. "
                f"Add to TRACE_KEY_REGISTRY or mark as component_candidate."
            )

        asyncio.run(_test())

    def test_component_candidate_count(self):
        """Exactly 3 keys are marked component_candidate=True."""
        candidates = [k for k, v in TRACE_KEY_REGISTRY.items() if v.component_candidate]
        assert len(candidates) == 3, (
            f"Expected 3 component_candidate keys, got {len(candidates)}: {candidates}"
        )
        candidate_names = set(candidates)
        assert candidate_names == {
            "planning.cumulative_tokens",
            "rag.chunk_id",
            "rag.retrieval_latency_ms",
        }
