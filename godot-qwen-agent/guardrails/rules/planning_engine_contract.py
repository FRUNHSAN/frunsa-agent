"""Rule: planning engine must emit all registered planning.* and agent.* keys.

Phase 15: ERROR level. The 4 planning.* keys were defined in Phase 10;
agent.identity is the first agent.* namespace key. Two checks:

1. Missing required keys: if the planning engine's source code
   contains ANY planning.* or agent.* key, it must contain ALL keys
   registered with engine="planning".
   Severity: ERROR.

2. Unregistered planning/agent keys: any key with the "planning." or
   "agent." prefix not in the registered set is a pollution error.
   Severity: ERROR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set

from guardrails.report import Severity, Violation
from guardrails.rules._ast_utils import collect_trace_keys_from_engine


def _load_planning_keys() -> Set[str]:
    """Load registered planning.* and agent.* key names from TRACE_KEY_REGISTRY."""
    try:
        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        return {
            k for k, v in TRACE_KEY_REGISTRY.items()
            if v.engine == "planning"
        }
    except ImportError:
        return set()


def planning_engine_contract(root: Path) -> List[Violation]:
    """Verify planning engine emits complete, correct trace key sets.

    Two checks, both ERROR severity:
      1. Missing required keys: engine has some planning.* or agent.* keys
         but not all registered ones → ERROR (incomplete contract)
      2. Unregistered planning/agent keys: engine emits a key with
         "planning." or "agent." prefix not in the registered set → ERROR
         (potential typo or pollution)
    """
    violations: List[Violation] = []
    registered_keys = _load_planning_keys()

    if not registered_keys:
        return violations  # registry not loaded — don't block

    planning_dir = root / "engines" / "planning"
    if not planning_dir.is_dir():
        return violations  # planning engine not yet created

    engine_keys = collect_trace_keys_from_engine(planning_dir)
    if not engine_keys:
        return violations  # no trace_context dicts found

    # Filter to planning.* and agent.* keys only (keys owned by planning engine)
    planning_prefixes = ("planning.", "agent.")
    source_planning_keys = {
        k for k in engine_keys
        if any(k.startswith(prefix) for prefix in planning_prefixes)
    }

    if not source_planning_keys:
        return violations  # no planning keys emitted — no claim to check

    # Check 1: Missing required keys
    missing = registered_keys - source_planning_keys
    if missing:
        violations.append(Violation(
            rule_id="planning-engine-contract-001",
            severity=Severity.ERROR,
            message=(
                f"Planning engine emits {len(source_planning_keys)} "
                f"of {len(registered_keys)} required planning trace keys. "
                f"Missing: {sorted(missing)}. "
                f"All keys registered with engine='planning' must be emitted "
                f"on every planning StreamItem."
            ),
            file="engines/planning/",
        ))

    # Check 2: Unregistered planning/agent keys (pollution detection)
    unregistered = source_planning_keys - registered_keys
    if unregistered:
        violations.append(Violation(
            rule_id="planning-engine-contract-002",
            severity=Severity.ERROR,
            message=(
                f"Planning engine emits unregistered planning/agent key(s): "
                f"{sorted(unregistered)}. "
                f"Registered planning keys are: {sorted(registered_keys)}. "
                f"Remove the unregistered key or add a TraceKeyDef entry "
                f"to core/observability/trace_registry.py."
            ),
            file="engines/planning/",
        ))

    return violations
