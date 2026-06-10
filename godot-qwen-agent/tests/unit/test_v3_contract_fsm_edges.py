"""Contract engine + StreamInterceptor edge cases."""

import pytest
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.stream_interceptor import StreamInterceptor, FSMState


class TestContractEdgeCases:
    def test_constitution_blocks_immutable_genes(self):
        engine = ContractEvolutionEngine()
        bp = DynamicBlueprint({"min_autonomy": "ASK_FIRST"})
        for gene in ["min_autonomy", "cooldown_rounds"]:
            prop = {"target_blueprint_key": gene, "new_value": "MALICIOUS"}
            ok, reason = engine.evaluate(prop, bp, trust=0.90)
            assert not ok, f"{gene} should be blocked"

    def test_multi_field_proposal_independent_cooldown(self):
        bp = DynamicBlueprint({"verbose": "HIGH", "tone": "WARM"}, cooldown_rounds=5)
        bp.apply_proposal("verbose", "LOW")
        # Different field, no cooldown
        ok, _ = bp.apply_proposal("tone", "PRAGMATIC")
        assert ok

    def test_rollback_window_boundary(self):
        engine = ContractEvolutionEngine(rollback_window=3, rollback_trust_drop=0.05)
        bp = DynamicBlueprint({"verbose": "HIGH"})
        bp.apply_proposal("verbose", "LOW")
        engine.record_evolution(trust_before=0.30)
        # Round 1-2: no rollback (monitoring)
        assert not engine.post_check(bp, trust_now=0.10)[0]
        assert not engine.post_check(bp, trust_now=0.10)[0]
        # Round 3: rollback triggers
        rolled, _ = engine.post_check(bp, trust_now=0.10)
        assert rolled


class TestFSMEdges:
    def test_fsm_resets_after_timeout_then_normal(self):
        fsm = StreamInterceptor()
        fsm.feed("hello. ")
        fsm.feed("<tool_call>")
        fsm.feed('{"tool": "x"')
        fsm.timeout()
        result = fsm.feed("回到正常聊天。")
        assert result.state == FSMState.TEXT

    def test_force_complete_on_normal_text_is_noop(self):
        fsm = StreamInterceptor()
        fsm.feed("正常文本，没有工具调用。")
        result = fsm.force_complete()
        assert result.state == FSMState.TEXT

    def test_trigger_window_handles_fragmented_input(self):
        fsm = StreamInterceptor()
        # Fragment the trigger across tokens
        fsm.feed("<too")
        fsm.feed("l_call>")
        result = fsm.feed('{"tool": "x"}')
        # The sliding window should detect the trigger
        assert result.state in (FSMState.BUFFERING, FSMState.VALIDATING)
