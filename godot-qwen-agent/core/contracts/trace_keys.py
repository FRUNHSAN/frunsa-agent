"""Component-level trace key contracts (Phase 13).

Defines formal trace contracts that engines MUST satisfy to claim
conformance to a component capability. Follows the same frozen-dataclass
+ registry + validation pattern established in validation.py.

Component types: retrieval, generation, scoring.
Each component type defines required trace keys that every engine
claiming that capability must emit in its trace_context dicts.

Distinct from core/observability/trace_registry.py which documents
engine-internal keys. The ENGINE_TO_COMPONENT_MAP in trace_registry.py
resolves engine-specific keys to these canonical component keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from core.contracts.validation import ContractValidationResult, ValidationError


@dataclass(frozen=True)
class ComponentTraceKeyDef:
    """One component-level trace key contract.

    Unlike TraceKeyDef (engine-level, observability layer), this lives
    in the component platform and defines what engines MUST emit to
    claim conformance to a component capability.

    The full_key property composes the dotted name
    (e.g. "retrieval.chunk_id") from component_type and key_suffix.
    """

    component_type: str  # "retrieval" | "generation" | "scoring"
    key_suffix: str      # e.g. "chunk_id", "latency_ms", "cumulative_tokens"
    type: type           # int, str, float
    semantics: str       # Human-readable description
    unit: str = ""       # "tokens", "ms", etc.

    @property
    def full_key(self) -> str:
        return f"{self.component_type}.{self.key_suffix}"


# ── Component Trace Key Registry ─────────────────────────────────────

COMPONENT_TRACE_KEYS: Dict[str, ComponentTraceKeyDef] = {
    # ── Retrieval capability ──
    "retrieval.chunk_id": ComponentTraceKeyDef(
        component_type="retrieval",
        key_suffix="chunk_id",
        type=str,
        semantics="Unique identifier of the retrieved chunk in the vector store",
    ),
    "retrieval.latency_ms": ComponentTraceKeyDef(
        component_type="retrieval",
        key_suffix="latency_ms",
        type=float,
        semantics="Wall-clock time for the vector store retrieval call, in milliseconds",
        unit="ms",
    ),

    # ── Generation capability ──
    "generation.cumulative_tokens": ComponentTraceKeyDef(
        component_type="generation",
        key_suffix="cumulative_tokens",
        type=int,
        semantics="Total LLM tokens consumed across all generation steps so far",
        unit="tokens",
    ),

    # ── Scoring capability ──
    # No component_candidate keys exist for scoring yet.
    # When a scoring engine is built (Phase 14+), add scoring.* keys here.
    #
    # Note: "scoring" is a valid component type even with 0 required keys.
    # _REQUIRED_KEYS_BY_TYPE is populated below; scoring gets an empty set.
    # This ensures validate_component_trace(ctx, "scoring") succeeds
    # (empty context passes — 0 required keys to check).
}


# ── Component Trace Validator ─────────────────────────────────────────

def validate_component_trace(
    trace_context: Dict[str, Any] | None,
    component_type: str,
) -> ContractValidationResult:
    """Validate that a trace_context satisfies the component trace contract.

    Checks:
      1. trace_context is not None (ERROR if it is)
      2. component_type is known (ERROR if not in COMPONENT_TRACE_KEYS)
      3. Every required key for component_type is present (ERROR if missing)
      4. Every key value matches declared type via isinstance (ERROR if mismatch)
      5. Extra keys not in the registry for that component type (WARNING)

    Returns ContractValidationResult with passed=True only if no errors.
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationError] = []

    # Null check
    if trace_context is None:
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="trace_context",
                    code="NULL_TRACE_CONTEXT",
                    message="trace_context is None — component trace contract requires a dict",
                )
            ],
        )

    # Unknown component type
    if component_type not in _REQUIRED_KEYS_BY_TYPE:
        known = sorted(_REQUIRED_KEYS_BY_TYPE.keys())
        return ContractValidationResult(
            passed=False,
            errors=[
                ValidationError(
                    field="component_type",
                    code="UNKNOWN_COMPONENT_TYPE",
                    message=f"Unknown component_type '{component_type}'. Known: {known}",
                )
            ],
        )

    required_keys = _REQUIRED_KEYS_BY_TYPE[component_type]

    # Check required key presence and type match
    for full_key in required_keys:
        defn = COMPONENT_TRACE_KEYS[full_key]
        if full_key not in trace_context:
            errors.append(
                ValidationError(
                    field=full_key,
                    code="MISSING_REQUIRED_KEY",
                    message=(
                        f"Required key '{full_key}' ({defn.type.__name__}) "
                        f"is missing from trace_context. "
                        f"Semantics: {defn.semantics}"
                    ),
                )
            )
        else:
            value = trace_context[full_key]
            if not isinstance(value, defn.type):
                errors.append(
                    ValidationError(
                        field=full_key,
                        code="TYPE_MISMATCH",
                        message=(
                            f"Key '{full_key}' has type {type(value).__name__}, "
                            f"expected {defn.type.__name__}. Value: {repr(value)[:80]}"
                        ),
                    )
                )

    # Check for extra keys (keys in trace_context not in this component type's contract)
    for key in trace_context:
        if key not in required_keys:
            warnings.append(
                ValidationError(
                    field=key,
                    code="EXTRA_KEY",
                    message=(
                        f"Key '{key}' is present in trace_context but is not "
                        f"a required key for component_type '{component_type}'. "
                        f"May be an engine-internal key or a typo."
                    ),
                    level="warning",
                )
            )

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# Cache: component_type -> set of full_key names
_REQUIRED_KEYS_BY_TYPE: Dict[str, set[str]] = {}
for _key_name, _defn in COMPONENT_TRACE_KEYS.items():
    _REQUIRED_KEYS_BY_TYPE.setdefault(_defn.component_type, set()).add(_key_name)

# Ensure scoring is a recognized type even with 0 keys
if "scoring" not in _REQUIRED_KEYS_BY_TYPE:
    _REQUIRED_KEYS_BY_TYPE["scoring"] = set()
