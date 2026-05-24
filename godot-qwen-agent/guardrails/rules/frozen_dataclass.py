"""Rule 2: Frozen dataclass integrity.

All @dataclass in core/contracts/ must use frozen=True.
Dict-typed fields must be wrapped in MappingProxyType via __post_init__.
object.__setattr__ usage on frozen dataclass instances is flagged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def frozen_dataclass_integrity(root: Path) -> List[Violation]:
    violations: List[Violation] = []

    contracts_dir = root / "core" / "contracts"
    if not contracts_dir.is_dir():
        return violations

    for py_file in contracts_dir.glob("*.py"):
        tree = _parse(py_file)
        if tree is None:
            continue

        # Find all dataclass decorators
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                dc = _get_dataclass_decorator(node)
                if dc is None:
                    continue  # Not a dataclass — skip

                # Check frozen=True
                if not _has_frozen(dc):
                    has_collections = bool(_find_dict_fields(node))
                    violations.append(Violation(
                        rule_id="frozen-001",
                        severity=Severity.ERROR if has_collections else Severity.WARNING,
                        message=f"@dataclass '{node.name}' missing frozen=True"
                                + (" (has collection fields — mutation risk)" if has_collections else ""),
                        file=str(py_file.relative_to(root)),
                        line=node.lineno,
                        snippet=f"class {node.name}:",
                    ))
                    continue

                # Check dict fields have MappingProxyType in __post_init__
                dict_fields = _find_dict_fields(node)
                if dict_fields and not _has_post_init_mappingproxy(node):
                    violations.append(Violation(
                        rule_id="frozen-002",
                        severity=Severity.ERROR,
                        message=(
                            f"frozen @dataclass '{node.name}' has dict fields "
                            f"({sorted(dict_fields)}) without MappingProxyType in __post_init__"
                        ),
                        file=str(py_file.relative_to(root)),
                        line=node.lineno,
                        snippet=f"class {node.name}: fields={sorted(dict_fields)}",
                    ))

        # Check for object.__setattr__ outside of __post_init__
        # (inside __post_init__ it's the standard pattern for frozen dataclasses)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_object_setattr(node):
                if not _inside_post_init(node, tree):
                    violations.append(Violation(
                        rule_id="frozen-003",
                        severity=Severity.ERROR,
                        message="object.__setattr__ outside __post_init__ bypasses frozen dataclass — create new instance instead",
                        file=str(py_file.relative_to(root)),
                        line=node.lineno,
                        snippet=_node_source(node, py_file),
                    ))

    # Also check steps/ for __setattr__ on frozen types (outside __post_init__)
    steps_dir = root / "core" / "steps"
    if steps_dir.is_dir():
        for py_file in steps_dir.glob("*.py"):
            tree = _parse(py_file)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _is_object_setattr(node):
                    if not _inside_post_init(node, tree):
                        violations.append(Violation(
                            rule_id="frozen-003",
                            severity=Severity.ERROR,
                            message="object.__setattr__ outside __post_init__ bypasses frozen dataclass — create new instance instead",
                            file=str(py_file.relative_to(root)),
                            line=node.lineno,
                            snippet=_node_source(node, py_file),
                        ))

    return violations


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _get_dataclass_decorator(node: ast.ClassDef) -> ast.Call | None:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and _name_matches(dec.func, "dataclass"):
            return dec
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return ast.Call(func=dec, args=[], keywords=[])  # bare @dataclass
    return None


def _has_frozen(dc: ast.Call) -> bool:
    for kw in dc.keywords:
        if kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _find_dict_fields(node: ast.ClassDef) -> List[str]:
    """Find fields annotated as dict or Dict[...] that don't already use MappingProxyType."""
    dict_fields = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            annotation = item.annotation
            if annotation is None:
                continue
            type_str = ast.unparse(annotation)
            # dict or Dict[...] but NOT MappingProxyType
            if ("dict" in type_str.lower() and "mappingproxytype" not in type_str.lower()):
                dict_fields.append(item.target.id)
    return dict_fields


def _has_post_init_mappingproxy(node: ast.ClassDef) -> bool:
    """Check if __post_init__ uses MappingProxyType for dict fields."""
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__post_init__":
            source = ast.unparse(item)
            if "MappingProxyType" in source:
                return True
    return False


def _inside_post_init(node: ast.AST, tree: ast.AST) -> bool:
    """Check if node is inside a __post_init__ method (where object.__setattr__ is legitimate)."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.FunctionDef) and parent.name == "__post_init__":
            # Check if node is within this function's body
            for child in ast.walk(parent):
                if child is node:
                    return True
    return False


def _is_object_setattr(node: ast.Call) -> bool:
    """Check if call is object.__setattr__ or setattr(..., ...)."""
    if isinstance(node.func, ast.Attribute):
        if node.func.attr == "__setattr__":
            if isinstance(node.func.value, ast.Name):
                return node.func.value.id == "object"
    return False


def _name_matches(node: ast.expr, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    return False


def _node_source(node: ast.AST, file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if hasattr(node, "lineno") and node.lineno <= len(lines):
            return lines[node.lineno - 1].strip()
    except Exception:
        pass
    return ""
