"""Rule: engine interface files must contain zero implementation.

Phase 10: engines/*/interface.py defines shapes (Protocols, dataclasses),
not behaviors. Function bodies must be exactly `...` (Ellipsis) — no
statements, no pass, no raise.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def engine_interface_purity(root: Path) -> List[Violation]:
    """Verify engines/*/interface.py has zero function bodies.

    AST scans for FunctionDef/AsyncFunctionDef nodes inside Protocol-like
    classes. The body of each method must contain only `...` (Ellipsis)
    and optionally a docstring. Any other statement is a violation.
    """
    violations: List[Violation] = []

    engines_dir = root / "engines"
    if not engines_dir.is_dir():
        return violations

    for py_file in engines_dir.glob("**/interface.py"):
        rel = str(py_file.relative_to(root))

        tree = _parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_body_ellipsis_only(node):
                    violations.append(Violation(
                        rule_id="engine-interface-001",
                        severity=Severity.ERROR,
                        message=(
                            f"Method '{node.name}' in engine interface has "
                            f"implementation body. Interface methods must use "
                            f"'...' (Ellipsis) only — no pass, raise, or statements."
                        ),
                        file=rel,
                        line=node.lineno,
                        snippet=_node_source(node, py_file),
                    ))

    return violations


def _is_body_ellipsis_only(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function body contains only docstring and/or Ellipsis."""
    body = func_node.body

    # Filter out docstrings (string expression statements at the top of body)
    effective = []
    for stmt in body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if isinstance(stmt.value.value, str):
                continue  # skip docstring
        effective.append(stmt)

    if len(effective) == 1:
        stmt = effective[0]
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is ...:  # Ellipsis literal
                return True

    return len(effective) == 0  # Empty body is also acceptable


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
