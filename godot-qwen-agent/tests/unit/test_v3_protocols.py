"""V3 Protocol conformance + mock tests — 30补充测试."""

import pytest
from core.contracts.v3_protocols import (
    SemanticTrustDetector, PatternRepository, ToolRegistry,
)
from tests.mocks import (
    MockPatternRepository, MockSemanticTrustDetector, MockToolRegistry,
)


# ═══════════════════ PatternRepository Protocol ═══════════════════

class TestPatternRepositoryProtocol:
    """Both SQLite and Mock must satisfy PatternRepository."""

    def test_mock_satisfies_protocol(self):
        repo = MockPatternRepository()
        assert isinstance(repo, PatternRepository)

    def test_sqlite_satisfies_protocol(self):
        from core.adapters.relational_patterns import RelationalPatterns
        repo = RelationalPatterns(":memory:")
        assert isinstance(repo, PatternRepository)
        repo.close()

    def test_mock_record_and_query(self):
        repo = MockPatternRepository()
        for _ in range(4):
            repo.record("user_a", "fatigue_brevity", "verbose_low",
                        tags="Tuesday,afternoon")
        results = repo.query_active("user_a")
        assert len(results) >= 1
        assert results[0]["confidence"] >= 0.8

    def test_mock_below_threshold_no_results(self):
        repo = MockPatternRepository()
        for _ in range(2):  # Only 2 — below min_occurrence=3
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        results = repo.query_active("user_a")
        assert len(results) == 0

    def test_mock_low_confidence_filtered(self):
        repo = MockPatternRepository()
        for i in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low",
                        success=(i == 0))  # 1/3 success = 33%
        results = repo.query_active("user_a", min_confidence=0.8)
        assert len(results) == 0

    def test_mock_hint_generation(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        hint = repo.generate_hint("user_a")
        assert hint is not None
        assert "关系预判" in hint

    def test_mock_no_hint_for_unknown_user(self):
        repo = MockPatternRepository()
        hint = repo.generate_hint("unknown")
        assert hint is None

    def test_mock_decay(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        decayed = repo.decay_all("user_a")
        assert decayed >= 1


# ═══════════════════ SemanticTrustDetector Protocol ═══════════════

class TestSemanticTrustProtocol:
    """Embedding engine + mock must satisfy SemanticTrustDetector."""

    def test_mock_satisfies_protocol(self):
        detector = MockSemanticTrustDetector()
        assert isinstance(detector, SemanticTrustDetector)

    def test_embedding_satisfies_protocol(self):
        try:
            from core.adapters.semantic_trust import SemanticTrustEngine
            engine = SemanticTrustEngine()
            assert isinstance(engine, SemanticTrustDetector)
        except (ImportError, OSError):
            pytest.skip("Embedding model not available")

    def test_mock_returns_configured_response(self):
        detector = MockSemanticTrustDetector()
        detector.set_response("fatigue", 0.72)
        result = detector.detect("好累啊")
        assert result["dimension"] == "fatigue"
        assert abs(result["score"] - 0.72) < 0.01

    def test_mock_returns_neutral_by_default(self):
        detector = MockSemanticTrustDetector()
        result = detector.detect("anything")
        assert result["dimension"] is None

    def test_mock_tracks_call_count(self):
        detector = MockSemanticTrustDetector()
        detector.detect("a")
        detector.detect("b")
        assert detector.call_count == 2

    def test_mock_dimensions_property(self):
        detector = MockSemanticTrustDetector()
        assert len(detector.dimensions) >= 3


# ═══════════════════ ToolRegistry Protocol ═══════════════════

class TestToolRegistryProtocol:
    """Dict-based and mock registries must satisfy ToolRegistry."""

    def test_mock_satisfies_protocol(self):
        registry = MockToolRegistry({"search": {"risk": "read"}})
        assert isinstance(registry, ToolRegistry)

    def test_dict_registry_satisfies_protocol(self):
        from core.contracts.tool_contract import TOOLS as tools_dict

        # Create a simple adapter
        class DictToolRegistry:
            def get_contract(self, tool_name: str) -> dict | None:
                return tools_dict.get(tool_name)

            def list_tools(self) -> list[str]:
                return list(tools_dict.keys())

            def register(self, name: str, contract: dict) -> None:
                tools_dict[name] = contract

        registry = DictToolRegistry()
        assert isinstance(registry, ToolRegistry)

    def test_mock_register_and_retrieve(self):
        registry = MockToolRegistry()
        registry.register("ping", {"risk": "read", "min_trust": 0.0})
        contract = registry.get_contract("ping")
        assert contract is not None
        assert contract["risk"] == "read"

    def test_mock_list_tools(self):
        registry = MockToolRegistry({"a": {}, "b": {}})
        assert set(registry.list_tools()) == {"a", "b"}

    def test_mock_unknown_tool_returns_none(self):
        registry = MockToolRegistry()
        assert registry.get_contract("nonexistent") is None


# ═══════════════════ Integration: mock → real pipeline ═══════════════════

class TestV3MockIntegration:
    """Pipeline components with mock dependencies."""

    def test_signal_interpreter_with_mock_detector(self):
        detector = MockSemanticTrustDetector()
        detector.set_response("fatigue", 0.72)
        sig = detector.detect("字少点")
        assert sig["dimension"] == "fatigue"

        from core.adapters.signal_interpreter import interpret
        proposals = interpret(sig["dimension"], sig["score"], trust=0.30,
                              current_bp={"response_verbose_level": "HIGH",
                                          "conversational_initiative": "BALANCED",
                                          "tone_style": "WARM"})
        assert len(proposals) > 0

    def test_action_pipeline_with_mock_registry(self):
        registry = MockToolRegistry({
            "search_web": {"name": "search_web", "risk_level": "read",
                           "min_trust": 0.0, "require_hitl": False,
                           "category": "search"},
        })
        contract = registry.get_contract("search_web")
        assert contract is not None
        from core.contracts.tool_contract import ToolContract
        tc = ToolContract(**{k: v for k, v in contract.items()
                             if k in ToolContract.__dataclass_fields__})
        ok, _ = tc.check_trust(0.30)
        assert ok

    def test_pattern_repo_mock_feeds_hint_to_prompt(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        hint = repo.generate_hint("user_a")
        assert hint is not None
        # Simulate what run_live.py does
        system_prompt = f"{hint}\n\n[CURRENT MODE] Verbose: MEDIUM"
        assert "关系预判" in system_prompt
        assert "CURRENT MODE" in system_prompt
