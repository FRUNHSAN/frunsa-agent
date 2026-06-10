"""Repl class tests — main interaction loop, previously 0 coverage."""

import io
import os
import tempfile
import pytest
from core.config import Config
from core.container import Container
from core.repl import Repl


@pytest.fixture
def repl():
    cfg = Config.from_args(["test"])
    ctr = Container(cfg)
    return Repl(ctr)


class TestReplCommands:
    """Built-in slash commands."""

    def test_explicit_command_minimal(self, repl):
        assert repl._detect_explicit_command("字少点，别啰嗦") is not None

    def test_explicit_command_high(self, repl):
        r = repl._detect_explicit_command("详细点，展开说说")
        assert r is not None
        assert r[0] == "response_verbose_level"

    def test_explicit_command_medium(self, repl):
        r = repl._detect_explicit_command("字多一点点")
        assert r is not None

    def test_explicit_command_proactive(self, repl):
        r = repl._detect_explicit_command("你倒是问问题呀")
        assert r is not None
        assert r[1] == "PROACTIVE"

    def test_explicit_command_no_questions(self, repl):
        r = repl._detect_explicit_command("别问了，不要问")
        assert r is not None
        assert r[1] == "RESPONSIVE_ONLY"

    def test_explicit_command_warm_tone(self, repl):
        r = repl._detect_explicit_command("带点感情，像朋友一样")
        assert r is not None
        assert r[1] == "WARM"

    def test_explicit_command_none_for_normal_text(self, repl):
        assert repl._detect_explicit_command("今天天气不错") is None
        assert repl._detect_explicit_command("好的，我了解了") is None
        assert repl._detect_explicit_command("可以") is None


class TestReplProposal:
    """Proposal application through the contract engine."""

    def test_apply_proposal_changes_bp(self, repl):
        old = repl.c.bp.enforce("response_verbose_level")
        prop = {"target_blueprint_key": "response_verbose_level", "new_value": "LOW"}
        ok = repl._apply_proposal(prop, "TEST")
        assert ok
        assert repl.c.bp.enforce("response_verbose_level") != old

    def test_apply_proposal_rejected_by_constitution(self, repl):
        prop = {"target_blueprint_key": "min_autonomy", "new_value": "DISABLED"}
        ok = repl._apply_proposal(prop)
        assert not ok

    def test_apply_proposal_rejected_by_schema(self, repl):
        prop = {"target_blueprint_key": "response_verbose_level", "new_value": "MEGA_LOW"}
        ok = repl._apply_proposal(prop)
        assert not ok


class TestReplPrompt:
    """Prompt construction from contract state."""

    def test_build_prompt_includes_contract(self, repl):
        prompt = repl._build_prompt("test_user")
        assert "CURRENT MODE" in prompt
        assert "输出规范" in prompt

    def test_build_prompt_reflects_verbose_change(self, repl):
        repl.c.bp.apply_proposal("response_verbose_level", "MINIMAL")
        prompt = repl._build_prompt("test_user")
        assert "一句话" in prompt

    def test_build_prompt_includes_anti_sycophancy(self, repl):
        prompt = repl._build_prompt("test_user")
        assert "你说得对" in prompt or "分歧是尊重" in prompt

    def test_build_prompt_low_anchoring_blocks_metaphors(self, repl):
        repl.c.bp.apply_proposal("contextual_anchoring", "LOW")
        prompt = repl._build_prompt("test_user")
        assert "晨光" in prompt or "禁止" in prompt


class TestReplSession:
    """Session lifecycle and state isolation."""

    def test_round_count_starts_zero(self, repl):
        assert repl.round_count == 0

    def test_trust_starts_at_default(self, repl):
        assert repl.trust == 0.50

    def test_pending_proposals_empty_initially(self, repl):
        assert repl.pending == []

    def test_history_empty_initially(self, repl):
        assert repl.history == []
