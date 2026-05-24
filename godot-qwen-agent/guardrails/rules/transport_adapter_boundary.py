"""Rule: transport_adapter_boundary — cloud-native transport libs confined to adapters/.

Enforces that transport-specific libraries (grpc, redis, kafka, etc.) are only
imported within core/adapters/, never in core/pipeline/ or core/contracts/.

Extends the cross-platform import pattern (cross_platform.py) to cloud-native libraries.
Behavior-based naming: describes WHAT boundary is enforced, not WHAT DOMAIN.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

from guardrails.report import Severity, Violation

_TRANSPORT_MODULES: Set[str] = {
    "grpc",
    "grpclib",
    "redis",
    "aioredis",
    "kafka",
    "aiokafka",
    "nats",
    "pulsar",
    "aio_pika",
    "amqp",
}

# Sub-paths where transport imports are allowed
_ALLOWED_PREFIXES = ("core/adapters/",)


def transport_adapter_boundary(root: Path) -> List[Violation]:
    """Enforce: transport libraries only imported within core/adapters/.

    Scans all core/ Python files for imports of transport-specific modules.
    Raises ERROR if found outside core/adapters/.
    """
    violations: List[Violation] = []

    core_dir = root / "core"
    if not core_dir.is_dir():
        return violations

    for py_file in core_dir.glob("**/*.py"):
        rel = str(py_file.relative_to(root))

        # Allowed: only files within core/adapters/
        allowed = any(rel.startswith(prefix) for prefix in _ALLOWED_PREFIXES)
        if allowed:
            continue

        # Skip test files
        if "test" in rel.lower():
            continue

        tree = _parse(py_file)
        if tree is None:
            continue

        for node in ast.walk(tree):
            # Check Import nodes: import grpc, import redis, etc.
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base_module = alias.name.split(".")[0]
                    if base_module in _TRANSPORT_MODULES:
                        violations.append(Violation(
                            rule_id="transport-boundary-001",
                            severity=Severity.ERROR,
                            message=(
                                f"Transport library '{alias.name}' imported in {rel}. "
                                f"Cloud-native transport libraries may only be used "
                                f"within core/adapters/. The engine core and contracts "
                                f"layer must remain transport-agnostic. "
                                f"See: phase_09_multi_engine_architecture_vision.yaml"
                            ),
                            file=rel,
                            line=node.lineno,
                            snippet=_node_source(node, py_file),
                        ))

            # Check ImportFrom nodes: from grpc import ..., from redis import ...
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                base_module = node.module.split(".")[0]
                if base_module in _TRANSPORT_MODULES:
                    violations.append(Violation(
                        rule_id="transport-boundary-001",
                        severity=Severity.ERROR,
                        message=(
                            f"Transport library '{node.module}' imported in {rel}. "
                            f"Cloud-native transport libraries may only be used "
                            f"within core/adapters/. The engine core and contracts "
                            f"layer must remain transport-agnostic. "
                            f"See: phase_09_multi_engine_architecture_vision.yaml"
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


def _node_source(node: ast.AST, file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if hasattr(node, "lineno") and node.lineno <= len(lines):
            return lines[node.lineno - 1].strip()
    except Exception:
        pass
    return ""
