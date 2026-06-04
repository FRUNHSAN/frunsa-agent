"""Backlash + Decay edge cases — the hardest-to-get-right contract behaviors."""

import pytest
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.action_pipeline import ActionPipeline
from core.adapters.contract_evolution_engine import ContractEvolutionEngine


class TestBacklash:
    """Backlash: tool failures lock tools. Success resets."""

    def test_zero_failures_allowed(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        assert p.check("search_web")["allowed"]

    def test_one_failure_still_allowed(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        p.record_result("search_web", success=False)
        assert p.check("search_web")["allowed"]

    def test_two_failures_still_allowed(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        p.record_result("search_web", success=False)
        p.record_result("search_web", success=False)
        assert p.check("search_web")["allowed"]

    def test_three_failures_blocked(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            p.record_result("search_web", success=False)
        assert not p.check("search_web")["allowed"]

    def test_four_failures_still_blocked(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(4):
            p.record_result("search_web", success=False)
        assert not p.check("search_web")["allowed"]

    def test_recovery_after_three_failures(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            p.record_result("search_web", success=False)
        p.record_result("search_web", success=True)
        assert p.check("search_web")["allowed"]

    def test_interleaved_success_resets_counter(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        p.record_result("search_web", success=False)
        p.record_result("search_web", success=False)
        p.record_result("search_web", success=True)  # Reset
        p.record_result("search_web", success=False)
        assert p.check("search_web")["allowed"]  # Only 1 failure after reset

    def test_backlash_is_per_tool(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            p.record_result("search_web", success=False)
        # search_web blocked but read_file unaffected
        assert not p.check("search_web")["allowed"]
        assert p.check("read_file")["allowed"]

    def test_backlash_persists_after_trust_change(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "FULL"}), trust=0.50)
        for _ in range(3):
            p.record_result("search_web", success=False)
        p.trust = 0.90  # High trust doesn't override Backlash
        assert not p.check("search_web")["allowed"]

    def test_backlash_survives_autonomy_change(self):
        p = ActionPipeline(DynamicBlueprint({"execution_autonomy": "ASK_FIRST"}), trust=0.50)
        # Even with FULL autonomy, Backlash blocks
        p._bp.apply_proposal("execution_autonomy", "FULL")
        for _ in range(3):
            p.record_result("search_web", success=False)
        assert not p.check("search_web")["allowed"]


class TestDecay:
    """Contract half-life decay: temporary adaptations heal over time."""

    def test_decay_returns_to_baseline_eventually(self):
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")
        for _ in range(100):
            bp.tick(half_life_rounds=20)
        assert bp.enforce("response_verbose_level") == "HIGH"

    def test_decay_stops_at_baseline(self):
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")
        for _ in range(200):
            bp.tick(half_life_rounds=20)
        assert bp.enforce("response_verbose_level") == "HIGH"

    def test_decay_skips_while_field_still_fresh(self):
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")
        # Tick with high half-life — field still fresh
        changes = bp.tick(half_life_rounds=999)
        assert "response_verbose_level" not in changes

    def test_decay_does_not_affect_unmodified_fields(self):
        bp = DynamicBlueprint({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        bp.apply_proposal("response_verbose_level", "LOW")
        for _ in range(50):
            bp.tick(half_life_rounds=20)
        # tone_style should stay WARM
        assert bp.enforce("tone_style") == "WARM"

    def test_decay_with_low_half_life(self):
        """Low half-life means faster decay."""
        bp = DynamicBlueprint({"response_verbose_level": "HIGH"})
        bp.apply_proposal("response_verbose_level", "LOW")
        for _ in range(20):
            bp.tick(half_life_rounds=5)
        assert bp.enforce("response_verbose_level") == "HIGH"

    def test_multi_field_decay(self):
        bp = DynamicBlueprint({
            "response_verbose_level": "HIGH",
            "proactive_suggestions": "ENABLED",
        })
        bp.apply_proposal("response_verbose_level", "EXTREME_BRIEF")
        bp.apply_proposal("proactive_suggestions", "DISABLED")
        for _ in range(60):
            bp.tick(half_life_rounds=20)
        assert bp.enforce("response_verbose_level") == "HIGH"
        assert bp.enforce("proactive_suggestions") == "ENABLED"

    def test_decay_preserves_other_fields_after_rollback(self):
        bp = DynamicBlueprint({
            "response_verbose_level": "HIGH",
            "tone_style": "WARM",
        })
        bp.apply_proposal("response_verbose_level", "LOW")
        bp.apply_proposal("tone_style", "PRAGMATIC")
        bp.rollback()  # Undo tone change
        for _ in range(60):
            bp.tick(half_life_rounds=20)
        assert bp.enforce("tone_style") == "WARM"  # Rolled back, stayed baseline
        assert bp.enforce("response_verbose_level") == "HIGH"  # Decayed back


class TestRollback:
    """Evolution rollback: trust drops → contract reverts."""

    def test_single_rollback_restores_state(self):
        engine = ContractEvolutionEngine(rollback_window=3, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)

        for _ in range(3):
            engine.post_check(bp, trust_now=0.20)
        assert bp.enforce("verbose") == "HIGH"

    def test_rollback_only_triggers_after_window(self):
        engine = ContractEvolutionEngine(rollback_window=5, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)

        # Round 1-4: not enough rounds, no rollback
        for _ in range(4):
            rolled, _ = engine.post_check(bp, trust_now=0.10)
            assert not rolled
            assert bp.enforce("verbose") == "LOW"

    def test_no_rollback_if_trust_recovers(self):
        engine = ContractEvolutionEngine(rollback_window=3, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)

        # Trust drops but then recovers within window
        engine.post_check(bp, trust_now=0.28)
        engine.post_check(bp, trust_now=0.31)  # Recovered!
        rolled, _ = engine.post_check(bp, trust_now=0.32)
        assert not rolled
        assert bp.enforce("verbose") == "LOW"  # No rollback needed

    def test_rollback_then_reapply(self):
        """After rollback, same proposal can be re-applied with cooldown bypass."""
        engine = ContractEvolutionEngine(rollback_window=3, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})

        # Apply, rollback
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)
        for _ in range(3):
            engine.post_check(bp, trust_now=0.20)
        assert bp.enforce("verbose") == "HIGH"

        # Re-apply (cooldown-aware — use ignore_cooldown for test)
        bp.apply_proposal("verbose", "LOW", ignore_cooldown=True)
        engine.record_evolution(trust_before=0.50)
        for _ in range(3):
            engine.post_check(bp, trust_now=0.48)
        assert bp.enforce("verbose") == "LOW"


class TestCooldown:
    """Cooldown: same field can't oscillate."""

    def test_cooldown_blocks_within_window(self):
        bp = DynamicBlueprint({"verbose": "HIGH"}, cooldown_rounds=5)
        assert bp.apply_proposal("verbose", "LOW")[0]
        # Immediate change back blocked
        ok, reason = bp.apply_proposal("verbose", "HIGH")
        assert not ok
        assert "cooldown" in reason.lower()

    def test_cooldown_allows_after_window_passes(self):
        bp = DynamicBlueprint({"verbose": "HIGH"}, cooldown_rounds=3)
        bp.apply_proposal("verbose", "LOW")
        # Simulate rounds passing
        for _ in range(3):
            bp.tick(half_life_rounds=99)
        ok, _ = bp.apply_proposal("verbose", "HIGH")
        assert ok

    def test_cooldown_per_field_independent(self):
        bp = DynamicBlueprint({"verbose": "HIGH", "tone": "WARM"}, cooldown_rounds=5)
        bp.apply_proposal("verbose", "LOW")
        # Different field, no cooldown
        ok, _ = bp.apply_proposal("tone", "PRAGMATIC")
        assert ok

    def test_cooldown_bypass_with_ignore_flag(self):
        bp = DynamicBlueprint({"verbose": "HIGH"}, cooldown_rounds=5)
        bp.apply_proposal("verbose", "LOW")
        ok, _ = bp.apply_proposal("verbose", "HIGH", ignore_cooldown=True)
        assert ok

    def test_cooldown_respected_after_rollback(self):
        bp = DynamicBlueprint({"verbose": "HIGH"}, cooldown_rounds=5)
        bp.apply_proposal("verbose", "LOW")
        bp.rollback()
        # Immediate re-apply blocked by cooldown
        ok, reason = bp.apply_proposal("verbose", "LOW")
        assert not ok
        assert "cooldown" in reason.lower()
