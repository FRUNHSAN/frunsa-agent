"""GuardrailChecker: runs all architectural rules and produces a CheckReport."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

from guardrails.report import CheckReport, Severity, Violation
from guardrails.rules import (
    component_registration_coverage,
    cross_platform_imports,
    frozen_dataclass_integrity,
    reasoning_chain_coverage,
)


class GuardrailChecker:
    """Runs all registered architectural rules against the project root."""

    def __init__(self, root: Path | None = None, min_severity: Severity = Severity.ERROR) -> None:
        self.root = Path(root) if root else self._find_root()
        self.min_severity = min_severity
        self._rules: Dict[str, Callable] = {
            "cross-platform-imports": cross_platform_imports,
            "frozen-dataclass-integrity": frozen_dataclass_integrity,
            "component-registration-coverage": component_registration_coverage,
            "reasoning-chain-coverage": reasoning_chain_coverage,
        }

    @staticmethod
    def _find_root() -> Path:
        """Find project root by looking for .ai_reasoning/ or .git/."""
        current = Path.cwd()
        for ancestor in [current, *current.parents]:
            if (ancestor / ".ai_reasoning").is_dir() or (ancestor / ".git").is_dir():
                return ancestor
        return current

    def run(self, rule_ids: List[str] | None = None) -> CheckReport:
        """Run all rules (or a subset) and return a CheckReport."""
        report = CheckReport()

        rules_to_run = {
            rid: fn for rid, fn in self._rules.items()
            if rule_ids is None or rid in rule_ids
        }

        # Count scannable files once
        core_dir = self.root / "core"
        py_files = list(core_dir.glob("**/*.py")) if core_dir.is_dir() else []
        report.files_scanned = len(py_files)
        report.rules_run = len(rules_to_run)

        for rule_id, rule_fn in rules_to_run.items():
            try:
                violations = rule_fn(self.root)
                # Filter by severity threshold
                for v in violations:
                    if self._severity_passes(v.severity):
                        report.violations.append(v)
            except Exception as exc:
                report.violations.append(Violation(
                    rule_id=rule_id,
                    severity=Severity.ERROR,
                    message=f"Rule crashed: {exc}",
                ))

        return report

    def _severity_passes(self, severity: Severity) -> bool:
        order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        return order.get(severity, 2) <= order.get(self.min_severity, 0)
