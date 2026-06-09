"""V7.1 ErrorMapper — translate physical failure into semantic constraint.

Defensive Axiom A (Assertion over Introspection):
  Prefers assertion diff (deterministic) over traceback introspection (fragile).
  Falls back to last-2-lines + original code when test_cases are absent.

Reset map ψ⁻¹: Q → S — physical failure → constraint embedding for Planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.execution.sandbox import ExecutionResult, PhysicalState


@dataclass
class ErrorMapping:
    """Structured crime scene for Planning consumption."""
    error_type: str                        # e.g. "SyntaxError", "AssertionDiff"
    location: str                          # e.g. "line 5" or "test_case[1]"
    constraint_violated: str               # e.g. "k >= len(arr)" or "missing colon"
    fix_hint: str                          # human+LLM-readable fix suggestion
    raw_context: str = ""                  # original code + traceback (fallback only)


class ErrorMapper:
    """Translate ExecutionResult → ErrorMapping for Planning constraint injection.

    Usage:
        mapper = ErrorMapper()
        result = executor.run(code, test_cases)
        if result.state != PhysicalState.PASS:
            mapping = mapper.map(result, code)
            # Inject mapping.fix_hint into Planning prompt
    """

    # ── V7.2: ⊢ delimited assertion extraction (Patch D) ─────────────

    @staticmethod
    def _extract_from_assertion(error_message: str) -> tuple[str, str] | None:
        """Extract (expected, actual) from ⊢-delimited assertion error.

        f-string format: f\"⊢EXPECTED⊢{expected}⊢ACTUAL⊢{actual}\"
        Returns None if the message doesn't match the format.
        """
        import re
        match = re.search(r"⊢EXPECTED⊢(.*)⊢ACTUAL⊢(.*)", error_message)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return None

    # ── Public API ──────────────────────────────────────────────────

    def map(self, result: ExecutionResult, original_code: str = "",
            test_cases: list[dict] | None = None) -> ErrorMapping:
        """Translate a physical failure into an ErrorMapping.

        Prefers assertion diff when test_cases are present.
        Falls back to traceback extraction when test_cases are absent.
        """
        if result.state == PhysicalState.PASS:
            return ErrorMapping(
                error_type="None",
                location="",
                constraint_violated="",
                fix_hint="",
            )

        # V7.2 Preferred path: ⊢ delimiters regex extraction (Patch D, zero LLM)
        if result.error_message:
            extracted = self._extract_from_assertion(result.error_message)
            if extracted:
                expected, actual = extracted
                return ErrorMapping(
                    error_type="AssertionDiff",
                    location="assertion",
                    constraint_violated=f"expected={expected}, got={actual}",
                    fix_hint=self._generate_fix_hint(expected, actual),
                    raw_context=f"Expected: {expected}\nGot: {actual}",
                )

        # Preferred path: assertion diff from test_cases (Defensive Axiom A)
        if result.test_results:
            mapping = self._from_assertion_diff(result)
            if mapping:
                mapping.raw_context = self._fallback_context(result, original_code)
                return mapping

        # Fallback: traceback (last 2 lines + original code)
        return self._from_traceback_fallback(result, original_code)

    def format_for_planning(self, mapping: ErrorMapping) -> str:
        """Format ErrorMapping as a Planning prompt constraint."""
        if not mapping.error_type or mapping.error_type == "None":
            return ""
        return (
            f"\n[PHYSICAL CONSTRAINT] Previous attempt failed:\n"
            f"  Error: {mapping.error_type} at {mapping.location}\n"
            f"  Constraint violated: {mapping.constraint_violated}\n"
            f"  Fix: {mapping.fix_hint}\n"
        )

    # ── Assertion diff path ─────────────────────────────────────────

    def _from_assertion_diff(self, result: ExecutionResult) -> ErrorMapping | None:
        """Build ErrorMapping from test case assertion diffs."""
        failed = [t for t in result.test_results if not t.get("passed", False)]
        if not failed:
            return None

        # Use the first failure for the mapping
        f0 = failed[0]
        idx = f0.get("index", 0)
        expected = f0.get("expected")
        got = f0.get("got")

        return ErrorMapping(
            error_type="AssertionDiff",
            location=f"test_case[{idx}]",
            constraint_violated=f"expected={expected}, got={got}",
            fix_hint=self._generate_fix_hint(expected, got),
        )

    # ── Traceback fallback ──────────────────────────────────────────

    def _from_traceback_fallback(
        self, result: ExecutionResult, original_code: str,
    ) -> ErrorMapping:
        """Fallback: extract last 2 traceback lines + original code."""
        tb_lines = result.error_message.split("\n") if result.error_message else []
        last_lines = tb_lines[-2:] if len(tb_lines) >= 2 else tb_lines

        error_type = result.state.value
        location = f"line {result.error_line}" if result.error_line else "unknown"
        constraint = last_lines[-1] if last_lines else result.error_message[:200]

        return ErrorMapping(
            error_type=error_type,
            location=location,
            constraint_violated=constraint[:200],
            fix_hint=self._fix_hint_from_error(result.state, constraint),
            raw_context=self._fallback_context(result, original_code),
        )

    def _fallback_context(self, result: ExecutionResult,
                          original_code: str) -> str:
        """Minimal context: original code + last 2 traceback lines."""
        tb_tail = ""
        if result.error_message:
            lines = result.error_message.split("\n")
            tb_tail = "\n".join(lines[-3:]) if len(lines) >= 3 else result.error_message
        return f"Code:\n{original_code[:500]}\n\nTraceback:\n{tb_tail[:300]}"

    # ── Fix hint generation ─────────────────────────────────────────

    @staticmethod
    def _generate_fix_hint(expected, got) -> str:
        """Generate fix hint from assertion diff."""
        got_str = str(got)
        if "SyntaxError" in got_str:
            return "Fix syntax error — check for missing colons, unmatched brackets, or indentation errors."
        if "IndexError" in got_str or "index out of range" in got_str:
            return "Add bounds check: ensure index < len(sequence) before accessing."
        if "KeyError" in got_str:
            return "Check that the key exists before accessing the dictionary."
        if "TypeError" in got_str:
            return "Check argument types — may be passing wrong type to a function."
        if "AttributeError" in got_str:
            return "Check method/attribute name spelling — the object may not have this member."
        if "NameError" in got_str:
            return "Variable or function not defined — check for typos or missing imports."
        return f"Test expected {expected} but got {got_str[:100]}. Review the logic."

    @staticmethod
    def _fix_hint_from_error(state: PhysicalState, detail: str) -> str:
        """Generate fix hint from physical state type."""
        if state == PhysicalState.COMPILE_ERR:
            return f"Fix syntax error: {detail[:150]}"
        if state == PhysicalState.RUNTIME_ERR:
            return f"Fix runtime error: {detail[:150]}"
        if state == PhysicalState.TYPE_MISMATCH:
            return f"Fix type mismatch: {detail[:150]}"
        if state == PhysicalState.TIMEOUT:
            return "Execution timed out — may contain infinite loop. Add termination condition."
        if state == PhysicalState.SANDBOX_VIOLATION:
            return "Code attempted restricted operation. Rewrite using only safe builtins."
        return f"Fix physical error: {detail[:150]}"
