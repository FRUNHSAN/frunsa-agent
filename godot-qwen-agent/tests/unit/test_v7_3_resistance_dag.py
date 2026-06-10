"""V7.3 Phase 2 — Resistance-field DAG: causality-preserving stable sort.

Tests the sheaf R on DAG G = (V, E):
  - RESISTANCE_WEIGHTS dictionary completeness
  - _resistance_weight() lookup with graceful degradation
  - Causality preservation (writes keep original order)
  - Resistance sort within reads (gradient descent on potential w)
  - Cross-level dependency precedence over resistance sort
  - Edge cases: empty steps, single step, all reads, all writes
  - X-Ray telemetry annotations
"""

import pytest
from core.track_c import (
    _build_dag_and_depth,
    RESISTANCE_WEIGHTS,
    _resistance_weight,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def rw():
    return RESISTANCE_WEIGHTS


# ── RESISTANCE_WEIGHTS completeness ───────────────────────────────────

class TestResistanceWeights:
    def test_empty_tool_is_zero(self):
        assert RESISTANCE_WEIGHTS[""] == 0.0

    def test_search_web_is_low(self):
        assert RESISTANCE_WEIGHTS["search_web"] == 0.1

    def test_rag_search_is_low(self):
        assert RESISTANCE_WEIGHTS["rag_search"] == 0.1

    def test_sandbox_python_is_low(self):
        assert RESISTANCE_WEIGHTS["sandbox_python"] == 2.0

    def test_filesystem_read_is_medium(self):
        assert RESISTANCE_WEIGHTS["mcp__filesystem_read"] == 5.0

    def test_filesystem_write_is_high(self):
        assert RESISTANCE_WEIGHTS["mcp__filesystem_write"] == 50.0

    def test_filesystem_delete_is_extreme(self):
        assert RESISTANCE_WEIGHTS["mcp__filesystem_delete"] == 100.0

    def test_database_query_is_medium(self):
        assert RESISTANCE_WEIGHTS["mcp__database_query"] == 30.0

    def test_database_write_is_extreme(self):
        assert RESISTANCE_WEIGHTS["mcp__database_write"] == 100.0

    def test_weights_are_monotone_by_risk(self):
        """Read < Sandbox < Query < Write < Delete (rough ordering)."""
        assert RESISTANCE_WEIGHTS["mcp__filesystem_read"] < RESISTANCE_WEIGHTS["mcp__filesystem_write"]
        assert RESISTANCE_WEIGHTS["mcp__filesystem_write"] <= RESISTANCE_WEIGHTS["mcp__filesystem_delete"]
        assert RESISTANCE_WEIGHTS["mcp__database_query"] < RESISTANCE_WEIGHTS["mcp__database_write"]

    def test_all_physical_tools_have_weights(self):
        """Every tool in PHYSICAL_TOOLS should have a RESISTANCE_WEIGHT."""
        from core.execution.tool_verifier import PHYSICAL_TOOLS
        for tool_name in PHYSICAL_TOOLS:
            assert tool_name in RESISTANCE_WEIGHTS, (
                f"Tool '{tool_name}' missing from RESISTANCE_WEIGHTS"
            )


class TestResistanceWeightLookup:
    def test_known_tool_returns_weight(self):
        assert _resistance_weight("mcp__filesystem_write") == 50.0

    def test_unknown_tool_returns_zero(self):
        assert _resistance_weight("nonexistent_tool") == 0.0

    def test_empty_tool_returns_zero(self):
        assert _resistance_weight("") == 0.0

    def test_none_tool_returns_zero(self):
        assert _resistance_weight(None) == 0.0


# ── Resistance stable sort ─────────────────────────────────────────────

class TestResistanceStableSort:
    """Red-Team #3: reads sorted by resistance, writes preserve original order."""

    def test_reads_sorted_by_resistance_ascending(self, rw):
        steps = [
            {"prompt": "fetch remote", "tool": "mcp__network_fetch"},     # w=10
            {"prompt": "search web", "tool": "search_web"},               # w=0.1
            {"prompt": "read file", "tool": "mcp__filesystem_read"},      # w=5
        ]
        result, _, _, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]
        assert tools == ["search_web", "mcp__filesystem_read", "mcp__network_fetch"]

    def test_writes_preserve_original_order(self, rw):
        steps = [
            {"prompt": "write A", "tool": "mcp__filesystem_write"},       # w=50
            {"prompt": "delete B", "tool": "mcp__filesystem_delete"},     # w=100
            {"prompt": "write C", "tool": "mcp__database_write"},         # w=100
        ]
        result, _, _, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]
        # All writes -> original order preserved
        assert tools == [s["tool"] for s in steps]

    def test_reads_before_writes_causality(self, rw):
        """Red-Team #3: writes come after all reads within the same BFS level."""
        steps = [
            {"prompt": "write config", "tool": "mcp__filesystem_write"},   # w=50
            {"prompt": "search docs", "tool": "search_web"},               # w=0.1
            {"prompt": "read config", "tool": "mcp__filesystem_read"},     # w=5
        ]
        result, _, _, _ = _build_dag_and_depth(steps, rw)

        # Find last read and first write indices
        read_indices = [i for i, s in enumerate(result)
                        if not s["tool"].endswith(("_write", "_delete", "_insert", "_update"))]
        write_indices = [i for i, s in enumerate(result)
                         if s["tool"].endswith(("_write", "_delete", "_insert", "_update"))]

        if read_indices and write_indices:
            assert max(read_indices) < min(write_indices), (
                f"Reads must come before writes: reads={read_indices}, writes={write_indices}"
            )

    def test_reads_sorted_writes_preserved_combined(self, rw):
        """Full scenario: 3 reads, 2 writes — reads sorted, writes last in orig order."""
        steps = [
            {"prompt": "write B", "tool": "mcp__filesystem_write"},       # w=50, write
            {"prompt": "fetch", "tool": "mcp__network_fetch"},            # w=10, read
            {"prompt": "write A", "tool": "mcp__database_write"},         # w=100, write
            {"prompt": "search", "tool": "search_web"},                   # w=0.1, read
            {"prompt": "read file", "tool": "mcp__filesystem_read"},      # w=5, read
        ]
        result, _, _, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]

        # First 3 should be reads sorted by resistance
        read_part = [t for t in tools if not t.endswith(("_write", "_delete", "_insert", "_update"))]
        assert read_part == ["search_web", "mcp__filesystem_read", "mcp__network_fetch"]

        # Last 2 should be writes in original order
        orig_writes = [s["tool"] for s in steps
                       if s["tool"].endswith(("_write", "_delete", "_insert", "_update"))]
        result_writes = [t for t in tools
                         if t.endswith(("_write", "_delete", "_insert", "_update"))]
        assert result_writes == orig_writes


# ── Cross-level dependency precedence ──────────────────────────────────

class TestCrossLevelPrecedence:
    """Dependency structure dominates resistance sort — cross-level edges
    are never reordered by resistance weights."""

    def test_dependency_not_broken_by_resistance(self, rw):
        """Step B depends on A: A (level 0), B (level 1). Resistance must not
        move B before A even if B has lower resistance."""
        steps = [
            {"prompt": "write config", "tool": "mcp__filesystem_write",
             "produces": "config"},                                         # w=50
            {"prompt": "read config", "tool": "mcp__filesystem_read",
             "needs": "config"},                                            # w=5 (lower!)
        ]
        result, depth, _, _ = _build_dag_and_depth(steps, rw)
        # Step 1 (read) depends on step 0 (write) -> must stay after step 0
        assert depth == 1  # Serial chain
        write_idx = next(i for i, s in enumerate(result)
                         if s["tool"] == "mcp__filesystem_write")
        read_idx = next(i for i, s in enumerate(result)
                        if s["tool"] == "mcp__filesystem_read")
        assert write_idx < read_idx, (
            f"Dependency violated: write@{write_idx} must precede read@{read_idx}"
        )

    def test_independent_levels_each_sorted(self, rw):
        """Level 0 independent steps sorted, level 1 (dependent) also sorted."""
        steps = [
            {"prompt": "a_fetch", "tool": "mcp__network_fetch"},             # w=10, level 0
            {"prompt": "a_search", "tool": "search_web"},                   # w=0.1, level 0
            {"prompt": "b_read", "tool": "mcp__filesystem_read",
             "depends_on": [0]},                                            # w=5, level 1
            {"prompt": "b_write", "tool": "mcp__filesystem_write",
             "depends_on": [0]},                                            # w=50, level 1
        ]
        result, depth, _, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]
        # Level 0 sorted: search_web (0.1) then network_fetch (10)
        # Level 1 sorted: filesystem_read (5, read) then filesystem_write (50, write)
        assert depth >= 2  # Two levels exist
        # Verify search_web is before network_fetch at level 0
        assert tools.index("search_web") < tools.index("mcp__network_fetch")


# ── Max resistance ─────────────────────────────────────────────────────

class TestMaxResistance:
    def test_max_resistance_zero_for_no_tools(self):
        steps = [{"prompt": "a"}, {"prompt": "b"}]
        _, _, mr, _ = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)
        assert mr == 0.0

    def test_max_resistance_finds_highest(self, rw):
        steps = [
            {"prompt": "low", "tool": "search_web"},         # 0.1
            {"prompt": "high", "tool": "mcp__filesystem_delete"},  # 100.0
            {"prompt": "mid", "tool": "mcp__filesystem_read"},     # 5.0
        ]
        _, _, mr, _ = _build_dag_and_depth(steps, rw)
        assert mr == 100.0

    def test_max_resistance_without_weights(self):
        steps = [{"prompt": "a", "tool": "mcp__filesystem_write"}]
        _, _, mr, _ = _build_dag_and_depth(steps)  # No weights passed
        assert mr == 0.0


# ── Edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_steps(self):
        steps = []
        result, depth, mr, _ = _build_dag_and_depth(steps)
        assert result == []
        assert depth == 1
        assert mr == 0.0

    def test_single_step(self):
        steps = [{"prompt": "only step"}]
        result, depth, mr, _ = _build_dag_and_depth(steps)
        assert len(result) == 1
        assert depth == 1

    def test_single_step_with_resistance(self, rw):
        steps = [{"prompt": "only", "tool": "mcp__filesystem_delete"}]
        result, depth, mr, _ = _build_dag_and_depth(steps, rw)
        assert len(result) == 1
        assert mr == 100.0

    def test_all_reads_no_writes(self, rw):
        steps = [
            {"prompt": "a", "tool": "mcp__network_fetch"},
            {"prompt": "b", "tool": "search_web"},
        ]
        result, depth, mr, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]
        # All reads, sorted by resistance
        assert tools == ["search_web", "mcp__network_fetch"]

    def test_all_writes_no_reads(self, rw):
        steps = [
            {"prompt": "a", "tool": "mcp__filesystem_write"},
            {"prompt": "b", "tool": "mcp__database_write"},
        ]
        result, depth, mr, _ = _build_dag_and_depth(steps, rw)
        tools = [s["tool"] for s in result]
        # All writes, original order preserved
        assert tools == ["mcp__filesystem_write", "mcp__database_write"]

    def test_no_resistance_weights_does_nothing(self):
        """Without resistance_weights, sort step is skipped completely."""
        steps = [
            {"prompt": "c", "tool": "mcp__network_fetch"},
            {"prompt": "a", "tool": "search_web"},
            {"prompt": "b", "tool": "mcp__filesystem_read"},
        ]
        result, depth, mr, _ = _build_dag_and_depth(steps)  # No weights
        tools = [s["tool"] for s in result]
        # Original order preserved (no sort)
        assert tools == ["mcp__network_fetch", "search_web", "mcp__filesystem_read"]
        assert mr == 0.0

    def test_steps_are_not_dictionaries_survives(self):
        """Graceful: steps without 'tool' key get weight 0."""
        steps = [{"prompt": "no tool key"}, {"prompt": "also none"}]
        result, depth, mr, _ = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)
        assert len(result) == 2
        assert mr == 0.0


# ── Original DAG invariants preserved ──────────────────────────────────

class TestDAGInvariantsPreserved:
    """V6.1 invariants must survive the V7.3 resistance-field addition."""

    def test_cycle_detection_still_works(self, rw):
        steps = [
            {"prompt": "A", "produces": "X", "needs": "Y"},
            {"prompt": "B", "produces": "Y", "needs": "X"},
        ]
        _, depth, _, _ = _build_dag_and_depth(steps, rw)
        assert depth == 1  # Cycle -> fallback to sequential

    def test_parallel_depth_unchanged_without_weights(self):
        """Backward compat: no weights = same behavior as V6.1."""
        steps = [
            {"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"},
        ]
        _, depth, _, _ = _build_dag_and_depth(steps)
        assert depth == 3  # All independent, full parallel

    def test_oob_indices_still_sanitized(self, rw):
        steps = [
            {"prompt": "A", "depends_on": [99]},  # OOB -> ignored
            {"prompt": "B"},
        ]
        _, depth, _, _ = _build_dag_and_depth(steps, rw)
        assert depth == 2  # Both independent after sanitization

    def test_fallback_depth_without_resistance_is_same(self):
        """Without resistance_weights, behavior is identical to V6.1."""
        steps = [
            {"prompt": "a"}, {"prompt": "b"},
        ]
        # With and without weights should give same depth
        _, d1, _, _ = _build_dag_and_depth(steps)
        _, d2, _, _ = _build_dag_and_depth(steps, RESISTANCE_WEIGHTS)
        assert d1 == d2 == 2  # Only depth may differ; max_resistance differs
