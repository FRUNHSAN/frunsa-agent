"""V9.2c: 规则引擎压力测试 — 命中/未命中/冲突/旧兼容."""
import pytest
from mainboard.orchestrate.harness import _resolve_tools_deterministic
from mainboard.plugin_sdk.registry import HarnessToolRegistry, discover_core_tools


@pytest.fixture
def registry():
    """初始化 HarnessToolRegistry 并加载核心工具。"""
    discover_core_tools()
    return HarnessToolRegistry()


class TestRuleEngine:
    """规则引擎的确定性匹配测试。

    规则优先 (100% 确定, 零延迟) → LLM 兜底 (处理未知意图)。
    """

    # ── 正例命中 ──────────────────────────────────────

    @pytest.mark.parametrize("user_text, expected_tool", [
        ("现在几点钟", "run_powershell"),
        ("帮我写个文件", "write_file"),
        ("搜一下量子力学", "web_search"),
        ("执行 dir 命令", "run_powershell"),
        ("查看文件 /tmp/test.txt", "read_file"),
        ("保存这个内容", "write_file"),
        ("查一下天气", "web_search"),
    ])
    def test_deterministic_hit(self, registry, user_text, expected_tool):
        result = _resolve_tools_deterministic(user_text, registry)
        assert result is not None, f"规则引擎漏报: '{user_text}'"
        assert result[0]["tool"] == expected_tool, (
            f"误报: 期望 {expected_tool}, "
            f"实际 {result[0]['tool']}"
        )

    # ── 负例未命中 ────────────────────────────────────

    @pytest.mark.parametrize("user_text", [
        "今天天气真好",
        "给我讲个笑话",
        "1+1等于几",
        "帮我分析一下这段代码的复杂度",
        "你是谁发明的",
    ])
    def test_deterministic_miss(self, registry, user_text):
        result = _resolve_tools_deterministic(user_text, registry)
        assert result is None, (
            f"规则引擎误伤: '{user_text}' 应该交给 LLM 兜底"
        )

    # ── 冲突场景 ──────────────────────────────────────

    def test_conflict_resolution(self, registry):
        """包含"写"和"时间" — 不崩溃，返回合法工具之一。"""
        user_text = "帮我写一个获取时间的脚本"
        result = _resolve_tools_deterministic(user_text, registry)
        assert result is not None, "冲突场景下规则引擎不应返回 None"
        # 不硬编码注册顺序，不制造 flaky test
        assert result[0]["tool"] in ("write_file", "run_powershell"), (
            f"冲突场景返回了意外工具: {result[0]['tool']}"
        )

    # ── 旧版本兼容 ────────────────────────────────────

    def test_backward_compatibility(self, registry):
        patterns = registry.get_match_patterns("nonexistent_legacy_tool")
        assert patterns == (), "旧工具应返回空元组"

        # 不存在的工具不应导致崩溃
        result = _resolve_tools_deterministic("随便说点什么", registry)
        assert result is None, "旧工具注册不完整时规则引擎不应崩溃"
