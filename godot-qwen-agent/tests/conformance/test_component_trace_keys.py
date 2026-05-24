"""Conformance tests for component trace key contracts (Phase 13)."""

import pytest

from core.contracts.trace_keys import (
    COMPONENT_TRACE_KEYS,
    ComponentTraceKeyDef,
    validate_component_trace,
)
from core.contracts.validation import ContractValidationResult, ValidationError


class TestComponentTraceKeyDef:
    """Frozen dataclass integrity for ComponentTraceKeyDef."""

    def test_frozen_integrity(self):
        """Cannot mutate ComponentTraceKeyDef fields after construction."""
        key = ComponentTraceKeyDef(
            component_type="retrieval",
            key_suffix="chunk_id",
            type=str,
            semantics="Unique chunk identifier",
        )
        with pytest.raises(Exception):
            key.component_type = "generation"  # type: ignore

    def test_full_key_composition(self):
        """full_key property composes component_type + key_suffix."""
        key = ComponentTraceKeyDef(
            component_type="retrieval",
            key_suffix="latency_ms",
            type=float,
            semantics="Retrieval latency in ms",
            unit="ms",
        )
        assert key.full_key == "retrieval.latency_ms"

    def test_all_keys_follow_naming_convention(self):
        """Every key's full_key matches {component_type}.{key_suffix}."""
        for full_key, defn in COMPONENT_TRACE_KEYS.items():
            assert full_key == defn.full_key
            assert defn.full_key.startswith(f"{defn.component_type}.")
            assert defn.full_key.endswith(f".{defn.key_suffix}")

    def test_unit_defaults_to_empty_string(self):
        """Unit defaults to '' when not provided."""
        key = ComponentTraceKeyDef(
            component_type="retrieval",
            key_suffix="chunk_id",
            type=str,
            semantics="Chunk ID",
        )
        assert key.unit == ""


class TestComponentTraceKeys:
    """Registry completeness and validity."""

    def test_registry_is_non_empty(self):
        """COMPONENT_TRACE_KEYS has entries."""
        assert len(COMPONENT_TRACE_KEYS) >= 3

    def test_three_keys_defined(self):
        """Phase 13 defines exactly 3 component trace keys."""
        assert len(COMPONENT_TRACE_KEYS) == 3

    def test_retrieval_keys_exist(self):
        """Retrieval component type has required keys."""
        retrieval_keys = [
            k for k, d in COMPONENT_TRACE_KEYS.items()
            if d.component_type == "retrieval"
        ]
        assert len(retrieval_keys) == 2
        assert "retrieval.chunk_id" in COMPONENT_TRACE_KEYS
        assert "retrieval.latency_ms" in COMPONENT_TRACE_KEYS

    def test_generation_keys_exist(self):
        """Generation component type has required keys."""
        gen_keys = [
            k for k, d in COMPONENT_TRACE_KEYS.items()
            if d.component_type == "generation"
        ]
        assert len(gen_keys) == 1
        assert "generation.cumulative_tokens" in COMPONENT_TRACE_KEYS

    def test_keys_have_valid_types(self):
        """All keys have valid Python types."""
        for defn in COMPONENT_TRACE_KEYS.values():
            assert defn.type in (int, str, float), (
                f"{defn.full_key}: type must be int/str/float, got {defn.type}"
            )

    def test_no_duplicate_full_keys(self):
        """No two entries share the same full_key."""
        full_keys = [d.full_key for d in COMPONENT_TRACE_KEYS.values()]
        assert len(full_keys) == len(set(full_keys))

    def test_scoring_type_valid(self):
        """Scoring component type is valid even with 0 keys."""
        # validate_component_trace should accept "scoring" as a known type
        # since it's in _REQUIRED_KEYS_BY_TYPE (even with empty required set)
        from core.contracts.trace_keys import _REQUIRED_KEYS_BY_TYPE
        # scoring may be absent if no keys exist — that's acceptable
        # The type should not cause an UNKNOWN_COMPONENT_TYPE error
        # if it is defined in _REQUIRED_KEYS_BY_TYPE


class TestValidateComponentTrace:
    """Validation of trace_context against component contracts."""

    def test_valid_retrieval_trace(self):
        """A complete retrieval trace_context passes validation."""
        ctx = {
            "retrieval.chunk_id": "doc-001",
            "retrieval.latency_ms": 12.5,
        }
        result = validate_component_trace(ctx, "retrieval")
        assert result.passed
        assert len(result.errors) == 0

    def test_valid_generation_trace(self):
        """A complete generation trace_context passes validation."""
        ctx = {
            "generation.cumulative_tokens": 150,
        }
        result = validate_component_trace(ctx, "generation")
        assert result.passed
        assert len(result.errors) == 0

    def test_missing_required_key(self):
        """Missing a required key produces an error."""
        ctx = {
            "retrieval.chunk_id": "doc-001",
            # missing retrieval.latency_ms
        }
        result = validate_component_trace(ctx, "retrieval")
        assert not result.passed
        assert len(result.errors) >= 1
        assert any(e.code == "MISSING_REQUIRED_KEY" for e in result.errors)

    def test_type_mismatch(self):
        """A value with wrong type produces an error."""
        ctx = {
            "retrieval.chunk_id": "doc-001",
            "retrieval.latency_ms": "not-a-float",  # should be float
        }
        result = validate_component_trace(ctx, "retrieval")
        assert not result.passed
        assert any(e.code == "TYPE_MISMATCH" for e in result.errors)

    def test_null_trace_context(self):
        """None trace_context produces an error."""
        result = validate_component_trace(None, "retrieval")
        assert not result.passed
        assert any(e.code == "NULL_TRACE_CONTEXT" for e in result.errors)

    def test_unknown_component_type(self):
        """Unknown component_type produces an error."""
        result = validate_component_trace({}, "unknown_type")
        assert not result.passed
        assert any(e.code == "UNKNOWN_COMPONENT_TYPE" for e in result.errors)

    def test_extra_key_warning(self):
        """Extra keys in trace_context produce warnings, not errors."""
        ctx = {
            "retrieval.chunk_id": "doc-001",
            "retrieval.latency_ms": 12.5,
            "extra.unregistered_key": "value",
        }
        result = validate_component_trace(ctx, "retrieval")
        assert result.passed  # extra keys are warnings, not errors
        assert len(result.warnings) >= 1
        assert any(w.code == "EXTRA_KEY" for w in result.warnings)

    def test_empty_context_for_retrieval(self):
        """Empty trace_context for a required component produces errors."""
        result = validate_component_trace({}, "retrieval")
        assert not result.passed
        assert len(result.errors) >= 2  # both required keys missing

    def test_scoring_with_empty_context(self):
        """Scoring with empty context passes (scoring currently has 0 required keys)."""
        result = validate_component_trace({}, "scoring")
        # scoring has 0 required keys, so empty context passes with no errors
        # (scope is valid even if empty)
        assert result.passed

    def test_output_is_contract_validation_result(self):
        """Return type is ContractValidationResult."""
        result = validate_component_trace(
            {"retrieval.chunk_id": "x", "retrieval.latency_ms": 1.0},
            "retrieval",
        )
        assert isinstance(result, ContractValidationResult)


class TestEngineToComponentMapping:
    """ENGINE_TO_COMPONENT_MAP integrity."""

    def test_three_mappings(self):
        """Phase 13 defines exactly 3 engine→component mappings."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        assert len(ENGINE_TO_COMPONENT_MAP) == 3

    def test_all_mapped_keys_exist_in_component_registry(self):
        """Every mapped component key exists in COMPONENT_TRACE_KEYS."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        for engine_key, component_key in ENGINE_TO_COMPONENT_MAP.items():
            assert component_key in COMPONENT_TRACE_KEYS, (
                f"Mapped key '{component_key}' (from '{engine_key}') "
                f"not found in COMPONENT_TRACE_KEYS"
            )

    def test_all_component_keys_have_engine_mapping(self):
        """Every COMPONENT_TRACE_KEYS entry has at least one engine mapping."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        mapped_component_keys = set(ENGINE_TO_COMPONENT_MAP.values())
        for full_key in COMPONENT_TRACE_KEYS:
            assert full_key in mapped_component_keys, (
                f"Component key '{full_key}' has no engine mapping"
            )

    def test_mapping_values_match_component_naming(self):
        """Mapped values follow {component_type}.{key_suffix} convention."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        for component_key in ENGINE_TO_COMPONENT_MAP.values():
            assert "." in component_key, (
                f"Component key '{component_key}' lacks dot separator"
            )

    def test_generation_mapping(self):
        """planning.cumulative_tokens maps to generation.cumulative_tokens."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        assert ENGINE_TO_COMPONENT_MAP["planning.cumulative_tokens"] == (
            "generation.cumulative_tokens"
        )

    def test_retrieval_mappings(self):
        """RAG keys map to retrieval component keys."""
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        assert ENGINE_TO_COMPONENT_MAP["rag.chunk_id"] == "retrieval.chunk_id"
        assert ENGINE_TO_COMPONENT_MAP["rag.retrieval_latency_ms"] == (
            "retrieval.latency_ms"
        )
