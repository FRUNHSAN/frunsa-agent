"""Rule: trace_context dict values must be JSON-serializable types.

Split severity:
  ERROR — ast.Call, ast.Attribute, ast.Tuple, ast.Set, ast.BinOp, ast.UnaryOp
  WARNING (REVIEW_REQUIRED) — ast.Name (AST cannot track runtime types)

Design rationale: AST-based type inference has fundamental limits. Variable
references to JSON-serializable types (step_idx: int, chunk_name: str)
are a common and valid pattern. Blocking them with ERROR would force all
trace_context values to be inline literals. WARNING preserves visibility
without penalizing legitimate code.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def trace_key_serializability(root: Path) -> List[Violation]:
    """Verify trace_context dict VALUES are JSON-serializable types.

    AST scans for dict literals used as the trace_context= keyword argument.
    Recursively checks all values (not keys — keys covered by trace-context-001).
    """
    violations: List[Violation] = []

    for scan_dir in ["core", "engines"]:
        target = root / scan_dir
        if not target.is_dir():
            continue

        for py_file in target.glob("**/*.py"):
            rel = str(py_file.relative_to(root))

            if "test" in rel.lower():
                continue
            # Stubs are provisional engine implementations that produce
            # trace_context naturally — exclude them from value-type checks
            if "stub.py" in rel:
                continue

            tree = _parse(py_file)
            if tree is None:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in getattr(node, "keywords", []):
                        if kw.arg == "trace_context" and isinstance(kw.value, ast.Dict):
                            _check_dict_values(kw.value, py_file, rel, violations)

    return violations


def _check_dict_values(
    dict_node: ast.Dict,
    file_path: Path,
    rel: str,
    violations: List[Violation],
) -> None:
    """Recursively check all values in a dict for JSON serializability."""
    for value_node in dict_node.values:
        if value_node is None:
            continue
        _check_value_node(value_node, file_path, rel, violations)


def _check_value_node(
    node: ast.AST,
    file_path: Path,
    rel: str,
    violations: List[Violation],
) -> None:
    """Check a single value node and recurse into containers."""
    # Allowed: simple constants
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool, type(None))):
            return
        # Other constant types (bytes, complex, etc.) — not JSON-serializable
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.ERROR,
            message=(
                f"trace_context value has non-JSON type: "
                f"{type(node.value).__name__}. Use str, int, float, bool, list, or dict."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # Allowed: list — recurse into elements
    if isinstance(node, ast.List):
        for elt in node.elts:
            _check_value_node(elt, file_path, rel, violations)
        return

    # Allowed: dict — recurse into values
    if isinstance(node, ast.Dict):
        _check_dict_values(node, file_path, rel, violations)
        return

    # ERROR: function calls produce non-JSON types (datetime.now(), uuid4(), etc.)
    if isinstance(node, ast.Call):
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.ERROR,
            message=(
                "trace_context value is a function call — likely not JSON-serializable. "
                "Use inline literals or ensure the callable returns a JSON-safe type."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # ERROR: attribute access could resolve to non-serializable objects
    if isinstance(node, ast.Attribute):
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.ERROR,
            message=(
                "trace_context value is an attribute access — cannot verify JSON safety at AST level. "
                "Use inline literals."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # ERROR: Tuple/Set are not valid JSON types
    if isinstance(node, (ast.Tuple, ast.Set)):
        node_type = "tuple" if isinstance(node, ast.Tuple) else "set"
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.ERROR,
            message=(
                f"trace_context value is a {node_type} — not a valid JSON type. "
                "Use list instead."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # ERROR: BinOp/UnaryOp produce unknown types
    if isinstance(node, (ast.BinOp, ast.UnaryOp)):
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.ERROR,
            message=(
                "trace_context value is an expression — cannot verify JSON safety at AST level. "
                "Use inline literals."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # WARNING: variable references — AST cannot track runtime types
    if isinstance(node, ast.Name):
        violations.append(Violation(
            rule_id="trace-key-serializability-001",
            severity=Severity.WARNING,
            message=(
                f"trace_context value is a variable reference ('{node.id}') — "
                f"AST cannot verify runtime type. REVIEW_REQUIRED: ensure the variable "
                f"holds a JSON-serializable value (str, int, float, bool, list, dict, None)."
            ),
            file=rel,
            line=node.lineno,
            snippet=_node_source(node, file_path),
        ))
        return

    # Catch-all for unhandled node types
    violations.append(Violation(
        rule_id="trace-key-serializability-001",
        severity=Severity.ERROR,
        message=(
            f"trace_context value has unhandled AST node type: {type(node).__name__}. "
            "Use JSON-serializable inline literals."
        ),
        file=rel,
        line=getattr(node, "lineno", 0),
        snippet=_node_source(node, file_path),
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
