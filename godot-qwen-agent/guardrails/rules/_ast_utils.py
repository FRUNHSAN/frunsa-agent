"""Shared AST utilities for guardrail rules (Phase 14).

Extracted from component_trace_completeness.py so that
orchestration_trace_completeness can reuse the same AST-scanning
logic without duplication.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Set


def collect_trace_keys_from_engine(engine_dir: Path) -> Set[str]:
    """AST-scan an engine directory for all static trace_context dict keys.

    Args:
        engine_dir: Path to the engine directory
            (e.g., Path("engines/orchestration/"))

    Returns:
        Set of dotted key name strings found in trace_context dict
        literals (e.g., {"orchestration.dag_node_id", "retrieval.chunk_id"})

    Excludes:
        - Files with "test" in the path (case-insensitive)
        - Files named "interface.py" (Protocol definitions)
        - Files with SyntaxError (silently skipped)
    """
    keys: Set[str] = set()

    for py_file in sorted(engine_dir.glob("**/*.py")):
        rel = str(py_file)
        if "test" in rel.lower():
            continue
        if py_file.name == "interface.py":
            continue

        tree = _parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in getattr(node, "keywords", []):
                    if kw.arg == "trace_context" and isinstance(kw.value, ast.Dict):
                        for key_node in kw.value.keys:
                            if key_node is None:
                                continue
                            if isinstance(key_node, ast.Constant) and isinstance(
                                key_node.value, str
                            ):
                                keys.add(key_node.value)

    return keys


def _parse(path: Path) -> ast.AST | None:
    """Parse a Python file, returning None on SyntaxError."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
