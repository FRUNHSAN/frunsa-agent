"""Rule: critic engine must emit all registered critic.* keys.

Phase 16: ERROR level. Two checks:

1. Missing required keys: if the critic engine's source code
   contains ANY critic.* key, it must contain ALL keys
   registered with engine="critic".
   Severity: ERROR.

2. Unregistered critic keys: any key with the "critic." prefix
   not in the registered set is a pollution error.
   Severity: ERROR.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

from guardrails.report import Severity, Violation
from guardrails.rules._ast_utils import collect_trace_keys_from_engine


def _load_critic_keys() -> Set[str]:
    """Load registered critic.* key names from TRACE_KEY_REGISTRY."""
    try:
        from core.observability.trace_registry import TRACE_KEY_REGISTRY

        return {
            k for k, v in TRACE_KEY_REGISTRY.items()
            if v.engine == "critic"
        }
    except ImportError:
        return set()


def critic_engine_contract(root: Path) -> List[Violation]:
    """Verify critic engine emits complete, correct trace key sets.

    Two checks, both ERROR severity:
      1. Missing required keys: engine has some critic.* keys
         but not all registered ones → ERROR (incomplete contract)
      2. Unregistered critic keys: engine emits a key with
         "critic." prefix not in the registered set → ERROR
         (potential typo or pollution)

    Note: agent.identity is NOT checked here. It is registered with
    engine="planning" (Phase 15) and checked by planning_engine_contract.
    The critic engine also produces agent.identity (Phase 16 technical
    debt — deferred to Phase 17+ multi-engine registration refactor).
    """
    violations: List[Violation] = []
    registered_keys = _load_critic_keys()

    if not registered_keys:
        return violations

    critic_dir = root / "engines" / "critic"
    if not critic_dir.is_dir():
        return violations

    engine_keys = collect_trace_keys_from_engine(critic_dir)
    if not engine_keys:
        return violations

    # Filter to critic.* keys only (keys owned by critic engine)
    source_critic_keys = {
        k for k in engine_keys
        if k.startswith("critic.")
    }

    if not source_critic_keys:
        return violations

    # Check 1: Missing required keys
    missing = registered_keys - source_critic_keys
    if missing:
        violations.append(Violation(
            rule_id="critic-engine-contract-001",
            severity=Severity.ERROR,
            message=(
                f"Critic engine emits {len(source_critic_keys)} "
                f"of {len(registered_keys)} required critic trace keys. "
                f"Missing: {sorted(missing)}. "
                f"All keys registered with engine='critic' must be emitted "
                f"on every critic StreamItem."
            ),
            file="engines/critic/",
        ))

    # Check 2: Unregistered critic keys (pollution detection)
    unregistered = source_critic_keys - registered_keys
    if unregistered:
        violations.append(Violation(
            rule_id="critic-engine-contract-002",
            severity=Severity.ERROR,
            message=(
                f"Critic engine emits unregistered critic key(s): "
                f"{sorted(unregistered)}. "
                f"Registered critic keys are: {sorted(registered_keys)}. "
                f"Remove the unregistered key or add a TraceKeyDef entry "
                f"to core/observability/trace_registry.py."
            ),
            file="engines/critic/",
        ))

    return violations
