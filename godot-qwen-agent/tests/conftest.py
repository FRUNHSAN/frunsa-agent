"""Pytest configuration for the agent platform test suite.

Phase 8.0: --guardrails flag runs architectural invariant checks at session start.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def common_initial_keys() -> set[str]:
    return {"document"}


# ── Guardrails integration (Phase 8.0) ───────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--guardrails",
        action="store_true",
        default=False,
        help="Run architectural invariant checks before test suite",
    )
    parser.addoption(
        "--guardrails-severity",
        choices=["error", "warning", "info"],
        default="error",
        help="Minimum severity for guardrails (default: error)",
    )


@pytest.fixture(scope="session", autouse=True)
def _guardrails_session_check(request):
    """Run guardrails once at session start when --guardrails is set."""
    if not request.config.getoption("--guardrails"):
        return

    from guardrails.checker import GuardrailChecker
    from guardrails.report import Severity

    severity_name = request.config.getoption("--guardrails-severity", "error")
    severity = getattr(Severity, severity_name.upper(), Severity.ERROR)

    root = Path.cwd()
    for ancestor in [root, *root.parents]:
        if (ancestor / ".ai_reasoning").is_dir():
            root = ancestor
            break

    checker = GuardrailChecker(root=root, min_severity=severity)
    report = checker.run()

    if not report.passed:
        pytest.fail(f"\n{report.format_terminal()}", pytrace=False)
