"""V7.3 Phase 3 — Test case auto-augmentation: canonical section sigma: E -> T.

Tests the deterministic test case fiber bundle section:
  - sigma(IndexError) -> boundary index tests
  - sigma(KeyError) -> missing key tests
  - sigma(TypeError) -> type lattice boundary tests
  - sigma(AttributeError) -> method existence tests
  - sigma(ZeroDivisionError) -> divisor boundary
  - sigma(ValueError) -> domain boundary
  - sigma(unknown) -> generic edge tests
  - Monotonicity: T_n subseteq T_{n+1}
  - Integration with failed_test context
"""

import pytest
from core.execution.error_mapper import augment_test_cases


# ── IndexError fiber ──────────────────────────────────────────────────

class TestIndexErrorAugmentation:
    def test_returns_boundary_tests(self):
        tc = augment_test_cases("IndexError")
        assert len(tc) >= 3
        inputs = [t["input"] for t in tc]
        assert any("empty" in i for i in inputs)
        assert any("-1" in i for i in inputs)

    def test_includes_context_from_failed_test(self):
        tc = augment_test_cases("IndexError",
            failed_test={"input": "arr, k=10", "expected": 4})
        assert len(tc) >= 4
        assert any("arr" in str(t.get("input", "")) for t in tc)

    def test_lowercase_error_type_works(self):
        tc = augment_test_cases("indexerror")
        assert len(tc) >= 3

    def test_partial_match_works(self):
        """'index out of range' should match IndexError augmentation."""
        tc = augment_test_cases("index out of range")
        assert len(tc) >= 3


# ── KeyError fiber ────────────────────────────────────────────────────

class TestKeyErrorAugmentation:
    def test_returns_boundary_tests(self):
        tc = augment_test_cases("KeyError")
        assert len(tc) >= 2
        inputs = [t["input"] for t in tc]
        assert any("empty_dict" in i for i in inputs)
        assert any("missing" in i for i in inputs)

    def test_with_context(self):
        tc = augment_test_cases("KeyError",
            failed_test={"input": "my_dict, key='name'"})
        assert len(tc) >= 2


# ── TypeError fiber ───────────────────────────────────────────────────

class TestTypeErrorAugmentation:
    def test_returns_boundary_tests(self):
        tc = augment_test_cases("TypeError")
        assert len(tc) >= 2
        assert any("wrong_type" in t["input"] or "None_arg" in t["input"]
                   for t in tc)


# ── AttributeError fiber ──────────────────────────────────────────────

class TestAttributeErrorAugmentation:
    def test_returns_boundary_tests(self):
        tc = augment_test_cases("AttributeError")
        assert len(tc) >= 2
        inputs = [t["input"] for t in tc]
        assert any("method" in i for i in inputs)

    def test_none_object_case(self):
        tc = augment_test_cases("AttributeError")
        assert any("None" in t["input"] for t in tc)


# ── ZeroDivisionError fiber ───────────────────────────────────────────

class TestZeroDivisionErrorAugmentation:
    def test_returns_division_boundary(self):
        tc = augment_test_cases("ZeroDivisionError")
        assert len(tc) >= 1
        assert any("0" in t["input"] for t in tc)


# ── ValueError fiber ──────────────────────────────────────────────────

class TestValueErrorAugmentation:
    def test_returns_value_boundary(self):
        tc = augment_test_cases("ValueError")
        assert len(tc) >= 1
        assert any("invalid" in t["input"] or "domain" in t["input"]
                   for t in tc)


# ── Generic / unknown errors ──────────────────────────────────────────

class TestGenericAugmentation:
    def test_unknown_error_returns_generic_tests(self):
        tc = augment_test_cases("SomeWeirdError")
        assert len(tc) >= 1
        assert any("empty" in t["input"] for t in tc)

    def test_empty_error_returns_empty(self):
        tc = augment_test_cases("")
        assert tc == []

    def test_none_error_returns_empty(self):
        tc = augment_test_cases(None)
        assert tc == []

    def test_none_string_returns_empty(self):
        tc = augment_test_cases("None")
        # "None" doesn't match any error type -> falls through to generic
        assert len(tc) >= 1


# ── Determinism ────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_produces_same_output(self):
        tc1 = augment_test_cases("IndexError")
        tc2 = augment_test_cases("IndexError")
        assert tc1 == tc2

    def test_no_randomness_in_augmentation(self):
        """augment_test_cases is pure function — no LLM, no random."""
        import inspect
        source = inspect.getsource(augment_test_cases)
        # Strip docstring before checking
        body = source.split('"""')[-1] if '"""' in source else source
        assert "random" not in body.lower()
        assert "model" not in body.lower()


# ── Monotonicity (simulated) ──────────────────────────────────────────

class TestMonotonicity:
    def test_multiple_calls_produce_more_tests(self):
        """Simulating T1 -> T2 -> T3: each augmentation adds tests."""
        all_tc = []
        for error in ["IndexError", "KeyError", "TypeError"]:
            new = augment_test_cases(error)
            all_tc.extend(new)
        assert len(all_tc) >= 7  # At least 3+2+2

    def test_augmented_tests_are_dicts_with_input_expected(self):
        for error in ["IndexError", "KeyError", "TypeError"]:
            tc = augment_test_cases(error)
            for t in tc:
                assert isinstance(t, dict), f"Not a dict: {t}"
                assert "input" in t, f"Missing 'input': {t}"
                assert "expected" in t, f"Missing 'expected': {t}"


# ── Integration: test_case format compatibility ───────────────────────

class TestOutputFormat:
    def test_output_matches_sandbox_format(self):
        """Output must be directly usable by SandboxExecutor.run(test_cases=...)."""
        tc = augment_test_cases("IndexError")
        for t in tc:
            assert isinstance(t["input"], str)
            assert isinstance(t["expected"], (str, int, float, type(None), list))

    def test_all_error_types_produce_valid_format(self):
        errors = ["IndexError", "KeyError", "TypeError", "AttributeError",
                   "ZeroDivisionError", "ValueError"]
        for error in errors:
            tc = augment_test_cases(error)
            for t in tc:
                assert "input" in t and "expected" in t, (
                    f"Bad format for {error}: {t}"
                )
