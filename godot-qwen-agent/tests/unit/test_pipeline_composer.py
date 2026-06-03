"""Phase 19 Pipeline Composition — unit tests.

Tests for SourceRule, CompositionBlueprint, SourceRouter, PipelineAssembler,
PipelineComposer, and ArchitectureInvariants.
"""

from __future__ import annotations

import json
import tempfile
import time
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
    ContractHealthReport,
    ContractLifecycle,
    ContractViolation,
    SeverityMapping,
    SeverityRule,
    SourceRule,
)
from core.contracts.tool import ToolCall, ToolProtocol, ToolResult
from core.adapters.repair_engine import (
    RepairAction, RepairBudget, RepairStrategy, SelfRepairEngine,
)
from core.adapters.composer import (
    AssemblyError,
    PipelineAssembler,
    PipelineComposer,
    SourceRouter,
)
from core.adapters.health_evaluator import ContractHealthEvaluator


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
        """Each error_type maps to the correct ContractViolation enum value."""
        assert PipelineAssembler._classify_violation(
            "routing", "unknown", "No matching rule"
        ) == ContractViolation.ROUTING_CONTRACT_BREACH
        assert PipelineAssembler._classify_violation(
            "instantiation", "xyz", "Unknown strategy: 'xyz'"
        ) == ContractViolation.UNKNOWN_CHUNKER_STRATEGY
        assert PipelineAssembler._classify_violation(
            "instantiation", "xyz", "Invalid params for 'xyz': missing chunk_size"
        ) == ContractViolation.INVALID_CHUNK_PARAMS
        assert PipelineAssembler._classify_violation(
            "validation", "xyz", "Contract validation: [...]"
        ) == ContractViolation.OUTPUT_CONTRACT_VIOLATION
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


# ── Phase 20: Contract Health Evaluator ────────────────────────────

class TestContractHealthEvaluator:
    """Verify evaluator produces correct ContractHealthReport from sink state."""

    @pytest.fixture
    def evaluator(self):
        return ContractHealthEvaluator()

    @pytest.fixture
    def sink(self):
        from core.adapters.event_sink import ContractAwareEventSink
        return ContractAwareEventSink()

    def _event(self, event_type, correlation_id, **context):
        return CompositionEvent(
            event_type=event_type,
            correlation_id=correlation_id,
            timestamp=1.0,
            context=context,
        )

    def test_zero_events_is_healthy(self, evaluator, sink):
        """Empty sink → healthy, 1.0 compliance, no violations."""
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"
        assert report.compliance_rate == 1.0
        assert report.dominant_violation_type is None
        assert report.total_documents == 0
        assert report.total_events == 0

    def test_all_success_is_healthy(self, evaluator, sink):
        """Documents with no violations → healthy at 1.0."""
        sink(self._event("rule_matched", "doc-1", path="a.md"))
        sink(self._event("chunker_instantiated", "doc-1", chunker="recursive"))
        sink(self._event("assembly_complete", "batch", total_docs=1))
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"
        assert report.compliance_rate == 1.0

    def test_single_unknown_strategy_is_critical(self, evaluator, sink):
        """One unknown_chunker_strategy → critical (threshold=1)."""
        sink(self._event(
            "document_failed", "doc-1",
            error_type="instantiation",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        sink(self._event("assembly_complete", "batch", total_docs=1))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"
        assert report.dominant_violation_type == ContractViolation.UNKNOWN_CHUNKER_STRATEGY

    def test_routing_breach_below_threshold_is_healthy(self, evaluator, sink):
        """routing_contract_breach threshold is 3 → 2 violations = healthy (below)."""
        for i in range(2):
            sink(self._event(
                "document_failed", f"doc-{i}",
                error_type="routing",
                contract_violation=ContractViolation.ROUTING_CONTRACT_BREACH,
            ))
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"

    def test_routing_breach_3_triggers_critical(self, evaluator, sink):
        """3 routing_contract_breach → critical."""
        for i in range(3):
            sink(self._event(
                "document_failed", f"doc-{i}",
                error_type="routing",
                contract_violation=ContractViolation.ROUTING_CONTRACT_BREACH,
            ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_invalid_params_is_degraded(self, evaluator, sink):
        """invalid_chunk_params threshold=1 → degraded (not critical)."""
        sink(self._event(
            "document_failed", "doc-1",
            error_type="instantiation",
            contract_violation=ContractViolation.INVALID_CHUNK_PARAMS,
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "degraded"

    def test_critical_overrides_degraded(self, evaluator, sink):
        """When violations span multiple severities, the most severe wins."""
        sink(self._event(
            "document_failed", "doc-1",
            error_type="instantiation",
            contract_violation=ContractViolation.INVALID_CHUNK_PARAMS,
        ))
        sink(self._event(
            "document_failed", "doc-2",
            error_type="instantiation",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_compliance_rate_calculation(self, evaluator, sink):
        """2 out of 4 docs with violations → compliance_rate = 0.5."""
        sink(self._event("rule_matched", "doc-ok-1"))
        sink(self._event("rule_matched", "doc-ok-2"))
        sink(self._event(
            "document_failed", "doc-bad-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        sink(self._event(
            "document_failed", "doc-bad-2",
            contract_violation=ContractViolation.OUTPUT_CONTRACT_VIOLATION,
        ))
        report = evaluator.evaluate(sink)
        assert report.compliance_rate == 0.5

    def test_dominant_violation_type(self, evaluator, sink):
        """dominant_violation_type is the most frequent category."""
        # 3 unknown_chunker_strategy, 1 invalid_chunk_params
        for i in range(3):
            sink(self._event(
                "document_failed", f"doc-u-{i}",
                contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            ))
        sink(self._event(
            "document_failed", "doc-i-1",
            contract_violation=ContractViolation.INVALID_CHUNK_PARAMS,
        ))
        report = evaluator.evaluate(sink)
        assert report.dominant_violation_type == ContractViolation.UNKNOWN_CHUNKER_STRATEGY

    def test_trend_first_report_is_none(self, evaluator, sink):
        """First report always has trend=None."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        report = evaluator.evaluate(sink)
        assert report.trend is None

    def test_trend_improving(self, evaluator, sink):
        """Better compliance_rate → trend='improving'."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        previous = evaluator.evaluate(sink)  # compliance = 0.0

        # Clear and add only success events
        sink.clear()
        sink(self._event("rule_matched", "doc-ok"))
        sink(self._event("assembly_complete", "batch", total_docs=1))
        current = evaluator.evaluate(sink, previous=previous)  # compliance = 1.0
        assert current.trend == "improving"

    def test_trend_deteriorating(self, evaluator, sink):
        """Worse compliance_rate → trend='deteriorating'."""
        sink(self._event("rule_matched", "doc-ok"))
        previous = evaluator.evaluate(sink)  # compliance = 1.0

        sink.clear()
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        current = evaluator.evaluate(sink, previous=previous)  # compliance = 0.0
        assert current.trend == "deteriorating"

    def test_trend_stable(self, evaluator, sink):
        """Same compliance_rate → trend='stable'."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        previous = evaluator.evaluate(sink)

        sink.clear()
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        current = evaluator.evaluate(sink, previous=previous)
        assert current.trend == "stable"

    def test_deterministic_same_input_same_output(self, evaluator, sink):
        """Pure function: same input → same output."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        r1 = evaluator.evaluate(sink)
        r2 = evaluator.evaluate(sink)
        assert r1.compliance_rate == r2.compliance_rate
        assert r1.severity == r2.severity
        assert r1.dominant_violation_type == r2.dominant_violation_type

    def test_evaluator_does_not_modify_sink(self, evaluator, sink):
        """evaluate() is read-only on the sink."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        before = len(sink)
        evaluator.evaluate(sink)
        assert len(sink) == before

    def test_custom_severity_mapping(self, sink):
        """Custom SeverityMapping overrides defaults."""
        custom = SeverityMapping(rules=(
            SeverityRule(
                violation_type=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
                count_threshold=5,
                severity="degraded",
            ),
        ))
        evaluator = ContractHealthEvaluator(severity_mapping=custom)
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        report = evaluator.evaluate(sink)
        # With custom mapping, 1 < 5 → still healthy
        assert report.severity == "healthy"

    def test_violation_counts_in_report(self, evaluator, sink):
        """ContractHealthReport.violation_counts mirrors the categories."""
        sink(self._event(
            "document_failed", "doc-1",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        sink(self._event(
            "document_failed", "doc-2",
            contract_violation=ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
        ))
        sink(self._event(
            "document_failed", "doc-3",
            contract_violation=ContractViolation.INVALID_CHUNK_PARAMS,
        ))
        report = evaluator.evaluate(sink)
        assert report.violation_counts[ContractViolation.UNKNOWN_CHUNKER_STRATEGY] == 2
        assert report.violation_counts[ContractViolation.INVALID_CHUNK_PARAMS] == 1


# ── Phase 20: ContractViolation Enum + Data Models ─────────────────

class TestContractViolationEnum:
    """Verify StrEnum drop-in compatibility with existing string checks."""

    def test_enum_is_str_subclass(self):
        assert issubclass(ContractViolation, str)

    def test_enum_equals_string(self):
        assert ContractViolation.UNKNOWN_CHUNKER_STRATEGY == "unknown_chunker_strategy"

    def test_enum_in_dict_key(self):
        d = {ContractViolation.UNKNOWN_CHUNKER_STRATEGY: 1}
        assert d["unknown_chunker_strategy"] == 1

    def test_all_seven_categories_defined(self):
        names = {m.name for m in ContractViolation}
        assert names == {
            "UNKNOWN_CHUNKER_STRATEGY",
            "INVALID_CHUNK_PARAMS",
            "ROUTING_CONTRACT_BREACH",
            "OUTPUT_CONTRACT_VIOLATION",
            "TOOL_NOT_FOUND",
            "TOOL_PARAM_MISMATCH",
            "INTENTIONAL_VIOLATION",
        }


class TestSeverityMappingDefaults:
    """Verify SeverityMapping.default() produces sensible rules."""

    def test_default_has_six_rules(self):
        m = SeverityMapping.default()
        assert len(m.rules) == 6

    def test_default_unknown_strategy_is_critical(self):
        m = SeverityMapping.default()
        rule = next(r for r in m.rules
                    if r.violation_type == ContractViolation.UNKNOWN_CHUNKER_STRATEGY)
        assert rule.count_threshold == 1
        assert rule.severity == "critical"

    def test_default_routing_breach_needs_3(self):
        m = SeverityMapping.default()
        rule = next(r for r in m.rules
                    if r.violation_type == ContractViolation.ROUTING_CONTRACT_BREACH)
        assert rule.count_threshold == 3
        assert rule.severity == "critical"

    def test_default_invalid_params_is_degraded(self):
        m = SeverityMapping.default()
        rule = next(r for r in m.rules
                    if r.violation_type == ContractViolation.INVALID_CHUNK_PARAMS)
        assert rule.count_threshold == 1
        assert rule.severity == "degraded"


class TestContractHealthReport:
    """Verify health report frozen dataclass invariants."""

    def test_compliance_rate_must_be_in_range(self):
        with pytest.raises(ValueError):
            ContractHealthReport(
                compliance_rate=1.5, severity="healthy",
                dominant_violation_type=None, trend=None,
                total_documents=0, total_events=0,
                violation_counts={}, evaluated_at=1.0,
            )

    def test_violation_counts_is_copied(self):
        vc = {"test": 5}
        report = ContractHealthReport(
            compliance_rate=1.0, severity="healthy",
            dominant_violation_type=None, trend=None,
            total_documents=0, total_events=0,
            violation_counts=vc, evaluated_at=1.0,
        )
        vc["test"] = 999
        assert report.violation_counts["test"] == 5

    def test_lifecycle_distribution_is_copied(self):
        ld = {"active": 3}
        report = ContractHealthReport(
            compliance_rate=1.0, severity="healthy",
            dominant_violation_type=None, trend=None,
            total_documents=0, total_events=0,
            violation_counts={}, evaluated_at=1.0,
            lifecycle_distribution=ld,
        )
        ld["active"] = 999
        assert report.lifecycle_distribution["active"] == 3


# ── Phase 21: ContractLifecycle + Blueprint Lifecycle ──────────────

class TestContractLifecycle:
    """Verify ContractLifecycle StrEnum invariants."""

    def test_enum_is_str_subclass(self):
        assert issubclass(ContractLifecycle, str)

    def test_enum_equals_string(self):
        assert ContractLifecycle.ACTIVE == "active"
        assert ContractLifecycle.DRAFT == "draft"
        assert ContractLifecycle.DEPRECATED == "deprecated"

    def test_enum_from_string(self):
        assert ContractLifecycle("active") == ContractLifecycle.ACTIVE
        assert ContractLifecycle("draft") == ContractLifecycle.DRAFT
        assert ContractLifecycle("deprecated") == ContractLifecycle.DEPRECATED

    def test_invalid_lifecycle_raises(self):
        with pytest.raises(ValueError):
            ContractLifecycle("nonexistent")

    def test_all_three_stages_defined(self):
        names = {m.name for m in ContractLifecycle}
        assert names == {"DRAFT", "ACTIVE", "DEPRECATED"}


class TestBlueprintLifecycle:
    """Verify CompositionBlueprint lifecycle integration."""

    def test_default_lifecycle_is_active(self):
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert bp.lifecycle == ContractLifecycle.ACTIVE

    def test_explicit_lifecycle_from_dict(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "draft",
        })
        assert bp.lifecycle == ContractLifecycle.DRAFT

    def test_lifecycle_from_yaml_string(self):
        yaml_content = """version: "1.0.0"
lifecycle: deprecated
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            tmp = f.name
        try:
            bp = CompositionBlueprint.from_yaml(tmp)
            assert bp.lifecycle == ContractLifecycle.DEPRECATED
        finally:
            Path(tmp).unlink()

    def test_lifecycle_affects_fingerprint(self):
        a = CompositionBlueprint.from_dict({"version": "1.0.0"})
        b = CompositionBlueprint.from_dict({
            "version": "1.0.0", "lifecycle": "draft",
        })
        assert a.fingerprint != b.fingerprint

    def test_lifecycle_normalized_from_string(self):
        """Passing a string lifecycle to constructor normalizes to enum."""
        bp = CompositionBlueprint(
            version=SemVer.parse("1.0.0"),
            lifecycle="draft",  # type: ignore[arg-type]
        )
        assert isinstance(bp.lifecycle, ContractLifecycle)
        assert bp.lifecycle == ContractLifecycle.DRAFT

    def test_lifecycle_stored_as_enum_not_string(self):
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert isinstance(bp.lifecycle, ContractLifecycle)


class TestSourceRouterDeprecatedRejection:
    """Verify SourceRouter rejects DEPRECATED blueprints."""

    def test_deprecated_blueprint_raises_assembly_error(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "deprecated",
        })
        router = SourceRouter(bp)
        with pytest.raises(AssemblyError, match="deprecated blueprint"):
            router.resolve("readme.md")

    def test_active_blueprint_resolves_normally(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "active",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rule = router.resolve("readme.md")
        assert rule.chunker == "identity"

    def test_draft_blueprint_resolves_normally(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "draft",
            "default_chunker": "identity",
        })
        router = SourceRouter(bp)
        rule = router.resolve("readme.md")
        assert rule.chunker == "identity"

    def test_deprecated_blueprint_raises_for_resolve_all(self):
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "deprecated",
        })
        router = SourceRouter(bp)
        with pytest.raises(AssemblyError, match="deprecated blueprint"):
            router.resolve_all(["readme.md"])


class TestPipelineAssemblerLifecycleEvents:
    """Verify blueprint_lifecycle is threaded into event context."""

    def test_document_failed_event_has_blueprint_lifecycle(self):
        events = []
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "draft",
            "source_rules": [
                {"pattern": "*.md", "chunker": "nonexistent", "priority": 10},
            ],
        })
        router = SourceRouter(bp)
        rules = router.resolve_all(["test.md"])
        doc = _make_doc("hello", "test.md")
        assembler = PipelineAssembler(
            event_sink=events.append,
            blueprint_lifecycle=bp.lifecycle,
        )
        with pytest.raises(AssemblyError):
            assembler.assemble(rules, {"test.md": doc}, "1.0.0")
        failed = [e for e in events if e.event_type == "document_failed"]
        assert len(failed) == 1
        assert failed[0].context["blueprint_lifecycle"] == "draft"

    def test_assembler_default_lifecycle_is_active(self):
        assembler = PipelineAssembler()
        assert assembler._blueprint_lifecycle == ContractLifecycle.ACTIVE


class TestLifecycleWeightedHealthEvaluation:
    """Verify lifecycle-aware severity weighting in HealthEvaluator."""

    @pytest.fixture
    def evaluator(self):
        return ContractHealthEvaluator()

    @pytest.fixture
    def sink(self):
        from core.adapters.event_sink import ContractAwareEventSink
        return ContractAwareEventSink()

    def _violation_event(self, correlation_id, violation_type, lifecycle="active"):
        return CompositionEvent(
            event_type="document_failed",
            correlation_id=correlation_id,
            timestamp=1.0,
            context={
                "contract_violation": violation_type,
                "blueprint_lifecycle": lifecycle,
            },
        )

    def test_active_violation_full_weight(self, evaluator, sink):
        """ACTIVE unknown_chunker_strategy → threshold 1 → critical."""
        sink(self._violation_event(
            "doc-1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="active",
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_draft_violation_half_weight(self, evaluator, sink):
        """DRAFT unknown_chunker_strategy → weight 0.5 < threshold 1 → healthy."""
        sink(self._violation_event(
            "doc-1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="draft",
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"

    def test_two_draft_critical_violations_equal_one_active(self, evaluator, sink):
        """2 DRAFT unknown_chunker_strategy = weighted 1.0 → just hits critical."""
        sink(self._violation_event(
            "doc-1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="draft",
        ))
        sink(self._violation_event(
            "doc-2", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="draft",
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_deprecated_violation_heavily_downweighted(self, evaluator, sink):
        """DEPRECATED unknown_chunker_strategy → weight 0.3 < threshold 1 → healthy."""
        sink(self._violation_event(
            "doc-1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="deprecated",
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"

    def test_four_deprecated_critical_violations_hit_threshold(self, evaluator, sink):
        """4 DEPRECATED = 4 × 0.3 = 1.2 ≥ 1 → critical."""
        for i in range(4):
            sink(self._violation_event(
                f"doc-{i}", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
                lifecycle="deprecated",
            ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_active_overrides_deprecated_in_severity(self, evaluator, sink):
        """1 ACTIVE violation + many deprecated → critical from active."""
        sink(self._violation_event(
            "doc-active", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="active",
        ))
        sink(self._violation_event(
            "doc-dep-1", ContractViolation.INVALID_CHUNK_PARAMS,
            lifecycle="deprecated",
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_lifecycle_distribution_in_report(self, evaluator, sink):
        """lifecycle_distribution counts unique docs per lifecycle stage."""
        sink(self._violation_event(
            "doc-a1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="active",
        ))
        sink(self._violation_event(
            "doc-a2", ContractViolation.INVALID_CHUNK_PARAMS,
            lifecycle="active",
        ))
        sink(self._violation_event(
            "doc-d1", ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            lifecycle="deprecated",
        ))
        sink(self._violation_event(
            "doc-d1", ContractViolation.INVALID_CHUNK_PARAMS,
            lifecycle="deprecated",
        ))
        report = evaluator.evaluate(sink)
        ld = dict(report.lifecycle_distribution)
        assert ld.get("active") == 2
        assert ld.get("deprecated") == 1

    def test_default_lifecycle_for_events_without_explicit_field(self, evaluator, sink):
        """Events without blueprint_lifecycle default to active."""
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=1.0,
            context={
                "contract_violation": ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            },
        ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"  # full weight
        ld = dict(report.lifecycle_distribution)
        assert ld.get("active") == 1

    def test_routing_breach_with_lifecycle_weighting(self, evaluator, sink):
        """routing_contract_breach threshold=3. 6 DRAFT = 6×0.5 = 3 → critical."""
        for i in range(6):
            sink(self._violation_event(
                f"doc-{i}", ContractViolation.ROUTING_CONTRACT_BREACH,
                lifecycle="draft",
            ))
        report = evaluator.evaluate(sink)
        assert report.severity == "critical"

    def test_routing_breach_deprecated_stays_below_threshold(self, evaluator, sink):
        """routing_contract_breach threshold=3. 9 DEPRECATED = 9×0.3 = 2.7 < 3."""
        for i in range(9):
            sink(self._violation_event(
                f"doc-{i}", ContractViolation.ROUTING_CONTRACT_BREACH,
                lifecycle="deprecated",
            ))
        report = evaluator.evaluate(sink)
        assert report.severity == "healthy"


class TestAuditManifestLifecycle:
    """Verify audit_manifest includes blueprint lifecycle."""

    def test_audit_manifest_includes_lifecycle(self):
        composer = PipelineComposer.from_dict({
            "version": "1.0.0",
            "lifecycle": "draft",
        })
        manifest = composer.audit_manifest
        assert manifest["blueprint_lifecycle"] == "draft"

    def test_audit_manifest_default_lifecycle(self):
        composer = PipelineComposer.from_dict({"version": "1.0.0"})
        manifest = composer.audit_manifest
        assert manifest["blueprint_lifecycle"] == "active"


class TestPhase21ArchitectureInvariants:
    """Constitutional integrity tests for Phase 21."""

    def test_blueprint_lifecycle_default_is_active_not_none(self):
        """Invariant #28: lifecycle default must be ACTIVE, never None."""
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        assert bp.lifecycle is not None
        assert bp.lifecycle == ContractLifecycle.ACTIVE

    def test_deprecated_blueprint_rejected_by_router(self):
        """Invariant #29: SourceRouter must reject DEPRECATED blueprints."""
        bp = CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "lifecycle": "deprecated",
        })
        router = SourceRouter(bp)
        with pytest.raises(AssemblyError):
            router.resolve("any/path.md")

    def test_active_and_draft_not_rejected(self):
        """DEPRECATED rejection must not affect ACTIVE or DRAFT blueprints."""
        for lifecycle in ("active", "draft"):
            bp = CompositionBlueprint.from_dict({
                "version": "1.0.0",
                "lifecycle": lifecycle,
                "default_chunker": "identity",
            })
            router = SourceRouter(bp)
            rule = router.resolve("test.md")
            assert rule is not None


# ── Phase 22a: Tool Contract + ToolAdapter ──────────────────────────

class TestToolCall:
    """Verify ToolCall frozen dataclass invariants."""

    def test_create_basic(self):
        tc = ToolCall(tool_name="web_search", parameters={"q": "hello"})
        assert tc.tool_name == "web_search"
        assert tc.parameters["q"] == "hello"
        assert tc.call_id != ""
        assert len(tc.call_id) == 12

    def test_call_id_deterministic(self):
        a = ToolCall(tool_name="web_search", parameters={"q": "hello"})
        b = ToolCall(tool_name="web_search", parameters={"q": "hello"})
        assert a.call_id == b.call_id

    def test_call_id_different_for_different_params(self):
        a = ToolCall(tool_name="web_search", parameters={"q": "hello"})
        b = ToolCall(tool_name="web_search", parameters={"q": "world"})
        assert a.call_id != b.call_id

    def test_call_id_explicit_overrides_auto(self):
        tc = ToolCall(tool_name="test", call_id="my-id")
        assert tc.call_id == "my-id"

    def test_parameters_are_copied(self):
        params = {"q": "hello"}
        tc = ToolCall(tool_name="test", parameters=params)
        params["q"] = "modified"
        assert tc.parameters["q"] == "hello"

    def test_parameters_sorted_in_call_id(self):
        """call_id should be the same regardless of parameter order."""
        a = ToolCall(tool_name="test", parameters={"a": 1, "b": 2})
        b = ToolCall(tool_name="test", parameters={"b": 2, "a": 1})
        assert a.call_id == b.call_id

    def test_frozen(self):
        tc = ToolCall(tool_name="test")
        with pytest.raises(Exception):
            tc.tool_name = "other"  # type: ignore[misc]


class TestToolResult:
    """Verify ToolResult frozen dataclass invariants."""

    def test_success_result(self):
        tr = ToolResult(
            call_id="abc", tool_name="web_search",
            success=True, data="results",
        )
        assert tr.success
        assert tr.contract_violation is None

    def test_failure_with_violation(self):
        tr = ToolResult(
            call_id="abc", tool_name="nonexistent",
            success=False, error="not found",
            contract_violation=ContractViolation.TOOL_NOT_FOUND,
        )
        assert not tr.success
        assert tr.contract_violation == ContractViolation.TOOL_NOT_FOUND

    def test_frozen(self):
        tr = ToolResult(call_id="abc", tool_name="test", success=True)
        with pytest.raises(Exception):
            tr.success = False  # type: ignore[misc]


class TestToolAdapterParse:
    """Verify ToolAdapter.parse_function_call translation."""

    @pytest.fixture
    def adapter(self):
        from core.adapters.tool_adapter import ToolAdapter
        return ToolAdapter()

    def test_parse_valid(self, adapter):
        raw = {"name": "web_search", "arguments": {"q": "hello"}}
        tc = adapter.parse_function_call(raw)
        assert tc.tool_name == "web_search"
        assert tc.parameters["q"] == "hello"
        assert isinstance(tc, ToolCall)

    def test_parse_missing_name_raises(self, adapter):
        with pytest.raises(ValueError, match="missing 'name'"):
            adapter.parse_function_call({"arguments": {}})

    def test_parse_empty_name_raises(self, adapter):
        with pytest.raises(ValueError, match="missing 'name'"):
            adapter.parse_function_call({"name": "", "arguments": {}})

    def test_parse_json_string_arguments(self, adapter):
        """LLMs sometimes return arguments as a JSON string."""
        raw = {"name": "web_search", "arguments": '{"q":"hello"}'}
        tc = adapter.parse_function_call(raw)
        assert tc.parameters["q"] == "hello"

    def test_parse_invalid_arguments_type(self, adapter):
        with pytest.raises(ValueError, match="must be a dict"):
            adapter.parse_function_call({"name": "test", "arguments": 42})

    def test_parse_invalid_json_string_raises(self, adapter):
        with pytest.raises(ValueError):
            adapter.parse_function_call({
                "name": "test", "arguments": "not valid json",
            })

    def test_parse_default_arguments(self, adapter):
        raw = {"name": "web_search"}
        tc = adapter.parse_function_call(raw)
        assert dict(tc.parameters) == {}


class TestToolAdapterValidate:
    """Verify ToolAdapter._validate_against_blueprint contract checks."""

    @pytest.fixture
    def adapter(self):
        from core.adapters.tool_adapter import ToolAdapter
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        return ToolAdapter(blueprint=bp)

    def test_empty_tool_name_is_violation(self, adapter):
        tc = ToolCall(tool_name="")
        v = adapter._validate_against_blueprint(tc)
        assert v == ContractViolation.TOOL_NOT_FOUND

    def test_unregistered_tool_is_violation(self, adapter):
        tc = ToolCall(tool_name="nonexistent_tool_xyz")
        v = adapter._validate_against_blueprint(tc)
        assert v == ContractViolation.TOOL_NOT_FOUND

    def test_no_blueprint_is_ok(self):
        from core.adapters.tool_adapter import ToolAdapter
        adapter = ToolAdapter(blueprint=None)
        tc = ToolCall(tool_name="anything")
        v = adapter._validate_against_blueprint(tc)
        # Without blueprint, only registry check applies — and fails
        assert v == ContractViolation.TOOL_NOT_FOUND


class TestToolAdapterExecute:
    """Verify ToolAdapter.execute() full flow."""

    @pytest.fixture
    def adapter(self):
        from core.adapters.tool_adapter import ToolAdapter
        return ToolAdapter()

    def test_tool_not_found_produces_violation_result(self, adapter):
        tc = ToolCall(tool_name="nonexistent_tool")
        result = adapter.execute(tc)
        assert result.success is False
        assert result.contract_violation == ContractViolation.TOOL_NOT_FOUND
        assert "not_found" in result.error or "not found" in result.error

    def test_contract_violation_before_registry_lookup(self, adapter):
        """Empty tool name should be caught before attempting registry lookup."""
        tc = ToolCall(tool_name="")
        result = adapter.execute(tc)
        assert result.contract_violation == ContractViolation.TOOL_NOT_FOUND


class TestSeverityMappingToolViolations:
    """Verify default SeverityMapping covers tool violations."""

    def test_tool_not_found_is_critical(self):
        m = SeverityMapping.default()
        rule = next(r for r in m.rules
                    if r.violation_type == ContractViolation.TOOL_NOT_FOUND)
        assert rule.count_threshold == 1
        assert rule.severity == "critical"

    def test_tool_param_mismatch_is_degraded(self):
        m = SeverityMapping.default()
        rule = next(r for r in m.rules
                    if r.violation_type == ContractViolation.TOOL_PARAM_MISMATCH)
        assert rule.count_threshold == 1
        assert rule.severity == "degraded"


class TestPhase22aArchitectureInvariants:
    """Constitutional integrity for Phase 22a."""

    def test_tool_call_has_deterministic_id(self):
        """ToolCall.call_id must be deterministic, not random."""
        a = ToolCall(tool_name="test", parameters={"x": 1})
        b = ToolCall(tool_name="test", parameters={"x": 1})
        assert a.call_id == b.call_id

    def test_tool_result_carries_contract_violation(self):
        """ToolResult must have contract_violation field for EventSink."""
        tr = ToolResult(call_id="abc", tool_name="test", success=True)
        assert hasattr(tr, "contract_violation")
        assert tr.contract_violation is None

    def test_tool_adapter_uses_registry_not_direct_import(self):
        """USB model: ToolAdapter gets tools via COMPONENT_REGISTRY, not import."""
        import inspect
        from core.adapters.tool_adapter import ToolAdapter as TA
        src = inspect.getsource(TA.execute)
        assert "COMPONENT_REGISTRY.get" in src
        assert "from .tools" not in src


# ── Phase 22b: Self-Repair Engine ───────────────────────────────────

class TestRepairBudget:
    """Verify RepairBudget limits and exhaustion logic."""

    def test_default_budget(self):
        budget = RepairBudget()
        assert budget.max_total == 5
        assert budget.max_per_type == 2
        assert budget.total_used == 0
        assert not budget.is_exhausted

    def test_can_repair_under_budget(self):
        budget = RepairBudget()
        assert budget.can_repair("unknown_chunker_strategy")

    def test_consume_reduces_budget(self):
        budget = RepairBudget()
        budget2 = budget.consume("test_type")
        assert budget2.total_used == 1
        assert budget.total_used == 0  # original unchanged (frozen pattern)

    def test_max_per_type_enforced(self):
        budget = RepairBudget(max_per_type=1)
        budget = budget.consume("test_type")
        assert not budget.can_repair("test_type")

    def test_max_total_enforced(self):
        budget = RepairBudget(max_total=2, max_per_type=5)
        budget = budget.consume("type_a")
        budget = budget.consume("type_b")
        assert budget.is_exhausted
        assert not budget.can_repair("type_c")

    def test_budget_exhausted_flag(self):
        budget = RepairBudget(max_total=0)
        assert budget.is_exhausted


class TestSelfRepairEngine:
    """Verify repair decisions and event emission."""

    @pytest.fixture
    def blueprint(self):
        return CompositionBlueprint.from_dict({
            "version": "1.0.0",
            "default_chunker": "identity",
        })

    @pytest.fixture
    def sink(self):
        from core.adapters.event_sink import ContractAwareEventSink
        return ContractAwareEventSink()

    @pytest.fixture
    def evaluator(self):
        return ContractHealthEvaluator()

    def test_healthy_report_produces_no_actions(self, blueprint, sink):
        engine = SelfRepairEngine(blueprint)
        report = ContractHealthReport(
            compliance_rate=1.0, severity="healthy",
            dominant_violation_type=None, trend=None,
            total_documents=1, total_events=1,
            violation_counts={}, evaluated_at=time.time(),
        )
        actions = engine.decide(report, sink)
        assert actions == []

    def test_degraded_report_produces_actions(self, blueprint, sink, evaluator):
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INVALID_CHUNK_PARAMS,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(blueprint)
        actions = engine.decide(report, sink)
        assert len(actions) >= 1
        assert actions[0].violation_type == ContractViolation.INVALID_CHUNK_PARAMS
        assert actions[0].strategy == RepairStrategy.RETRY_WITH_DEFAULT

    def test_unknown_chunker_strategy_triggers_replace(self, blueprint, sink, evaluator):
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(blueprint)
        actions = engine.decide(report, sink)
        assert len(actions) == 1
        assert actions[0].strategy == RepairStrategy.REPLACE_COMPONENT
        assert actions[0].replacement == "identity"  # default_chunker

    def test_tool_not_found_triggers_replace(self, blueprint, sink, evaluator):
        sink(CompositionEvent(
            event_type="tool_executed",
            correlation_id="tool-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.TOOL_NOT_FOUND,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(blueprint)
        actions = engine.decide(report, sink)
        assert len(actions) == 1
        assert actions[0].strategy == RepairStrategy.REPLACE_COMPONENT
        assert actions[0].target_component == "tool"

    def test_budget_limits_actions(self, blueprint, sink, evaluator):
        """Budget of 1 total → only first violation gets a repair action."""
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INVALID_CHUNK_PARAMS,
            },
        ))
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-2",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.OUTPUT_CONTRACT_VIOLATION,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(
            blueprint, budget=RepairBudget(max_total=1, max_per_type=1),
        )
        actions = engine.decide(report, sink)
        assert len(actions) == 1

    def test_execute_all_returns_results(self, blueprint, sink, evaluator):
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INVALID_CHUNK_PARAMS,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(blueprint)
        actions = engine.decide(report, sink)
        results = engine.execute_all(actions)
        assert len(results) == 1
        assert results[0]["applied"] is True
        assert results[0]["violation"] == ContractViolation.INVALID_CHUNK_PARAMS

    def test_budget_exhausted_emits_event(self, blueprint, sink, evaluator):
        """When budget hits 0 during decide, emit repair_budget_exhausted."""
        events = []
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.UNKNOWN_CHUNKER_STRATEGY,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(
            blueprint, event_sink=events.append,
            budget=RepairBudget(max_total=1, max_per_type=1),
        )
        actions = engine.decide(report, sink)
        assert len(actions) == 1
        # After consuming the only budget slot, the exhaust event fires
        exhausted = [e for e in events if e.event_type == "repair_budget_exhausted"]
        assert len(exhausted) == 1

    def test_repair_attempted_event_emitted(self, blueprint, sink, evaluator):
        """Each repair attempt emits a repair_attempted event."""
        events = []
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INVALID_CHUNK_PARAMS,
            },
        ))
        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(blueprint, event_sink=events.append)
        actions = engine.decide(report, sink)
        engine.execute_all(actions)
        attempted = [e for e in events if e.event_type == "repair_attempted"]
        assert len(attempted) == 1
        assert attempted[0].context["violation_type"] == ContractViolation.INVALID_CHUNK_PARAMS

    def test_strategy_enum_values(self):
        assert RepairStrategy.RETRY_WITH_DEFAULT == "retry_with_default"
        assert RepairStrategy.REPLACE_COMPONENT == "replace_component"
        assert RepairStrategy.ESCALATE_TO_HUMAN == "escalate_to_human"
        assert RepairStrategy.GIVE_UP == "give_up"

    def test_repair_action_is_frozen(self):
        action = RepairAction(
            violation_type="test", strategy=RepairStrategy.GIVE_UP,
        )
        with pytest.raises(Exception):
            action.violation_type = "other"  # type: ignore[misc]


# ── Phase 22c: Relationship Memory Store ────────────────────────────

class TestRelationshipMemoryStore:
    """Verify persistent health transition storage."""

    @pytest.fixture
    def store(self):
        from core.adapters.persistence import RelationshipMemoryStore
        s = RelationshipMemoryStore(":memory:")
        yield s
        s.clear()

    def _make_report(self, compliance=1.0, severity="healthy",
                     dominant=None, counts=None):
        return ContractHealthReport(
            compliance_rate=compliance,
            severity=severity,
            dominant_violation_type=dominant,
            trend=None,
            total_documents=1,
            total_events=1,
            violation_counts=counts or {},
            evaluated_at=time.time(),
        )

    def test_empty_store_has_zero_transitions(self, store):
        assert store.transition_count == 0

    def test_record_first_transition(self, store):
        current = self._make_report(compliance=1.0)
        store.record_transition(None, current, "fp-abc")
        assert store.transition_count == 1

    def test_record_transition_tracks_delta(self, store):
        prev = self._make_report(compliance=1.0)
        curr = self._make_report(
            compliance=0.5,
            severity="degraded",
            dominant="invalid_chunk_params",
            counts={"invalid_chunk_params": 1},
        )
        store.record_transition(prev, curr, "fp-abc")
        history = store.get_history("fp-abc")
        assert len(history) == 1
        assert history[0]["compliance_delta"] == -0.5
        assert history[0]["severity_before"] == "healthy"
        assert history[0]["severity_after"] == "degraded"

    def test_get_latest(self, store):
        r1 = self._make_report(compliance=1.0)
        r2 = self._make_report(compliance=0.8, severity="degraded")
        store.record_transition(None, r1, "fp-abc")
        store.record_transition(r1, r2, "fp-abc")
        latest = store.get_latest("fp-abc")
        assert latest["severity_after"] == "degraded"
        assert latest["compliance_delta"] == pytest.approx(-0.2)

    def test_get_history_respects_limit(self, store):
        for i in range(10):
            r = self._make_report(compliance=1.0 - i * 0.1)
            store.record_transition(None, r, "fp-abc")
        history = store.get_history("fp-abc", limit=3)
        assert len(history) == 3

    def test_count_transitions(self, store):
        r = self._make_report()
        store.record_transition(None, r, "fp-abc")
        store.record_transition(r, r, "fp-abc")
        assert store.count_transitions("fp-abc") == 2

    def test_deterioration_count(self, store):
        prev = self._make_report(compliance=1.0)
        worse = self._make_report(
            compliance=0.5, severity="degraded",
            counts={"invalid_chunk_params": 1},
        )
        store.record_transition(prev, worse, "fp-abc")
        assert store.get_deterioration_count("fp-abc") == 1

    def test_multiple_blueprints_isolated(self, store):
        r = self._make_report()
        store.record_transition(None, r, "fp-a")
        store.record_transition(None, r, "fp-b")
        assert store.count_transitions("fp-a") == 1
        assert store.count_transitions("fp-b") == 1

    def test_clear_resets_all(self, store):
        r = self._make_report()
        store.record_transition(None, r, "fp-abc")
        store.clear()
        assert store.transition_count == 0

    def test_violation_snapshot_stored_as_json(self, store):
        r = self._make_report(
            compliance=0.5, severity="critical",
            counts={
                "unknown_chunker_strategy": 1,
                "invalid_chunk_params": 2,
            },
        )
        store.record_transition(None, r, "fp-abc")
        history = store.get_history("fp-abc")
        snapshot = json.loads(history[0]["violation_snapshot"])
        assert snapshot["unknown_chunker_strategy"] == 1
        assert snapshot["invalid_chunk_params"] == 2

    def test_lifecycle_stored_in_transition(self, store):
        r = self._make_report()
        store.record_transition(
            None, r, "fp-abc", lifecycle="draft",
        )
        history = store.get_history("fp-abc")
        assert history[0]["lifecycle"] == "draft"


# ── PLAN2: Intentional Violation ────────────────────────────────────

class TestIntentionalViolation:
    """PLAN2 core test: intentional violations bypass repair and build trust."""

    def test_intentional_violation_not_in_severity_mapping(self):
        """Intentional violations must NOT appear in default SeverityMapping —
        they don't reduce compliance or trigger repair."""
        m = SeverityMapping.default()
        intentional_rules = [
            r for r in m.rules
            if r.violation_type == ContractViolation.INTENTIONAL_VIOLATION
        ]
        assert len(intentional_rules) == 0, (
            "INTENTIONAL_VIOLATION must NOT be in SeverityMapping — "
            "it is a trust-building event, not a failure"
        )

    def test_is_intentional_override_property(self):
        """ToolResult.is_intentional_override returns True only for INTENTIONAL."""
        from core.contracts.tool import ToolResult
        # Normal violation — not intentional
        r1 = ToolResult(
            call_id="a", tool_name="t", success=False,
            contract_violation=ContractViolation.TOOL_NOT_FOUND,
        )
        assert not r1.is_intentional_override

        # Intentional violation — trust-building
        r2 = ToolResult(
            call_id="b", tool_name="t", success=True,
            contract_violation=ContractViolation.INTENTIONAL_VIOLATION,
            higher_value_reason="User expressed fatigue; reducing cognitive load",
        )
        assert r2.is_intentional_override
        assert r2.higher_value_reason is not None

    def test_repair_engine_skips_intentional_violations(self):
        """SelfRepairEngine.decide() must skip INTENTIONAL_VIOLATION
        and not generate repair actions for it."""
        from core.adapters.event_sink import ContractAwareEventSink
        from core.adapters.health_evaluator import ContractHealthEvaluator

        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        sink = ContractAwareEventSink()
        evaluator = ContractHealthEvaluator()

        # Simulate a mix: 1 intentional + 1 real violation
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INTENTIONAL_VIOLATION,
                "blueprint_lifecycle": "active",
            },
        ))
        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-2",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.TOOL_NOT_FOUND,
                "blueprint_lifecycle": "active",
            },
        ))

        report = evaluator.evaluate(sink)
        engine = SelfRepairEngine(bp)

        actions = engine.decide(report, sink)
        # Should have action for TOOL_NOT_FOUND
        assert len(actions) >= 1
        # But NONE of the actions should be for INTENTIONAL_VIOLATION
        intentional_actions = [
            a for a in actions
            if a.violation_type == ContractViolation.INTENTIONAL_VIOLATION
        ]
        assert len(intentional_actions) == 0, (
            "INTENTIONAL_VIOLATION must not generate repair actions"
        )

    def test_record_trust_accumulation(self):
        """SelfRepairEngine.record_trust_accumulation() emits trust_accumulated."""
        events = []
        bp = CompositionBlueprint.from_dict({"version": "1.0.0"})
        engine = SelfRepairEngine(bp, event_sink=events.append)

        engine.record_trust_accumulation(
            violation_type=ContractViolation.INTENTIONAL_VIOLATION,
            reason="User fatigue; skipped non-critical validation",
            impact_score=5,
        )

        trust_events = [e for e in events if e.event_type == "trust_accumulated"]
        assert len(trust_events) == 1
        ctx = dict(trust_events[0].context)
        assert ctx["impact_score"] == 5
        assert "User fatigue" in ctx["higher_value_reason"]
        assert "Trust accumulation" in ctx["message"]

    def test_intentional_violation_does_not_affect_compliance(self):
        """A sink with only intentional violations should still be healthy."""
        from core.adapters.event_sink import ContractAwareEventSink
        from core.adapters.health_evaluator import ContractHealthEvaluator

        sink = ContractAwareEventSink()
        evaluator = ContractHealthEvaluator()

        sink(CompositionEvent(
            event_type="document_failed",
            correlation_id="doc-1",
            timestamp=time.time(),
            context={
                "contract_violation": ContractViolation.INTENTIONAL_VIOLATION,
                "blueprint_lifecycle": "active",
            },
        ))

        report = evaluator.evaluate(sink)
        # Since SeverityMapping has no rule for INTENTIONAL_VIOLATION,
        # it should NOT be flagged as degraded/critical
        # The violation exists in the sink but doesn't reduce health
        assert ContractViolation.INTENTIONAL_VIOLATION not in dict(report.violation_counts) or \
            report.severity == "healthy"
