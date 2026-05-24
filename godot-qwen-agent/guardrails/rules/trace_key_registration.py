"""Rule: trace_context dict keys must be registered in TRACE_KEY_REGISTRY.

Phase 11: WARNING level. Unregistered keys serialize fine but lack documented
semantics. New engines in Phase 12+ will naturally add keys — WARNING nudges
without blocking. Upgrade to ERROR in Phase 13+ after registry coverage matures.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def _get_registry_keys() -> frozenset:
    """Lazy-load TRACE_KEY_REGISTRY keys for guardrail comparison."""
    try:
        from core.observability.trace_registry import TRACE_KEY_REGISTRY
        return frozenset(TRACE_KEY_REGISTRY.keys())
    except ImportError:
        return frozenset()  # registry not yet created — don't block bootstrapping


def trace_key_registration(root: Path) -> List[Violation]:
    """Verify all trace_context dict keys exist in TRACE_KEY_REGISTRY.

    AST scans for dict literals used as the trace_context= keyword argument.
    Each string key is checked against the registry. Unregistered keys get WARNING.
    """
    violations: List[Violation] = []
    registry_keys = _get_registry_keys()

    for scan_dir in ["core", "engines"]:
        target = root / scan_dir
        if not target.is_dir():
            continue

        for py_file in target.glob("**/*.py"):
            rel = str(py_file.relative_to(root))

            if "test" in rel.lower():
                continue
            if "stub.py" in rel:
                continue

            tree = _parse(py_file)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in getattr(node, "keywords", []):
                        if kw.arg == "trace_context" and isinstance(kw.value, ast.Dict):
                            _check_dict_keys(kw.value, py_file, rel, violations, registry_keys)

    return violations


def _check_dict_keys(
    dict_node: ast.Dict,
    file_path: Path,
    rel: str,
    violations: List[Violation],
    registry_keys: frozenset,
) -> None:
    """Check all string keys in a dict literal for registry membership."""
    for key_node in dict_node.keys:
        if key_node is None:
            continue  # ** unpacking — can't analyze
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            key = key_node.value
            if key not in registry_keys:
                violations.append(Violation(
                    rule_id="trace-key-registration-001",
                    severity=Severity.WARNING,
                    message=(
                        f"trace_context key '{key}' is not registered in TRACE_KEY_REGISTRY. "
                        f"Add a TraceKeyDef(type=..., semantics=\"...\", engine=\"{key.split('.')[0]}\") "
                        f"entry to core/observability/trace_registry.py."
                    ),
                    file=rel,
                    line=key_node.lineno,
                    snippet=_node_source(key_node, file_path),
                ))
        # Non-string keys (variables, expressions) — can't check, skip silently
        # They'll be caught by trace_key_serializability if needed


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _node_source(node: ast.AST, file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if hasattr(node, "lineno") and node.lineno <= len(lines):
            return lines[node.lineno - 1].strip()
    except Exception:
        pass
    return ""
