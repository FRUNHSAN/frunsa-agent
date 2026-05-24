"""CLI entry point for guardrails — usable as pre-commit hook or standalone.

Usage:
  python -m guardrails check              # Run all rules (default: error level)
  python -m guardrails check --all        # Include warnings
  python -m guardrails check --rule cross-platform-imports
  python -m guardrails list-rules         # Show available rules
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from guardrails.checker import GuardrailChecker
from guardrails.report import Severity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="guardrails",
        description="AST-based architectural invariant enforcement for godot-qwen-agent",
    )
    sub = parser.add_subparsers(dest="command")

    # check
    check_parser = sub.add_parser("check", help="Run architectural rules")
    check_parser.add_argument(
        "--all", action="store_true",
        help="Report warnings in addition to errors"
    )
    check_parser.add_argument(
        "--severity", choices=["error", "warning", "info"], default="error",
        help="Minimum severity to report (default: error)"
    )
    check_parser.add_argument(
        "--rule", action="append", dest="rules",
        help="Run only this rule (repeatable)"
    )
    check_parser.add_argument(
        "--root", type=Path, default=None,
        help="Project root path (auto-detected if omitted)"
    )
    check_parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of terminal format"
    )

    # list-rules
    sub.add_parser("list-rules", help="Show available rules")

    args = parser.parse_args(argv)

    if args.command == "list-rules":
        checker = GuardrailChecker()
        print("Available rules:")
        for rid in checker._rules:
            print(f"  {rid}")
        return 0

    if args.command == "check":
        severity = getattr(Severity, args.severity.upper())
        if args.all:
            severity = Severity.WARNING

        checker = GuardrailChecker(
            root=args.root,
            min_severity=severity,
        )
        report = checker.run(rule_ids=args.rules)

        if args.json:
            import json
            result = {
                "passed": report.passed,
                "error_count": report.error_count,
                "warning_count": report.warning_count,
                "files_scanned": report.files_scanned,
                "rules_run": report.rules_run,
                "violations": [
                    {
                        "rule_id": v.rule_id,
                        "severity": v.severity.value,
                        "message": v.message,
                        "file": v.file,
                        "line": v.line,
                    }
                    for v in report.violations
                ],
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(report.format_terminal())

        return 0 if report.passed else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
