"""Rule: engines must emit complete sets of component trace keys.

Phase 13: WARNING level. If an engine emits ANY trace_context key that maps
to a component type (via ENGINE_TO_COMPONENT_MAP), it must emit ALL required
keys for that component type. Upgrade to ERROR in Phase 14+.

Example: if an engine writes "rag.chunk_id" (maps to retrieval.chunk_id),
it must also write "rag.retrieval_latency_ms" (maps to retrieval.latency_ms).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from guardrails.report import Severity, Violation
from guardrails.rules._ast_utils import collect_trace_keys_from_engine


def _load_component_contracts() -> Dict[str, Set[str]]:
    """Load required keys per component type from COMPONENT_TRACE_KEYS."""
    try:
        from core.contracts.trace_keys import COMPONENT_TRACE_KEYS

        required: Dict[str, Set[str]] = defaultdict(set)
        for defn in COMPONENT_TRACE_KEYS.values():
            required[defn.component_type].add(defn.full_key)
        return dict(required)
    except ImportError:
        return {}


def _load_engine_mapping() -> Dict[str, str]:
    """Load engine-to-component key mapping."""
    try:
        from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP
        return dict(ENGINE_TO_COMPONENT_MAP)
    except ImportError:
        return {}


def _reverse_map(engine_map: Dict[str, str], component_type: str) -> Dict[str, str]:
    """Build reverse map: component_key -> engine_key for a component type."""
    return {
        ck: ek
        for ek, ck in engine_map.items()
        if ck.startswith(f"{component_type}.")
    }


def component_trace_completeness(root: Path) -> List[Violation]:
    """Verify engines emit complete component trace key sets.

    For each engine directory under engines/: collect all trace_context
    dict keys via AST scan, resolve through ENGINE_TO_COMPONENT_MAP to
    component types, then verify each referenced component type has ALL
    its required keys present.

    Engine emits NO component keys → no violation (no claim to check).
    Engine emits SOME but not ALL retrieval keys → WARNING.
    """
    violations: List[Violation] = []
    component_required = _load_component_contracts()
    engine_map = _load_engine_mapping()

    if not component_required or not engine_map:
        return violations

    engines_dir = root / "engines"
    if not engines_dir.is_dir():
        return violations

    for engine_dir in engines_dir.iterdir():
        if not engine_dir.is_dir():
            continue
        engine_name = engine_dir.name

        engine_keys = collect_trace_keys_from_engine(engine_dir)
        if not engine_keys:
            continue

        # Resolve to component types
        component_types_seen: Set[str] = set()
        for key in engine_keys:
            component_key = engine_map.get(key)
            if component_key:
                ct = component_key.split(".", 1)[0]
                component_types_seen.add(ct)

        # Check completeness per component type
        for ct in sorted(component_types_seen):
            required = component_required.get(ct, set())

            # Map required component keys to engine-key equivalents
            rev_map = _reverse_map(engine_map, ct)
            required_as_engine: Set[str] = set()
            for rk in required:
                ek = rev_map.get(rk)
                if ek:
                    required_as_engine.add(ek)
                else:
                    # No engine mapping — component key used directly
                    required_as_engine.add(rk)

            present = engine_keys & required_as_engine
            missing = required_as_engine - engine_keys

            if missing:
                violations.append(Violation(
                    rule_id="component-trace-completeness-001",
                    severity=Severity.WARNING,
                    message=(
                        f"Engine '{engine_name}' references component type "
                        f"'{ct}' (via keys {sorted(present)}) but is missing "
                        f"required trace keys: {sorted(missing)}. "
                        f"Component contract for '{ct}' requires: "
                        f"{sorted(required_as_engine)}."
                    ),
                    file=f"engines/{engine_name}/",
                ))

    return violations



