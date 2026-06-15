"""Guardrails: AST-based architectural invariant enforcement.

Phase 8.0 — machine-enforced architectural rules.
Runs as pre-commit hook, CI step, or pytest plugin.
"""

from guardrails.report import Violation, Severity
from guardrails.checker import GuardrailChecker

__all__ = ["Violation", "Severity", "GuardrailChecker"]
