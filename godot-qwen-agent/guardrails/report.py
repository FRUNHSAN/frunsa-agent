"""Violation report model for guardrails checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Severity(str, Enum):
    ERROR = "error"       # Blocks commit — invariant violation
    WARNING = "warning"   # Advisory — should be fixed but doesn't block
    INFO = "info"         # Informational only


@dataclass
class Violation:
    rule_id: str
    severity: Severity
    message: str
    file: str = ""
    line: int = 0
    snippet: str = ""


@dataclass
class CheckReport:
    violations: List[Violation] = field(default_factory=list)
    files_scanned: int = 0
    rules_run: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def format_terminal(self) -> str:
        if not self.violations:
            return (
                f"Guardrails: PASSED "
                f"({self.files_scanned} files, {self.rules_run} rules)"
            )

        lines = [
            f"Guardrails: {self.error_count} error(s), {self.warning_count} warning(s) "
            f"({self.files_scanned} files, {self.rules_run} rules)",
            "─" * 60,
        ]
        for v in self.violations:
            prefix = "ERROR" if v.severity == Severity.ERROR else "WARN"
            loc = f"{v.file}:{v.line}" if v.file else "<project>"
            lines.append(f"  [{prefix}] {loc} — {v.message}")
            if v.snippet:
                lines.append(f"         {v.snippet.strip()[:120]}")
        lines.append("─" * 60)

        if self.error_count > 0:
            lines.append(
                "Commit BLOCKED. Fix errors above or run with --severity warning to bypass."
            )
        return "\n".join(lines)
