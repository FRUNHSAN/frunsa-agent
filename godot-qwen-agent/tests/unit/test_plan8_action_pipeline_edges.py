"""ActionPipeline edge cases: all tools, all trust levels, all autonomy modes."""

import pytest
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.tool_contract import TOOLS, RiskLevel


class TestActionPipelineAllTools:
    """Every tool tested at critical trust boundaries."""

    @pytest.mark.parametrize("tool_name,min_trust", [
        ("search_web", 0.0),
        ("read_file", 0.10),
        ("write_file", 0.35),
        ("send_email", 0.50),
        ("delete_logs", 0.85),
        ("restart_server", 0.90),
    ])
    def test_tool_blocked_just_below_min_trust(self, tool_name, min_trust):
        if min_trust == 0.0:
            pytest.skip("No minimum for search_web")
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=min_trust - 0.001)
        result = p.check(tool_name)
        if TOOLS[tool_name].get("require_hitl"):
            assert not result["allowed"]  # HITL blocks regardless
        else:
            assert not result["allowed"]
            assert "trust" in result["reason"].lower()

    @pytest.mark.parametrize("tool_name,min_trust", [
        ("search_web", 0.0),
        ("read_file", 0.10),
        ("write_file", 0.35),
        ("send_email", 0.50),
        ("delete_logs", 0.85),
        ("restart_server", 0.90),
    ])
    def test_tool_allowed_at_min_trust_with_full_autonomy(self, tool_name, min_trust):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=min_trust)
        result = p.check(tool_name)
        if TOOLS[tool_name].get("require_hitl"):
            assert not result["allowed"]  # HITL always blocks
            assert result.get("requires_hitl")
        else:
            assert result["allowed"]

    def test_all_read_tools_allowed_at_trust_zero(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.0)
        for name, data in TOOLS.items():
            if data["risk_level"] == RiskLevel.READ and data["min_trust"] == 0.0:
                assert p.check(name)["allowed"], f"{name} should be allowed"

    def test_destructive_tools_require_highest_trust(self):
        destructive = [t for t in TOOLS.values() if t["risk_level"] == RiskLevel.DESTRUCTIVE]
        write = [t for t in TOOLS.values() if t["risk_level"] == RiskLevel.WRITE]
        if destructive and write:
            min_destructive = min(t["min_trust"] for t in destructive)
            max_write = max(t["min_trust"] for t in write)
            assert min_destructive > max_write


class TestAutonomyModes:
    """Blueprint autonomy controls tool execution."""

    def test_disabled_blocks_even_read(self):
        bp = DynamicBlueprint({"execution_autonomy": "DISABLED"})
        p = ActionPipeline(bp, trust=0.99)
        assert not p.check("search_web")["allowed"]

    def test_ask_first_blocks_write(self):
        bp = DynamicBlueprint({"execution_autonomy": "ASK_FIRST"})
        p = ActionPipeline(bp, trust=0.99)
        assert not p.check("write_file")["allowed"]
        assert p.check("search_web")["allowed"]

    def test_ask_first_blocks_destructive(self):
        bp = DynamicBlueprint({"execution_autonomy": "ASK_FIRST"})
        p = ActionPipeline(bp, trust=0.99)
        assert not p.check("delete_logs")["allowed"]

    def test_high_allows_write(self):
        bp = DynamicBlueprint({"execution_autonomy": "HIGH"})
        p = ActionPipeline(bp, trust=0.50)
        assert p.check("write_file")["allowed"]

    def test_full_allows_write(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.50)
        assert p.check("write_file")["allowed"]

    def test_full_still_respects_hitl(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.90)
        result = p.check("delete_logs")
        assert not result["allowed"]
        assert result.get("requires_hitl")

    def test_autonomy_downgrade_blocks_previously_allowed(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.50)
        assert p.check("write_file")["allowed"]
        bp.apply_proposal("execution_autonomy", "ASK_FIRST")
        assert not p.check("write_file")["allowed"]


class TestTrustBoundaries:
    """Trust value edge cases at tool thresholds."""

    def test_trust_zero_point_one_allows_read_file(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.10)
        assert p.check("read_file")["allowed"]

    def test_trust_zero_point_zero_nine_blocks_read_file(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.09)
        assert not p.check("read_file")["allowed"]

    def test_trust_one_allows_all_non_hitl(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=1.0)
        for name, data in TOOLS.items():
            if not data.get("require_hitl"):
                assert p.check(name)["allowed"], f"{name} blocked at trust=1.0"

    def test_trust_exact_boundary(self):
        """Floating point at exact boundary should pass."""
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.10)
        result = p.check("read_file")
        assert result["allowed"]

    def test_trust_just_below_boundary(self):
        """Floating point at boundary - epsilon should fail."""
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.0999999)
        result = p.check("read_file")
        assert not result["allowed"]


class TestUnknownTool:
    """Unknown tools always blocked."""

    def test_unknown_tool_name(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.99)
        result = p.check("do_something_sketchy")
        assert not result["allowed"]
        assert "unknown" in result["reason"].lower()

    def test_empty_tool_name(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.99)
        result = p.check("")
        assert not result["allowed"]

    def test_none_tool_name_blocked(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.99)
        result = p.check(None)  # type: ignore
        assert not result["allowed"]
