"""OutputPipeline + ActionPipeline edge tests."""

import pytest
from core.adapters.output_pipeline import OutputPipeline
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.dynamic_blueprint import DynamicBlueprint


class MockBP:
    def __init__(self, d): self.d = d
    def enforce(self, k): return self.d.get(k)


class TestOutputPipelineEdges:
    def test_minimal_truncates_to_two_sentences(self):
        bp = MockBP({"response_verbose_level": "MINIMAL", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "你好。这是第一句。这是第二句。这是第三句。这是第四句。"
        clean, penalty = p.process(raw)
        assert clean.count("。") <= 2

    def test_low_truncates_to_three_sentences(self):
        bp = MockBP({"response_verbose_level": "LOW", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "一。二。三。四。五。"
        clean, _ = p.process(raw)
        assert clean.count("。") <= 3

    def test_high_no_truncation(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "一。二。三。四。五。六。七。八。九。"
        clean, _ = p.process(raw)
        # HIGH allows up to 8
        assert clean.count("。") <= 8

    def test_pragmatic_strips_fillers(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "PRAGMATIC"})
        p = OutputPipeline(bp)
        raw = "我觉得这个方案可能有问题，我认为可以试试别的。"
        clean, _ = p.process(raw)
        assert "我觉得" not in clean
        assert "我认为" not in clean

    def test_sycophancy_penalty(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        _, penalty = p.process("你说得对，这个判断很准确。")
        assert penalty > 0

    def test_sycophancy_variants(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        for text in ["你的判断正确", "非常准确", "确实如此，你", "没错，你"]:
            _, penalty = p.process(text)
            assert penalty > 0, f"Should penalize: {text}"

    def test_markdown_stripping(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "**hello** world\n- item 1\n### header"
        clean, _ = p.process(raw)
        assert "**" not in clean
        assert "- " not in clean
        assert "###" not in clean

    def test_normal_text_no_penalty(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        _, penalty = p.process("你好，今天天气不错。")
        assert penalty == 0

    def test_empty_input(self):
        bp = MockBP({"response_verbose_level": "HIGH", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        clean, penalty = p.process("")
        assert clean == ""
        assert penalty == 0

    def test_question_mark_counts_as_sentence(self):
        bp = MockBP({"response_verbose_level": "MINIMAL", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "你好吗？我很好。今天天气不错吧？确实不错。"
        clean, _ = p.process(raw)
        # Should truncate at 2 sentence terminators
        count = clean.count("。") + clean.count("？") + clean.count("！")
        assert count <= 2

    def test_exclamation_mark_counts(self):
        bp = MockBP({"response_verbose_level": "MINIMAL", "tone_style": "WARM"})
        p = OutputPipeline(bp)
        raw = "太好了！真棒！继续加油！"
        clean, _ = p.process(raw)
        assert clean.count("！") <= 2


class TestActionPipelineEdges:
    def test_unknown_tool_blocked_reason(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.99)
        result = p.check("do_something_evil")
        assert not result["allowed"]
        assert "unknown" in result["reason"].lower()

    def test_write_blocked_by_ask_first(self):
        bp = DynamicBlueprint({"execution_autonomy": "ASK_FIRST"})
        p = ActionPipeline(bp, trust=0.99)
        result = p.check("write_file")
        assert not result["allowed"]

    def test_trust_boundary_read_file(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.10)
        assert p.check("read_file")["allowed"]
        p.trust = 0.09
        assert not p.check("read_file")["allowed"]

    def test_backlash_count_reset_after_check(self):
        bp = DynamicBlueprint({"execution_autonomy": "FULL"})
        p = ActionPipeline(bp, trust=0.50)
        for _ in range(3):
            p.record_result("search_web", success=False)
        # search_web blocked
        assert not p.check("search_web")["allowed"]
        # Other tools unaffected
        assert p.check("read_file")["allowed"]

    def test_autonomy_disabled_blocks_all(self):
        bp = DynamicBlueprint({"execution_autonomy": "DISABLED"})
        p = ActionPipeline(bp, trust=0.99)
        for name in ["search_web", "read_file", "write_file"]:
            assert not p.check(name)["allowed"], f"{name} should be blocked"
