"""PLAN5-8 Core Tests — DynamicBlueprint, EvolutionEngine, ActionPipeline.

Edge cases and boundary conditions that prove determinism.
"""

import pytest
from core.contracts.dynamic_blueprint import DynamicBlueprint, CONSTITUTION
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.tool_contract import TOOLS, RiskLevel
from core.contracts.blueprint_schema import blueprint_defaults


class TestDynamicBlueprint:
    """Core CRUD + safety valves for the living contract."""

    def test_apply_and_rollback(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        assert bp.apply_proposal("verbose", "LOW")[0]
        assert bp.enforce("verbose") == "LOW"
        assert bp.rollback()
        assert bp.enforce("verbose") == "HIGH"

    def test_rollback_no_history(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        assert not bp.rollback()

    def test_constitution_blocks_immutable_genes(self):
        for gene in CONSTITUTION:
            bp = DynamicBlueprint({gene: "original"})
            ok, reason = bp.apply_proposal(gene, "malicious")
            assert not ok, f"Gene {gene} should be immutable"
            assert "gene lock" in reason.lower()

    def test_schema_validation_rejects_invalid_values(self):
        bp = DynamicBlueprint(blueprint_defaults())
        ok, reason = bp.apply_proposal("response_verbose_level", "SUPER_LOW")
        assert not ok
        assert "instruction" in reason.lower() or "schema" in reason.lower()

    def test_schema_validation_accepts_valid_values(self):
        bp = DynamicBlueprint(blueprint_defaults())
        ok, _ = bp.apply_proposal("response_verbose_level", "LOW")
        assert ok
        assert bp.enforce("response_verbose_level") == "LOW"

    def test_cooldown_blocks_rapid_changes(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        assert bp.apply_proposal("verbose", "LOW")[0]
        # Same field, same round — blocked
        ok, reason = bp.apply_proposal("verbose", "HIGH")
        assert not ok
        assert "cooldown" in reason.lower()

    def test_cooldown_bypass_with_ignore_flag(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        assert bp.apply_proposal("verbose", "LOW")[0]
        ok, _ = bp.apply_proposal("verbose", "HIGH", ignore_cooldown=True)
        assert ok

    def test_min_autonomy_floor(self):
        bp = DynamicBlueprint({"execution_autonomy": "ASK_FIRST"})
        ok, reason = bp.apply_proposal("execution_autonomy", "DISABLED")
        assert not ok
        assert "min autonomy" in reason.lower()

    def test_decay_drifts_toward_baseline(self):
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")
        assert bp.enforce("response_verbose_level") == "LOW"
        # Simulate many rounds of decay
        for _ in range(60):
            bp.tick(half_life_rounds=20)
        # After many decay ticks, should be back at baseline
        assert bp.enforce("response_verbose_level") == "HIGH"

    def test_rejection_log_tracks_blocked_proposals(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")  # accepted
        bp.apply_proposal("verbose", "HIGH")  # cooldown blocked
        log = bp.rejection_log
        assert len(log) >= 1
        assert any("cooldown" in r["reason"].lower() for r in log)

    def test_enforce_reads_contract(self):
        bp = DynamicBlueprint({"tone": "WARM", "verbose": "HIGH"})
        assert bp.enforce("tone") == "WARM"
        assert bp.enforce("verbose") == "HIGH"
        assert bp.enforce("nonexistent") is None

    def test_snapshot_is_deep_copy(self):
        bp = DynamicBlueprint({"verbose": "HIGH"})
        snap = bp.snapshot
        bp.apply_proposal("verbose", "LOW")
        assert snap["verbose"] == "HIGH"  # Snapshot unchanged


class TestContractEvolutionEngine:
    """Trust gate, explicit commands, rollback monitoring."""

    def test_trust_gate_blocks_at_low_trust(self):
        engine = ContractEvolutionEngine(trust_threshold=0.10)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        ok, reason = engine.evaluate(
            {"target_blueprint_key": "verbose", "new_value": "LOW"},
            bp, trust=0.05,
        )
        assert not ok
        assert "trust gate" in reason.lower()

    def test_trust_gate_allows_at_sufficient_trust(self):
        engine = ContractEvolutionEngine(trust_threshold=0.10)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        ok, _ = engine.evaluate(
            {"target_blueprint_key": "verbose", "new_value": "LOW"},
            bp, trust=0.15,
        )
        assert ok

    def test_explicit_user_command_bypasses_all_gates(self):
        engine = ContractEvolutionEngine(trust_threshold=0.10)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        ok, _ = engine.evaluate(
            {"target_blueprint_key": "verbose", "new_value": "LOW", "source": "explicit_user_command"},
            bp, trust=0.01,  # Well below threshold
        )
        assert ok  # User is sovereign

    def test_rollback_on_trust_drop(self):
        engine = ContractEvolutionEngine(rollback_window=3, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)

        # Need 3 rounds of monitoring before rollback triggers
        engine.post_check(bp, trust_now=0.28)
        engine.post_check(bp, trust_now=0.25)
        rolled, reason = engine.post_check(bp, trust_now=0.24)
        assert rolled
        assert "rollback" in reason.lower()
        assert bp.enforce("verbose") == "HIGH"  # Reverted

    def test_constitution_guard_in_engine(self):
        engine = ContractEvolutionEngine()
        bp = DynamicBlueprint({"core_identity": "AI"})
        ok, reason = engine.evaluate(
            {"target_blueprint_key": "core_identity", "new_value": "SLAVE"},
            bp, trust=0.50,
        )
        assert not ok
        assert "gene lock" in reason.lower()


class TestActionPipeline:
    """Contract-bound tool execution: trust gates, HITL, Backlash, Constitution."""

    def test_read_tool_allowed_at_zero_trust(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.0)
        result = pipeline.check("search_web")
        assert result["allowed"]

    def test_read_tool_blocked_below_min_trust(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.05)
        result = pipeline.check("read_file")  # min_trust=0.10
        assert not result["allowed"]

    def test_read_tool_allowed_at_min_trust_boundary(self):
        """Edge case: exactly at threshold should pass."""
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.10)
        result = pipeline.check("read_file")  # min_trust=0.10
        assert result["allowed"]

    def test_read_tool_blocked_just_below_threshold(self):
        """Edge case: 0.001 below threshold should fail."""
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.099)
        result = pipeline.check("read_file")  # min_trust=0.10
        assert not result["allowed"]

    def test_write_blocked_by_ask_first_autonomy(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "ASK_FIRST"}), trust=0.40)
        result = pipeline.check("write_file")  # trust OK but ASK_FIRST blocks write
        assert not result["allowed"]
        assert result.get("requires_hitl")

    def test_destructive_requires_hitl(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.90)
        result = pipeline.check("delete_logs")  # trust >= 0.85 but HITL required
        assert not result["allowed"]
        assert result.get("requires_hitl")

    def test_backlash_3_failures_blocks(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            pipeline.record_result("search_web", success=False)
        result = pipeline.check("search_web")
        assert not result["allowed"]
        assert "backlash" in result["reason"].lower()

    def test_backlash_2_failures_still_allowed(self):
        """Edge case: 2 failures, 3rd should still work."""
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        pipeline.record_result("search_web", success=False)
        pipeline.record_result("search_web", success=False)
        result = pipeline.check("search_web")
        assert result["allowed"]  # Only 2 failures

    def test_backlash_reset_on_success(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            pipeline.record_result("search_web", success=False)
        pipeline.record_result("search_web", success=True)  # Reset
        result = pipeline.check("search_web")
        assert result["allowed"]

    def test_unknown_tool_blocked(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        result = pipeline.check("nonexistent_tool")
        assert not result["allowed"]
        assert "unknown" in result["reason"].lower()

    def test_disabled_autonomy_blocks_all_writes(self):
        pipeline = ActionPipeline(DynamicBlueprint({"execution_autonomy": "DISABLED"}), trust=0.90)
        result = pipeline.check("search_web")  # Even READ at DISABLED
        assert not result["allowed"]


class TestToolContract:
    """Tool contract metadata and trust thresholds."""

    def test_risk_level_enum(self):
        assert RiskLevel.READ.value == "read"
        assert RiskLevel.DESTRUCTIVE.value == "destructive"

    def test_tool_registry_has_expected_risk_levels(self):
        assert TOOLS["search_web"]["risk_level"] == RiskLevel.READ
        assert TOOLS["delete_logs"]["risk_level"] == RiskLevel.DESTRUCTIVE

    def test_min_trust_thresholds_are_calibrated(self):
        """DESTRUCTIVE tools must require higher trust than WRITE tools."""
        destructive_min = min(t["min_trust"] for t in TOOLS.values() if t["risk_level"] == RiskLevel.DESTRUCTIVE)
        write_min = max(t["min_trust"] for t in TOOLS.values() if t["risk_level"] == RiskLevel.WRITE)
        assert destructive_min > write_min, "Destructive tools should require more trust than write tools"

    def test_hitl_required_for_all_destructive(self):
        # Only check the 6 built-in tools (SDK may register extras)
        built_in = ["search_web", "read_file", "write_file", "send_email", "delete_logs", "restart_server"]
        for name in built_in:
            data = TOOLS[name]
            if data["risk_level"] == RiskLevel.DESTRUCTIVE:
                assert data.get("require_hitl"), f"{name} destructive but no HITL"
