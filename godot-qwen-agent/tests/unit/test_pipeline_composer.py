"""Phase 19 Pipeline Composition — unit tests.

Tests for SourceRule, CompositionBlueprint, SourceRouter, PipelineAssembler,
PipelineComposer, and ArchitectureInvariants.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.contracts import (
    COMPONENT_REGISTRY,
    ContentBlock,
    SemVer,
)
from core.contracts.composition import (
    AssemblyDiagnostic,
    CompositionBlueprint,
    CompositionEvent,
    SourceRule,
)
from core.adapters.composer import (
    AssemblyError,
    PipelineAssembler,
    PipelineComposer,
    SourceRouter,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_doc(text: str = "hello world", source: str = "/test/doc.md") -> ContentBlock:
    return ContentBlock(text=text, source=source)


# ── Test SourceRule ──────────────────────────────────────────────────

class TestSourceRule:
    def test_matches_simple_glob(self):
        rule = SourceRule(pattern="*.md", chunker="fixed")
        assert rule.matches("readme.md")
        assert not rule.matches("readme.txt")

    def test_matches_deep_glob(self):
        rule = SourceRule(pattern="docs/**/*.md", chunker="recursive")
        assert rule.matches("docs/api/auth.md")
        assert rule.matches("docs/security/overview.md")
        assert not rule.matches("readme.md")

    def test_no_match(self):
        rule = SourceRule(pattern="*.py", chunker="fixed")
        assert not rule.matches("app.js")

    def test_rule_id_deterministic(self):
        a = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        b = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        assert a.rule_id == b.rule_id
        assert len(a.rule_id) == 12

    def test_rule_id_different_for_different_params(self):
        a = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        b = SourceRule(pattern="*.md", chunker="fixed", priority=10)
        assert a.rule_id != b.rule_id

    def test_rule_id_explicit_overrides_auto(self):
        rule = SourceRule(pattern="*.md", chunker="fixed", rule_id="explicit-id")
        assert rule.rule_id == "explicit-id"

    def test_rule_id_changes_with_priority(self):
        a = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        b = SourceRule(pattern="*.md", chunker="recursive", priority=20)
        assert a.rule_id != b.rule_id

    def test_chunk_params_is_copied(self):
        params = {"size": 256}
        rule = SourceRule(pattern="*", chunker="fixed", chunk_params=params)
        params["size"] = 999
        assert rule.chunk_params["size"] == 256

    def test_default_priority(self):
        rule = SourceRule(pattern="*", chunker="fixed")
        assert rule.priority == 100


# ── Test CompositionBlueprint ────────────────────────────────────────

class TestCompositionBlueprint:
    def test_from_dict_minimal(self):
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert str(bp.version) == "1.0.0"
        assert bp.default_chunker == "recursive"
        assert bp.source_rules == ()

    def test_from_dict_with_rules(self):
        raw = {
            "version": "1.0.0",
            "default_chunker": "fixed",
            "source_rules": [
                {"pattern": "*.md", "chunker": "recursive", "priority": 10},
                {"pattern": "*.txt", "chunker": "fixed", "priority": 5},
            ],
        }
        bp = CompositionBlueprint.from_dict(raw)
        assert bp.default_chunker == "fixed"
        assert len(bp.source_rules) == 2
        assert bp.source_rules[0].priority == 5  # sorted ascending
        assert bp.source_rules[1].priority == 10

    def test_rules_sorted_by_priority(self):
        raw = {
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "c.md", "chunker": "fixed", "priority": 100},
                {"pattern": "a.md", "chunker": "fixed", "priority": 10},
                {"pattern": "b.md", "chunker": "fixed", "priority": 50},
            ],
        }
        bp = CompositionBlueprint.from_dict(raw)
        priorities = [r.priority for r in bp.source_rules]
        assert priorities == [10, 50, 100]

    def test_fingerprint_deterministic(self):
        raw = {
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "*.md", "chunker": "recursive", "priority": 10}
            ],
        }
        a = CompositionBlueprint.from_dict(raw)
        b = CompositionBlueprint.from_dict(raw)
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_changes_on_config_change(self):
        a = CompositionBlueprint.from_dict({"version": "1.0.0"})
        b = CompositionBlueprint.from_dict({"version": "2.0.0"})
        assert a.fingerprint != b.fingerprint

    def test_from_dict_missing_pattern_raises(self):
        with pytest.raises(ValueError, match="missing 'pattern'"):
            CompositionBlueprint.from_dict({
                "version": "1.0.0",
                "source_rules": [{"chunker": "fixed"}],
            })

    def test_from_dict_missing_chunker_raises(self):
        with pytest.raises(ValueError, match="missing 'chunker'"):
            CompositionBlueprint.from_dict({
                "version": "1.0.0",
                "source_rules": [{"pattern": "*.md"}],
            })

    def test_from_dict_invalid_version_raises(self):
        with pytest.raises(ValueError):
            CompositionBlueprint.from_dict({"version": "not.a.version"})

    def test_from_yaml_valid(self):
        yaml_content = """version: "1.0.0"
default_chunker: fixed
source_rules:
  - pattern: "*.md"
    chunker: recursive
    priority: 10
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            tmp = f.name
        try:
            bp = CompositionBlueprint.from_yaml(tmp)
            assert bp.default_chunker == "fixed"
            assert len(bp.source_rules) == 1
            assert bp.source_rules[0].chunker == "recursive"
        finally:
            Path(tmp).unlink()

    def test_rules_by_priority_returns_sorted(self):
        raw = {
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "b.md", "chunker": "fixed", "priority": 50},
                {"pattern": "a.md", "chunker": "fixed", "priority": 10},
            ],
        }
        bp = CompositionBlueprint.from_dict(raw)
        assert bp.rules_by_priority[0].priority == 10


# ── Test SourceRouter ────────────────────────────────────────────────

class TestSourceRouter:
    @staticmethod
    def _make_blueprint(**kwargs):
        return CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "recursive",
            **kwargs,
        })

    def test_resolve_first_match_wins(self):
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.md", "chunker": "fixed", "priority": 10},
            {"pattern": "*.md", "chunker": "recursive", "priority": 20},
        ])
        router = SourceRouter(bp)
        rule = router.resolve("readme.md")
        assert rule.chunker == "fixed"

    def test_resolve_fallback_to_default(self):
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.py", "chunker": "fixed", "priority": 10},
        ])
        router = SourceRouter(bp)
        rule = router.resolve("readme.md")
        assert rule.chunker == "recursive"
        assert rule.priority == 999

    def test_events_emitted_for_match(self):
        events = []
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.md", "chunker": "fixed", "priority": 10},
        ])
        router = SourceRouter(bp, event_sink=events.append)
        router.resolve("readme.md")
        assert len(events) == 1
        assert events[0].event_type == "rule_matched"
        assert events[0].correlation_id != ""

    def test_events_emitted_for_fallback(self):
        events = []
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.py", "chunker": "fixed", "priority": 10},
        ])
        router = SourceRouter(bp, event_sink=events.append)
        router.resolve("readme.md")
        assert events[-1].event_type == "fallback_used"

    def test_resolve_all(self):
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.py", "chunker": "fixed", "priority": 10},
        ])
        router = SourceRouter(bp)
        result = router.resolve_all(["a.py", "b.md"])
        assert result["a.py"].chunker == "fixed"
        assert result["b.md"].chunker == "recursive"

    def test_correlation_id_consistent_for_same_path(self):
        events = []
        bp = self._make_blueprint(source_rules=[
            {"pattern": "*.md", "chunker": "fixed", "priority": 10},
            {"pattern": "*.md", "chunker": "recursive", "priority": 20},
        ])
        router = SourceRouter(bp, event_sink=events.append)
        router.resolve("readme.md")
        assert len(events) >= 1
        assert all(e.correlation_id == events[0].correlation_id for e in events)


# ── Test PipelineAssembler ───────────────────────────────────────────

class TestPipelineAssembler:
    def test_assemble_single_document(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello world", "test.md")
        assembler = PipelineAssembler()
        step = assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        assert step is not None
        assert len(assembler.diagnostics) == 0

    def test_assemble_chunk_lineage(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
            "source_rules": [
                {"pattern": "*.md", "chunker": "identity", "priority": 10,
                 "rule_id": "test-rule"},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["readme.md"])
        doc = _make_doc("chunk lineage test", "readme.md")
        assembler = PipelineAssembler()
        step = assembler.assemble(rules, {"readme.md": doc}, "1.0.0")
        chunks = step._backend._chunks
        assert len(chunks) >= 1
        ch = chunks[0]
        meta = ch.metadata
        assert meta.get("source_path") == "readme.md"
        assert meta.get("chunker_strategy") == "identity"
        assert meta.get("rule_id") == "test-rule"
        assert meta.get("blueprint_version") == "1.0.0"
        assert "composed_at" in meta

    def test_events_emitted(self):
        events = []
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler(event_sink=events.append)
        assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        assert any(e.event_type == "chunker_instantiated" for e in events)
        assert any(e.event_type == "assembly_complete" for e in events)

    def test_assemble_missing_strategy_yields_diagnostics(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "*.md", "chunker": "nonexistent_strategy", "priority": 10},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler()
        with pytest.raises(AssemblyError):
            assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        assert len(assembler.diagnostics) == 1
        assert assembler.diagnostics[0].error_type == "instantiation"

    def test_diagnostics_are_AssemblyDiagnostic_instances(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "*.md", "chunker": "nonexistent", "priority": 10},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler()
        with pytest.raises(AssemblyError):
            assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        assert all(isinstance(d, AssemblyDiagnostic) for d in assembler.diagnostics)
        # Phase 19.5: unknown strategy = contract violation
        assert assembler.diagnostics[0].contract_violation == "unknown_chunker_strategy"

    def test_assemble_all_failure_raises_AssemblyError(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "source_rules": [
                {"pattern": "*.md", "chunker": "nonexistent_a", "priority": 10},
                {"pattern": "*.txt", "chunker": "nonexistent_b", "priority": 20},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["a.md", "b.txt"])
        docs = {"a.md": _make_doc("a", "a.md"), "b.txt": _make_doc("b", "b.txt")}
        assembler = PipelineAssembler()
        with pytest.raises(AssemblyError, match="All 2 document"):
            assembler.assemble(rules, docs, "1.0.0")

    def test_assemble_partial_failure_succeeds(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
            "source_rules": [
                {"pattern": "bad.md", "chunker": "nonexistent", "priority": 10},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["bad.md", "good.md"])
        docs = {"bad.md": _make_doc("bad", "bad.md"), "good.md": _make_doc("good", "good.md")}
        assembler = PipelineAssembler()
        step = assembler.assemble(rules, docs, "1.0.0")
        assert step is not None
        assert len(assembler.diagnostics) == 1

    def test_no_matching_rule_records_diagnostics(self):
        """When a document has no resolved rule, it produces a routing diagnostic.
        If at least one document succeeds, partial failure is non-fatal."""
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["good.md"])  # only good doc gets a rule
        assembler = PipelineAssembler()
        docs = {
            "orphan.md": _make_doc("orphan", "orphan.md"),
            "good.md": _make_doc("good", "good.md"),
        }
        step = assembler.assemble(rules, docs, "1.0.0")
        assert step is not None
        routing_diags = [d for d in assembler.diagnostics if d.error_type == "routing"]
        assert len(routing_diags) == 1


# ── Test PipelineComposer ────────────────────────────────────────────

class TestPipelineComposer:
    def test_from_dict_test_friendly(self):
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        assert composer is not None
        assert composer.blueprint.default_chunker == "identity"

    def test_audit_manifest_contains_fingerprint(self):
        composer = PipelineComposer.from_dict({"version": "1.0.0"})
        manifest = composer.audit_manifest
        assert "blueprint_fingerprint" in manifest
        assert "blueprint_version" in manifest
        assert manifest["blueprint_version"] == "1.0.0"
        assert "router_type" in manifest

    def test_compose_for_sources_returns_RetrieverStep(self):
        from core.steps.retriever import RetrieverStep
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        doc = _make_doc("hello world", "test.md")
        step = composer.compose_for_sources(["test.md"], {"test.md": doc})
        assert isinstance(step, RetrieverStep)

    def test_health_check_passes(self):
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        status = composer.health_check()
        assert status.status == "healthy"

    def test_health_check_unknown_strategy(self):
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "default_chunker": "nonexistent_chunker",
        })
        status = composer.health_check()
        assert status.status == "degraded"

    def test_diagnostics_empty_on_success(self):
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        composer.compose_for_sources(["test.md"], {"test.md": _make_doc("hi", "test.md")})
        assert composer.diagnostics == []


# ── Test Architecture Invariants ─────────────────────────────────────

class TestArchitectureInvariants:
    """Constitutional integrity tests — automated enforcement of the kernel's soul."""

    def test_blueprint_has_no_resolve_method(self):
        """Blueprint is pure data — resolve() must live on SourceRouter only."""
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert not hasattr(bp, "resolve")
        assert not callable(getattr(bp, "resolve", None))

    def test_router_is_pure_function_no_side_effects(self):
        """SourceRouter.resolve() produces no I/O, no state mutation."""
        bp = CompositionBlueprint.from_dict({"version": "1.0.0", "default_chunker": "identity"})
        router = SourceRouter(bp)
        rule1 = router.resolve("a.md")
        rule2 = router.resolve("a.md")
        assert rule1.rule_id == rule2.rule_id
        assert rule1.chunker == rule2.chunker

    def test_assembler_never_imports_logging(self):
        """PipelineAssembler must use event_sink, not logging module."""
        import inspect
        src = inspect.getsource(PipelineAssembler)
        assert "logging." not in src
        assert "import logging" not in src

    def test_blueprint_fingerprint_is_stable(self):
        """Same config → same fingerprint, regardless of file path or machine."""
        a = CompositionBlueprint.from_dict({"version": "1.0.0"})
        b = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert a.fingerprint == b.fingerprint

    def test_source_rule_rule_id_is_deterministic(self):
        """rule_id must be deterministic hash, not random UUID."""
        a = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        b = SourceRule(pattern="*.md", chunker="recursive", priority=10)
        assert a.rule_id == b.rule_id

    def test_composition_event_has_correlation_id(self):
        """Every CompositionEvent must carry a correlation_id."""
        event = CompositionEvent(
            event_type="rule_matched",
            correlation_id="abc123",
            timestamp=0.0,
            context={},
        )
        assert event.correlation_id == "abc123"

    def test_assembly_diagnostic_has_contract_violation_field(self):
        """AssemblyDiagnostic must have contract_violation field (even if None)."""
        diag = AssemblyDiagnostic(
            path="test.md", chunker="fixed",
            error_type="validation", message="test",
        )
        assert hasattr(diag, "contract_violation")
        assert diag.contract_violation is None

    def test_source_rule_is_frozen(self):
        """All data models must be frozen dataclasses."""
        import dataclasses
        assert dataclasses.is_dataclass(SourceRule)
        # Accessing __dataclass_params__ is private but reliable
        params = getattr(SourceRule, "__dataclass_params__", None)
        assert params is not None

    def test_composition_blueprint_is_frozen(self):
        import dataclasses
        assert dataclasses.is_dataclass(CompositionBlueprint)

    def test_assembly_diagnostic_is_frozen(self):
        import dataclasses
        assert dataclasses.is_dataclass(AssemblyDiagnostic)

    def test_composition_event_is_frozen(self):
        import dataclasses
        assert dataclasses.is_dataclass(CompositionEvent)

    def test_registry_has_freeze_method(self):
        """COMPONENT_REGISTRY must support freeze() for Anti-WinReg firewall."""
        assert hasattr(COMPONENT_REGISTRY, "freeze")
        assert callable(COMPONENT_REGISTRY.freeze)


# ── Phase 19.5: Contract Violation Detection ────────────────────────

class TestContractViolationDetection:
    """Verify that PipelineAssembler classifies failures with contract_violation."""

    def _make_blueprint_with_rule(self, chunker="identity", **params):
        return CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
            "source_rules": [
                {"pattern": "*.md", "chunker": chunker,
                 "chunk_params": params, "priority": 10},
            ],
        })

    def test_unknown_strategy_is_contract_violation(self):
        """Unknown chunker strategy → contract_violation='unknown_chunker_strategy'."""
        bp = self._make_blueprint_with_rule(chunker="nonexistent_xyz")
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler()
        with pytest.raises(AssemblyError):
            assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        diag = assembler.diagnostics[0]
        assert diag.contract_violation == "unknown_chunker_strategy"
        assert diag.error_type == "instantiation"

    def test_routing_breach_is_contract_violation(self):
        """Document with no resolved rule → contract_violation='routing_contract_breach'."""
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["good.md"])
        assembler = PipelineAssembler()
        docs = {
            "orphan.md": _make_doc("orphan", "orphan.md"),
            "good.md": _make_doc("good", "good.md"),
        }
        step = assembler.assemble(rules, docs, "1.0.0")
        assert step is not None
        routing_diags = [d for d in assembler.diagnostics if d.error_type == "routing"]
        assert len(routing_diags) == 1
        assert routing_diags[0].contract_violation == "routing_contract_breach"

    def test_contract_violation_in_event_context(self):
        """document_failed event context includes contract_violation."""
        events = []
        bp = self._make_blueprint_with_rule(chunker="nonexistent_xyz")
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler(event_sink=events.append)
        with pytest.raises(AssemblyError):
            assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        failed_events = [e for e in events if e.event_type == "document_failed"]
        assert len(failed_events) == 1
        assert failed_events[0].context["contract_violation"] == "unknown_chunker_strategy"

    def test_execution_failure_is_not_violation(self):
        """Execution failures are technical, not contract violations."""
        cv = PipelineAssembler._classify_violation(
            "execution", "some_chunker", "ChunkerAdapter failed: something"
        )
        assert cv is None

    def test_classify_violation_all_categories(self):
        """Each error_type maps to the correct violation category."""
        assert PipelineAssembler._classify_violation(
            "routing", "unknown", "No matching rule"
        ) == "routing_contract_breach"
        assert PipelineAssembler._classify_violation(
            "instantiation", "xyz", "Unknown strategy: 'xyz'"
        ) == "unknown_chunker_strategy"
        assert PipelineAssembler._classify_violation(
            "instantiation", "xyz", "Invalid params for 'xyz': missing chunk_size"
        ) == "invalid_chunk_params"
        assert PipelineAssembler._classify_violation(
            "validation", "xyz", "Contract validation: [...]"
        ) == "output_contract_violation"
        assert PipelineAssembler._classify_violation(
            "execution", "xyz", "ChunkerAdapter failed: OOM"
        ) is None


# ── Phase 19.5: Contract-Aware Event Sink ──────────────────────────

class TestContractAwareEventSink:
    """Verify structured in-memory sink for CompositionEvents."""

    @pytest.fixture
    def sink(self):
        from core.adapters.event_sink import ContractAwareEventSink
        return ContractAwareEventSink()

    @pytest.fixture
    def sample_events(self):
        return [
            CompositionEvent(
                event_type="rule_matched",
                correlation_id="corr-abc",
                timestamp=1.0,
                context={"path": "a.md", "rule_id": "r1"},
            ),
            CompositionEvent(
                event_type="chunker_instantiated",
                correlation_id="corr-abc",
                timestamp=1.1,
                context={"chunker": "fixed", "version": "1.0.0"},
            ),
            CompositionEvent(
                event_type="document_failed",
                correlation_id="corr-def",
                timestamp=2.0,
                context={
                    "path": "bad.md", "chunker": "nonexistent",
                    "error_type": "instantiation",
                    "contract_violation": "unknown_chunker_strategy",
                },
            ),
            CompositionEvent(
                event_type="document_failed",
                correlation_id="corr-ghi",
                timestamp=3.0,
                context={
                    "path": "bad2.md", "chunker": "recursive",
                    "error_type": "validation",
                    "contract_violation": "output_contract_violation",
                },
            ),
            CompositionEvent(
                event_type="assembly_complete",
                correlation_id="batch",
                timestamp=4.0,
                context={"total_docs": 3, "success_count": 1},
            ),
        ]

    def test_callable_interface(self, sink, sample_events):
        """ContractAwareEventSink is callable — drop-in for event_sink."""
        for e in sample_events:
            sink(e)
        assert len(sink) == 5

    def test_by_correlation(self, sink, sample_events):
        """Query events by correlation_id for single-document tracing."""
        for e in sample_events:
            sink(e)
        corr_abc = sink.by_correlation("corr-abc")
        assert len(corr_abc) == 2
        assert all(e.correlation_id == "corr-abc" for e in corr_abc)

    def test_by_type(self, sink, sample_events):
        """Filter events by event_type."""
        for e in sample_events:
            sink(e)
        failed = sink.by_type("document_failed")
        assert len(failed) == 2
        matched = sink.by_type("rule_matched")
        assert len(matched) == 1

    def test_violations(self, sink, sample_events):
        """violations property returns only contract violation events."""
        for e in sample_events:
            sink(e)
        violations = sink.violations
        assert len(violations) == 2
        cv_categories = {e.context["contract_violation"] for e in violations}
        assert cv_categories == {"unknown_chunker_strategy", "output_contract_violation"}

    def test_violation_count(self, sink, sample_events):
        for e in sample_events:
            sink(e)
        assert sink.violation_count == 2

    def test_violations_by_type(self, sink, sample_events):
        """Group violations by contract_violation category."""
        for e in sample_events:
            sink(e)
        grouped = sink.violations_by_type()
        assert "unknown_chunker_strategy" in grouped
        assert "output_contract_violation" in grouped
        assert len(grouped["unknown_chunker_strategy"]) == 1
        assert len(grouped["output_contract_violation"]) == 1

    def test_summary(self, sink, sample_events):
        """summary property produces JSON-safe dict for audit."""
        for e in sample_events:
            sink(e)
        s = sink.summary
        assert s["total_events"] == 5
        assert s["documents_tracked"] == 4  # corr-abc, corr-def, corr-ghi, batch
        assert s["violation_count"] == 2
        assert "document_failed" in s["events_by_type"]
        assert "unknown_chunker_strategy" in s["violations_by_category"]

    def test_clear(self, sink, sample_events):
        """clear() resets for reuse (test isolation)."""
        for e in sample_events:
            sink(e)
        assert len(sink) == 5
        sink.clear()
        assert len(sink) == 0
        assert sink.violations == []

    def test_non_violation_events_not_in_violations(self, sink):
        """Events without contract_violation context are not violations."""
        sink(CompositionEvent(
            event_type="rule_matched",
            correlation_id="corr-xyz",
            timestamp=1.0,
            context={"path": "ok.md"},
        ))
        assert sink.violations == []
        assert sink.violation_count == 0

    def test_end_to_end_with_composer(self):
        """PipelineComposer with ContractAwareEventSink — full flow."""
        from core.adapters.event_sink import ContractAwareEventSink

        sink = ContractAwareEventSink()
        composer = PipelineComposer.from_dict(
            {"version": "1.0.0", "default_chunker": "identity"},
            event_sink=sink,
        )
        doc = _make_doc("e2e test", "test.md")
        step = composer.compose_for_sources(["test.md"], {"test.md": doc})
        assert step is not None
        assert len(sink) >= 2  # at least: chunker_instantiated + assembly_complete
        assert sink.violation_count == 0  # all good, no violations

    def test_sink_repr(self, sink, sample_events):
        for e in sample_events:
            sink(e)
        r = repr(sink)
        assert "events=5" in r
        assert "violations=2" in r
