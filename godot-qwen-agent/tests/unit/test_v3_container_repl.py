"""V3 Container + REPL tests — verifying the new architecture."""

import pytest
from core.config import Config
from core.container import Container
from core.repl import Repl
from tests.mocks import MockSemanticTrustDetector


class TestConfig:
    def test_default_user_id(self):
        cfg = Config.from_args([])
        assert cfg.user_id == "default"

    def test_user_id_from_args(self):
        cfg = Config.from_args(["", "frunhsan"])
        assert cfg.user_id == "frunhsan"

    def test_local_flag(self):
        cfg = Config.from_args(["", "--local"])
        assert cfg.use_local

    def test_no_local_flag(self):
        cfg = Config.from_args(["", "user"])
        assert not cfg.use_local


class TestContainer:
    def test_builds_all_components(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        assert ctr.bp is not None
        assert ctr.engine is not None
        assert ctr.output_pipeline is not None
        assert ctr.action_pipeline is not None
        assert ctr.fsm is not None
        assert ctr.profile is not None
        assert ctr.learner is not None
        assert ctr.patterns is not None
        assert ctr.listener is not None

    def test_local_llm_initializes(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        llm = ctr.local_llm
        assert llm is not None

    def test_auditor_initializes(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        auditor = ctr.auditor
        assert auditor is not None
        assert auditor.interval == 10

    def test_bp_has_schema_fields(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        bp = ctr.bp.snapshot
        assert "response_verbose_level" in bp
        assert "conversational_initiative" in bp
        assert "tone_style" in bp


class TestRepl:
    def test_repl_initialization(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        assert repl.trust == 0.30
        assert repl.round_count == 0

    def test_explicit_command_detection(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)

        assert repl._detect_explicit_command("字少点，别啰嗦") is not None
        assert repl._detect_explicit_command("详细展开一下") is not None
        assert repl._detect_explicit_command("字多一点") is not None
        assert repl._detect_explicit_command("正常聊天") is None

    def test_explicit_command_verbose_minimal(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        result = repl._detect_explicit_command("字少点")
        assert result == ("response_verbose_level", "MINIMAL")

    def test_explicit_command_verbose_high(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        result = repl._detect_explicit_command("详细点，展开讲讲")
        assert result == ("response_verbose_level", "HIGH")

    def test_explicit_command_no_questions(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        result = repl._detect_explicit_command("别问了，不要问")
        assert result == ("conversational_initiative", "RESPONSIVE_ONLY")

    def test_explicit_command_warm_tone(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        result = repl._detect_explicit_command("带点感情，像朋友一样")
        assert result == ("tone_style", "WARM")

    def test_apply_proposal_changes_bp(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        prop = {"target_blueprint_key": "response_verbose_level", "new_value": "LOW"}
        ok = repl._apply_proposal(prop, label="TEST")
        assert ok
        assert ctr.bp.enforce("response_verbose_level") == "LOW"

    def test_build_prompt_includes_contract_state(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        prompt = repl._build_prompt()
        assert "CURRENT MODE" in prompt
        assert "字数" in prompt

    def test_explicit_commands_dont_trigger_on_normal_text(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        # "好" should not match "字少点" etc.
        assert repl._detect_explicit_command("好的，我了解了") is None
        assert repl._detect_explicit_command("可以") is None

    def test_round_count_increments(self):
        cfg = Config.from_args(["test"])
        ctr = Container(cfg)
        repl = Repl(ctr)
        repl.round_count += 1
        repl.round_count += 1
        assert repl.round_count == 2


class TestConfigEdgeCases:
    def test_extra_args_ignored(self):
        cfg = Config.from_args(["", "user", "--verbose", "--extra"])
        assert cfg.user_id == "user"

    def test_empty_args(self):
        cfg = Config.from_args([])
        assert not cfg.use_local
