"""Rule: trace_context dict keys must use dot-separated engine prefixes.

Phase 10: prevents bare keys like "step" that could collide across engines.
All trace_context keys must contain "." — e.g. "planning.step_index",
"rag.chunk_id". Enforced at WARNING level to allow migration time.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


# Engines with known prefixes — keys under these top-level names are exempt
# from the "." check because they ARE the namespace prefix.
_KNOWN_ENGINES = {"planning", "rag", "retrieval", "generation", "scoring", "orchestration", "agent"}


def trace_context_namespace(root: Path) -> List[Violation]:
    """Verify trace_context dict keys contain '.' separator.

    AST scans for dict literals used as the trace_context= keyword argument.
    All string keys must contain '.' to indicate engine prefix (e.g.
    "planning.step_index"). Bare keys like "step" are flagged.
    """
    violations: List[Violation] = []

    for scan_dir in ["core", "engines"]:
        target = root / scan_dir
        if not target.is_dir():
            continue

        for py_file in target.glob("**/*.py"):
            rel = str(py_file.relative_to(root))

            # Exclude test files
            if "test" in rel.lower():
                continue

            tree = _parse(py_file)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in getattr(node, "keywords", []):
                        if kw.arg == "trace_context" and isinstance(kw.value, ast.Dict):
                            _check_dict_keys(kw.value, py_file, rel, violations)

    return violations


def _check_dict_keys(
    dict_node: ast.Dict,
    file_path: Path,
    rel: str,
    violations: List[Violation],
) -> None:
    """Check all string keys in a dict literal for '.' separator."""
    for key_node in dict_node.keys:
        if key_node is None:
            continue  # ** unpacking — can't analyze
        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
            key = key_node.value
            if "." not in key:
                violations.append(Violation(
                    rule_id="trace-context-001",
                    severity=Severity.WARNING,
                    message=(
                        f"trace_context key '{key}' lacks engine prefix. "
                        f"Use dot-separated namespace: e.g. 'planning.{key}' "
                        f"or 'rag.{key}'."
                    ),
                    file=rel,
                    line=key_node.lineno,
                    snippet=_node_source(key_node, file_path),
                ))


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
