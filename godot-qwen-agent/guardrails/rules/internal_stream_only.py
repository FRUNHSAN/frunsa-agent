"""Rule: internal_stream_only — InternalStream data must not leak to UserFacing.

Extends user_facing_stream_isolation by also checking that transport adapters
do not accidentally route internal_stream data to external consumers.

Behavior-based naming: describes WHAT the rule enforces, not WHAT DOMAIN.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation


def internal_stream_only(root: Path) -> List[Violation]:
    """Enforce: internal_stream data must never leak to UserFacing serialization.

    Scans core/adapters/ for code paths that write internal_stream data to
    UserFacing outputs (SSE, WebSocket, HTTP response body).

    Exclusion: test files (path contains 'test') — Mock StepOutput in tests
    may use stream= for test purposes.
    """
    violations: List[Violation] = []

    adapters_dir = root / "core" / "adapters"
    if not adapters_dir.is_dir():
        return violations

    for py_file in adapters_dir.glob("**/*.py"):
        rel = str(py_file.relative_to(root))

        if "test" in rel.lower():
            continue

        tree = _parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_stepoutput_call(node):
                stream_arg = _get_stream_keyword(node)
                if stream_arg is None:
                    continue
                if _is_none(stream_arg.value):
                    continue

                violations.append(Violation(
                    rule_id="internal-stream-001",
                    severity=Severity.ERROR,
                    message=(
                        "Non-generator code sets StepOutput.stream (UserFacing). "
                        "Use StepOutput.internal_stream for internal data passing. "
                        "Only generator steps may expose UserFacing streams. "
                        "See: phase_09_multi_engine_architecture_vision.yaml"
                    ),
                    file=rel,
                    line=node.lineno,
                    snippet=_node_source(node, py_file),
                ))

    return violations


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _is_stepoutput_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "StepOutput"
    return False


def _get_stream_keyword(node: ast.Call) -> ast.keyword | None:
    for kw in node.keywords:
        if kw.arg == "stream":
            return kw
    return None


def _is_none(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
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
