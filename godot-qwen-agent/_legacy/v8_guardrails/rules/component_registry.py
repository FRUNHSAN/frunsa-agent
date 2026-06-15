"""Rule 3: Component registration coverage.

Classes in core/steps/ that implement run() and health_check() should be
registered via @register_component.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def component_registration_coverage(root: Path) -> List[Violation]:
    violations: List[Violation] = []

    steps_dir = root / "core" / "steps"
    if not steps_dir.is_dir():
        return violations

    for py_file in steps_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        tree = _parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                has_run = _has_method(node, "run")
                has_health = _has_method(node, "health_check")
                is_registered = _has_register_decorator(node)

                if has_run and has_health and not is_registered:
                    violations.append(Violation(
                        rule_id="registry-001",
                        severity=Severity.WARNING,
                        message=(
                            f"Class '{node.name}' has run() + health_check() "
                            f"but is not @register_component decorated"
                        ),
                        file=str(py_file.relative_to(root)),
                        line=node.lineno,
                        snippet=f"class {node.name}:",
                    ))

    return violations


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _has_method(node: ast.ClassDef, name: str) -> bool:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == name:
            return True
    return False


def _has_register_decorator(node: ast.ClassDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            if _name_matches(dec.func, "register_component"):
                return True
    return False


def _name_matches(node: ast.expr, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    return False
