"""Rule: UserFacingStream isolation.

Only component_type="generator" steps may set StepOutput.stream (UserFacing).
All other steps MUST use StepOutput.internal_stream for data passing.

Reference: .ai_reasoning/chains/phase_08_dag_streaming_semantics.yaml
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation

# Files that are allowed to set StepOutput.stream (UserFacing)
_ALLOWED_USER_FACING_FILES = {
    "generator.py",      # Generator step is the ONLY legitimate source
}


def user_facing_stream_isolation(root: Path) -> List[Violation]:
    """Enforce: only generator steps may set StepOutput.stream.

    Scans core/steps/ and core/adapters/ for StepOutput() calls
    where stream=<non-None value>. Excludes generator.py and test files.
    """
    violations: List[Violation] = []

    for search_dir_name in ("steps", "adapters"):
        search_dir = root / "core" / search_dir_name
        if not search_dir.is_dir():
            continue

        for py_file in search_dir.glob("*.py"):
            rel = str(py_file.relative_to(root))

            # Skip allowed files
            if py_file.name in _ALLOWED_USER_FACING_FILES:
                continue
            # Skip test files
            if "test" in rel.lower():
                continue

            tree = _parse(py_file)
            if tree is None:
                continue

            # Find StepOutput() calls with stream=<non-None>
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _is_stepoutput_call(node):
                    stream_arg = _get_stream_keyword(node)
                    if stream_arg is None:
                        continue  # No stream= kwarg — OK
                    if _is_none(stream_arg.value):
                        continue  # stream=None — OK

                    violations.append(Violation(
                        rule_id="stream-isolation-001",
                        severity=Severity.ERROR,
                        message=(
                            f"Non-generator step sets StepOutput.stream (UserFacing). "
                            f"Use StepOutput.internal_stream for internal data passing. "
                            f"Only generator steps may expose UserFacing streams. "
                            f"See: phase_08_dag_streaming_semantics.yaml"
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
    """Check if the call is StepOutput(...)."""
    if isinstance(node.func, ast.Name):
        return node.func.id == "StepOutput"
    return False


def _get_stream_keyword(node: ast.Call) -> ast.keyword | None:
    """Return the stream= keyword if present, else None."""
    for kw in node.keywords:
        if kw.arg == "stream":
            return kw
    return None


def _is_none(node: ast.expr) -> bool:
    """Check if an AST node represents None."""
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
