"""Contract conformance tests: data model invariants, registry validation, SemVer.

Verification scenarios: 3, 4, 5
"""

from __future__ import annotations

import pytest

from core.contracts import (
    COMPONENT_REGISTRY,
    Chunk,
    ContentBlock,
    IdentityChunker,
    SemVer,
    ValidationError,
    register_component,
    validate_pipeline_steps,
)
from core.pipeline import PipelineStartupError


class TestSemVer:
    def test_strict_three_part_required(self):
        v = SemVer.parse("1.0.0")
        assert str(v) == "1.0.0"
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0

    def test_rejects_loose_versions(self):
        for bad in ("1", "1.0", "v1.0.0", "1.0.0.0"):
            with pytest.raises(ValueError, match="Invalid SemVer"):
                SemVer.parse(bad)

    def test_pre_release_and_build(self):
        v = SemVer.parse("2.1.3-alpha.1+build123")
        assert v.prerelease == "alpha.1"
        assert v.build == "build123"
        assert str(v) == "2.1.3-alpha.1+build123"

    def test_comparison(self):
        assert SemVer(1, 0, 0) < SemVer(2, 0, 0)
        assert SemVer(1, 1, 0) >= SemVer(1, 0, 0)
        assert SemVer(1, 0, 5) >= SemVer(1, 0, 3)

    def test_frozen(self):
        v = SemVer(1, 0, 0)
        with pytest.raises(Exception):
            v.major = 2


class TestContentBlockImmutability:
    """Scenario 5: ContentBlock deepcopy defence."""

    def test_metadata_deepcopy_protection(self):
        orig = {"key": "val", "nested": [1, 2, 3]}
        block = ContentBlock.from_dict("text", "source", orig)
        orig["key"] = "MUTATED"
        orig["nested"].append(999)
        assert block.metadata["key"] == "val"
        assert block.metadata["nested"] == [1, 2, 3]

    def test_metadata_is_readonly(self):
        block = ContentBlock(text="hi", source="s", metadata={"a": 1})
        with pytest.raises(TypeError):
            block.metadata["a"] = 2  # type: ignore[index]

    def test_frozen_dataclass(self):
        block = ContentBlock(text="hi", source="s")
        with pytest.raises(Exception):
            block.text = "bye"  # type: ignore[misc]


class TestChunkImmutability:
    """Scenario 4: Chunk immutability."""

    def test_frozen_dataclass_prevents_assignment(self):
        c = Chunk(text="hello", source_strategy="test", span=(0, 5))
        with pytest.raises(Exception):
            c.text = "world"  # type: ignore[misc]

    def test_metadata_write_protected(self):
        c = Chunk(text="hello", source_strategy="test", span=(0, 5))
        with pytest.raises(TypeError):
            c.metadata["k"] = "v"  # type: ignore[index]

    def test_with_metadata_creates_new_instance(self):
        c1 = Chunk(text="hello", source_strategy="test", span=(0, 5))
        c2 = c1.with_metadata(lang="en")
        assert c2.metadata["lang"] == "en"
        assert "lang" not in c1.metadata
        assert c1 is not c2

    def test_mappingproxy_coercion_in_post_init(self):
        c = Chunk(text="hi", metadata={"a": 1}, source_strategy="x", span=(0, 2))
        with pytest.raises(TypeError):
            c.metadata["a"] = 2  # type: ignore[index]


class TestRegistry:
    def test_identity_chunker_is_registered(self):
        strategies = COMPONENT_REGISTRY.list_strategies("chunker")
        assert "identity" in strategies

    def test_get_returns_class(self):
        cls = COMPONENT_REGISTRY.get("chunker", "identity")
        assert cls is IdentityChunker

    def test_register_rejects_missing_version(self):
        with pytest.raises(ValueError, match="VERSION"):
            register_component("chunker", "bad")(type("NoVersion", (), {}))

    def test_identity_chunker_version_is_semver(self):
        assert isinstance(IdentityChunker.VERSION, SemVer)


class TestValidatePipelineSteps:
    """Scenario 3: static compatibility validation."""

    def test_identity_to_identity_passes(self):
        errors, warnings = validate_pipeline_steps(
            [
                {"name": "s1", "strategy": "identity"},
                {"name": "s2", "strategy": "identity"},
            ]
        )
        assert len(errors) == 0

    def test_unknown_strategy_reports_error(self):
        errors, _ = validate_pipeline_steps(
            [{"name": "s1", "strategy": "no_such_strategy"}]
        )
        assert len(errors) >= 1
        assert "unknown" in errors[0].lower()

    def test_metadata_mismatch_detected(self):
        """Mock a strategy that requires code_ratio — identity doesn't provide it."""
        # Temporarily register a mock strategy
        class MockFilter:
            VERSION = SemVer(1, 0, 0)
            requires_metadata = {"code_ratio"}
            provides_metadata = set()

            def chunk(self, content):
                return []

        register_component("chunker", "mock_filter")(MockFilter)
        errors, _ = validate_pipeline_steps(
            [
                {"name": "s1", "strategy": "identity"},
                {"name": "s2", "strategy": "mock_filter"},
            ]
        )
        assert len(errors) >= 1
        assert "code_ratio" in errors[0]
        assert "s1" in errors[0]  # error message references the previous step name

    def test_returns_tuple_of_lists(self):
        result = validate_pipeline_steps([])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], list)


class TestValidationError:
    def test_structured_fields(self):
        ve = ValidationError(
            field="chunks[0].span",
            code="INVERTED_SPAN",
            message="Span inverted: (5, 3)",
            level="error",
        )
        assert ve.field == "chunks[0].span"
        assert ve.code == "INVERTED_SPAN"
        assert ve.level == "error"

    def test_default_level_is_error(self):
        ve = ValidationError(field="x", code="Y", message="z")
        assert ve.level == "error"
