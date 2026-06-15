"""Rule: orchestration engine must emit all 6 registered trace keys.

Phase 14: ERROR level. The 6 orchestration.* keys were pre-defined in
Phase 12 — there is no exploratory phase. Two checks:

1. Missing required keys: if the orchestration engine's source code
   contains ANY orchestration.* key, it must contain ALL 6.
   Severity: ERROR.

2. Unregistered orchestration keys: any key with the "orchestration."
   prefix not in the 6 registered keys is a pollution error.
   Severity: ERROR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set

from guardrails.report import Severity, Violation
from guardrails.rules._ast_utils import collect_trace_keys_from_engine


def _load_orchestration_keys() -> Set[str]:
    """Load registered orchestration.* key names from TRACE_KEY_REGISTRY.

    Filters by key prefix (orchestration.*), not by engine registration,
    because keys like agent.identity may be registered to multiple engines
    including orchestration without being orchestration-specific keys.
    """
    try:
        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        return {
            k for k, v in TRACE_KEY_REGISTRY.items()
            if k.startswith("orchestration.")
        }
    except ImportError:
        return set()


def orchestration_trace_completeness(root: Path) -> List[Violation]:
    """Verify orchestration engine emits complete, correct trace key sets.

    Two checks, both ERROR severity:
      1. Missing required keys: engine has some orchestration.* keys
         but not all 6 → ERROR (incomplete contract)
      2. Unregistered orchestration keys: engine emits a key with
         "orchestration." prefix not in the 6 registered keys → ERROR
         (potential typo or pollution)
    """
    violations: List[Violation] = []
    registered_keys = _load_orchestration_keys()

    if not registered_keys:
        return violations  # registry not loaded — don't block

    orch_dir = root / "engines" / "orchestration"
    if not orch_dir.is_dir():
        return violations  # orchestration engine not yet created

    engine_keys = collect_trace_keys_from_engine(orch_dir)
    if not engine_keys:
        # Engine directory exists but has no trace_context dicts
        # This is unusual — the stub should have them
        return violations

    # Filter to orchestration.* keys only
    orch_keys_in_source = {k for k in engine_keys if k.startswith("orchestration.")}

    if not orch_keys_in_source:
        return violations  # no orchestration keys emitted — no claim to check

    # Check 1: Missing required keys
    missing = registered_keys - orch_keys_in_source
    if missing:
        violations.append(Violation(
            rule_id="orchestration-trace-completeness-001",
            severity=Severity.ERROR,
            message=(
                f"Orchestration engine emits {len(orch_keys_in_source)} "
                f"of {len(registered_keys)} required orchestration trace keys. "
                f"Missing: {sorted(missing)}. "
                f"All 6 orchestration.* keys defined in Phase 12 pre-design "
                f"must be emitted on every orchestration StreamItem."
            ),
            file="engines/orchestration/",
        ))

    # Check 2: Unregistered orchestration keys (pollution detection)
    unregistered = orch_keys_in_source - registered_keys
    if unregistered:
        violations.append(Violation(
            rule_id="orchestration-trace-completeness-002",
            severity=Severity.ERROR,
            message=(
                f"Orchestration engine emits unregistered orchestration key(s): "
                f"{sorted(unregistered)}. "
                f"Registered orchestration keys are: {sorted(registered_keys)}. "
                f"Remove the unregistered key or add a TraceKeyDef entry "
                f"to core/observability/trace_registry.py."
            ),
            file="engines/orchestration/",
        ))

    return violations
