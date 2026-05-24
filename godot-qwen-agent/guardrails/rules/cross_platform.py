"""Rule 1: Cross-platform import guard.

core/pipeline/ MUST NOT import domain types (Chunk, ContentBlock, RetrievalResult).
core/contracts/ MUST NOT import orchestration types (PipelineRunner, StepConfig, PipelineConfig, ResourceContainer).
Shared infrastructure types (SemVer, HealthStatus) are legitimate wiring.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from guardrails.report import Severity, Violation

DOMAIN_TYPES = {
    "Chunk", "ContentBlock", "RetrievalResult",
    "ChunkingStrategy", "RetrievalStrategy", "GenerationResult",
    "GenerationStrategy", "ScoringStrategy",
}

ORCHESTRATION_TYPES = {
    "PipelineRunner", "StepConfig", "PipelineConfig",
    "ResourceContainer", "StepOutput", "PipelineStep",
}


def cross_platform_imports(root: Path) -> List[Violation]:
    violations: List[Violation] = []

    # Check pipeline/ → contracts/ imports
    pipeline_dir = root / "core" / "pipeline"
    if pipeline_dir.is_dir():
        for py_file in pipeline_dir.glob("*.py"):
            tree = _parse(py_file)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "core.contracts" in node.module:
                        imported = {alias.name for alias in node.names}
                        domain_imports = imported & DOMAIN_TYPES
                        if domain_imports:
                            violations.append(Violation(
                                rule_id="cross-platform-001",
                                severity=Severity.ERROR,
                                message=f"pipeline imports domain types: {sorted(domain_imports)}",
                                file=str(py_file.relative_to(root)),
                                line=node.lineno,
                                snippet=_node_source(node, py_file),
                            ))

    # Check contracts/ → pipeline/ imports
    contracts_dir = root / "core" / "contracts"
    if contracts_dir.is_dir():
        for py_file in contracts_dir.glob("*.py"):
            tree = _parse(py_file)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "core.pipeline" in node.module:
                        imported = {alias.name for alias in node.names}
                        orch_imports = imported & ORCHESTRATION_TYPES
                        if orch_imports:
                            violations.append(Violation(
                                rule_id="cross-platform-002",
                                severity=Severity.ERROR,
                                message=f"contracts imports orchestration types: {sorted(orch_imports)}",
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


def _node_source(node: ast.AST, file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if hasattr(node, "lineno") and node.lineno <= len(lines):
            return lines[node.lineno - 1].strip()
    except Exception:
        pass
    return ""
