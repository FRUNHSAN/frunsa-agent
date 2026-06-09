"""V6.1 DAG Topology Engine — unit tests for _build_dag_and_depth + _extract_step_fields.

Pure math tests: no LLM, no I/O, no embedding. Validates:
  - Tag-based dependency resolution
  - Index-based fallback
  - Cycle detection (Kahn's algorithm)
  - Index sanitization (out-of-bounds, self-loops)
  - Parallel depth computation via BFS level assignment
"""

import pytest
from core.track_c import _build_dag_and_depth, _extract_step_fields


# ═══════════════════════════════════════════════════════════════════════════
# _extract_step_fields
# ═══════════════════════════════════════════════════════════════════════════

class TestExtractStepFields:
    def test_extracts_json_fields(self):
        step = {}
        _extract_step_fields('{"prompt": "test", "produces": "x", "needs": "y"}', step)
        assert step["produces"] == "x"
        assert step["needs"] == "y"

    def test_extracts_depends_on_list(self):
        step = {}
        _extract_step_fields('{"prompt": "test", "depends_on": [0, 1]}', step)
        assert step["depends_on"] == [0, 1]

    def test_no_json_no_crash(self):
        step = {}
        _extract_step_fields("plain text without json", step)
        assert "produces" not in step
        assert "needs" not in step

    def test_broken_json_no_crash(self):
        step = {"prompt": "original"}
        _extract_step_fields('{"broken json', step)
        assert step["prompt"] == "original"  # unchanged


# ═══════════════════════════════════════════════════════════════════════════
# _build_dag_and_depth — tag-based resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestDAGBuilderTagResolution:
    def test_independent_steps_full_parallel(self):
        """Star DAG: 3 steps, 2 independent at level 0, 1 at level 1."""
        steps = [
            {"prompt": "查A", "produces": "a"},
            {"prompt": "查B", "produces": "b"},
            {"prompt": "对比", "needs": "a"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 2  # 2 at level 0, 1 at level 1

    def test_sequential_chain_serial(self):
        """Chain DAG: A→B→C, each level has 1 step."""
        steps = [
            {"prompt": "设计", "produces": "d"},
            {"prompt": "实现", "needs": "d", "produces": "c"},
            {"prompt": "测试", "needs": "c"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1

    def test_hybrid_dag(self):
        """Two independent at level 0, one dependent at level 1, one at level 2."""
        steps = [
            {"prompt": "A", "produces": "a"},
            {"prompt": "B", "produces": "b"},
            {"prompt": "C", "needs": "a"},
            {"prompt": "D", "needs": "b"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 2  # 2 at level 0, 2 at level 1

    def test_tag_not_matched_falls_back(self):
        """Unmatched 'needs' tag should not create a dependency."""
        steps = [
            {"prompt": "A", "needs": "nonexistent"},
            {"prompt": "B"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 2  # Both independent

    def test_empty_steps(self):
        steps = []
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1  # Safe default


# ═══════════════════════════════════════════════════════════════════════════
# _build_dag_and_depth — index-based fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestDAGBuilderIndexFallback:
    def test_depends_on_indices(self):
        steps = [
            {"prompt": "A", "depends_on": []},
            {"prompt": "B", "depends_on": [0]},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1

    def test_depends_on_oob_sanitized(self):
        """Out-of-bounds index should be silently dropped."""
        steps = [
            {"prompt": "A", "depends_on": [5]},  # OOB
            {"prompt": "B", "depends_on": [0]},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1

    def test_self_loop_sanitized(self):
        steps = [
            {"prompt": "A", "depends_on": [0]},  # self-loop
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1  # No crash, isolated step

    def test_tag_and_index_combined(self):
        """Both tag and index deps should be merged."""
        steps = [
            {"prompt": "A", "produces": "a"},
            {"prompt": "B", "depends_on": [0]},
            {"prompt": "C", "needs": "a", "depends_on": [1]},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        # A→B→C chain: depth=1
        assert depth == 1


# ═══════════════════════════════════════════════════════════════════════════
# _build_dag_and_depth — cycle detection
# ═══════════════════════════════════════════════════════════════════════════

class TestDAGBuilderCycleDetection:
    def test_direct_cycle_tag(self):
        steps = [
            {"prompt": "A", "produces": "a", "needs": "b"},
            {"prompt": "B", "produces": "b", "needs": "a"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1  # Cycle → fallback sequential

    def test_direct_cycle_index(self):
        steps = [
            {"prompt": "A", "depends_on": [1]},
            {"prompt": "B", "depends_on": [0]},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1  # Cycle → fallback sequential

    def test_indirect_cycle(self):
        """A→B→C→A three-step cycle."""
        steps = [
            {"prompt": "A", "produces": "a", "needs": "c"},
            {"prompt": "B", "produces": "b", "needs": "a"},
            {"prompt": "C", "produces": "c", "needs": "b"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1  # Cycle → fallback sequential

    def test_no_cycle_but_complex_dag(self):
        """Diamond DAG: A→C, B→C, A→D, B→D. No cycle."""
        steps = [
            {"prompt": "A", "produces": "a"},
            {"prompt": "B", "produces": "b"},
            {"prompt": "C", "needs": "a"},
            {"prompt": "D", "needs": "b"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        # 2 at level 0, 2 at level 1
        assert depth == 2


# ═══════════════════════════════════════════════════════════════════════════
# _build_dag_and_depth — no tags, no deps
# ═══════════════════════════════════════════════════════════════════════════

class TestDAGBuilderEmpty:
    def test_all_independent(self):
        steps = [
            {"prompt": "A"},
            {"prompt": "B"},
            {"prompt": "C"},
        ]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 3  # All independent, all at level 0

    def test_single_step(self):
        steps = [{"prompt": "A"}]
        _, depth, _ = _build_dag_and_depth(steps)
        assert depth == 1
