"""Rule 4: Reasoning chain coverage.

Core modules (contracts/, adapters/) must be referenced by at least one
reasoning chain. This prevents "orphan modules" that evolved without
architectural documentation.

For pre-commit: checks staged files against chain references.
For full scan: reports modules with zero chain coverage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Set

from guardrails.report import Severity, Violation


# Modules that don't need individual chain coverage (infrastructure)
EXEMPT_MODULES = {"__init__", "registry", "chunking", "retrieval"}


def reasoning_chain_coverage(root: Path) -> List[Violation]:
    violations: List[Violation] = []

    chains_dir = root / ".ai_reasoning" / "chains"
    if not chains_dir.is_dir():
        return [Violation(
            rule_id="chain-cov-001",
            severity=Severity.WARNING,
            message="No .ai_reasoning/chains/ directory found",
        )]

    # Collect all text from all chains
    chain_texts: Dict[str, str] = {}
    for chain_file in chains_dir.glob("*.yaml"):
        try:
            chain_texts[chain_file.stem] = chain_file.read_text(encoding="utf-8")
        except Exception:
            pass

    if not chain_texts:
        return violations

    # Check core/contracts/ modules
    contracts_dir = root / "core" / "contracts"
    if contracts_dir.is_dir():
        for py_file in sorted(contracts_dir.glob("*.py")):
            stem = py_file.stem
            if stem in EXEMPT_MODULES:
                continue
            if not _is_referenced_in_chains(stem, chain_texts):
                violations.append(Violation(
                    rule_id="chain-cov-002",
                    severity=Severity.WARNING,
                    message=f"Module 'core/contracts/{py_file.name}' has no reasoning chain reference — consider documenting its architectural decisions",
                    file=str(py_file.relative_to(root)),
                ))

    # Check core/adapters/ modules
    adapters_dir = root / "core" / "adapters"
    if adapters_dir.is_dir():
        for py_file in sorted(adapters_dir.glob("*.py")):
            stem = py_file.stem
            if stem in EXEMPT_MODULES:
                continue
            if not _is_referenced_in_chains(stem, chain_texts):
                violations.append(Violation(
                    rule_id="chain-cov-003",
                    severity=Severity.WARNING,
                    message=f"Module 'core/adapters/{py_file.name}' has no reasoning chain reference — consider documenting its architectural decisions",
                    file=str(py_file.relative_to(root)),
                ))

    # Staged file check: if we're in a git repo, check staged new files
    violations.extend(_check_staged_new_files(root, chain_texts))

    return violations


def _is_referenced_in_chains(module_stem: str, chain_texts: Dict[str, str]) -> bool:
    """Check if module stem appears in any chain text."""
    for chain_text in chain_texts.values():
        if module_stem in chain_text:
            return True
    return False


def _check_staged_new_files(root: Path, chain_texts: Dict[str, str]) -> List[Violation]:
    """Check git staged files — new core files must have chain references."""
    import subprocess
    violations: List[Violation] = []

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
            capture_output=True, text=True, cwd=str(root),
            timeout=5,
        )
        if result.returncode != 0:
            return violations

        new_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
        core_patterns = ("core/contracts/", "core/adapters/")

        for f in new_files:
            if not f.endswith(".py"):
                continue
            if f.endswith("__init__.py"):
                continue
            if not any(f.startswith(p) for p in core_patterns):
                continue

            stem = Path(f).stem
            if stem in EXEMPT_MODULES:
                continue

            if not _is_referenced_in_chains(stem, chain_texts):
                violations.append(Violation(
                    rule_id="chain-cov-004",
                    severity=Severity.ERROR,
                    message=(
                        f"NEW staged file '{f}' has NO reasoning chain reference. "
                        f"Per AI Collaboration Protocol, new core modules require a chain entry."
                    ),
                    file=f,
                ))

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return violations
