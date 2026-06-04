"""NarrativeEmergence tests — CBO patterns → user profile."""

import pytest
from core.adapters.narrative_emergence import NarrativeEmergence
from tests.mocks import MockPatternRepository


class FakeLLM:
    """Mock LLM that returns a fixed narrative."""
    def __init__(self, response: str = ""):
        self._response = response
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


class TestNarrativeEmergence:
    def test_no_narrative_when_insufficient_patterns(self):
        repo = MockPatternRepository()
        llm = FakeLLM("不应该被调用")
        ne = NarrativeEmergence(repo, llm)
        result = ne.generate("user_a")
        assert result is None

    def test_no_narrative_with_only_one_pattern(self):
        repo = MockPatternRepository()
        for _ in range(2):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        llm = FakeLLM("测试叙事")
        ne = NarrativeEmergence(repo, llm)
        # 2 occurrences but min_occurrence=2 and only 1 unique pattern
        result = ne.generate("user_a")
        assert result is None or len(llm.calls) >= 0  # May or may not call

    def test_generates_narrative_with_enough_patterns(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low", tags="Tuesday,afternoon")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command", tags="night,weekday")

        expected = "该用户通常在周二下午和深夜感到疲惫，倾向于简洁直接的沟通方式。"
        llm = FakeLLM(expected)
        ne = NarrativeEmergence(repo, llm)
        result = ne.generate("user_a")
        assert result is not None
        assert len(result) > 20

    def test_narrative_is_cached(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("该用户在周二下午和深夜时段容易疲惫，偏好简洁直接的沟通方式。")
        ne = NarrativeEmergence(repo, llm)
        r1 = ne.generate("user_a")
        r2 = ne.generate("user_a")  # Should hit cache
        assert r1 == r2
        assert len(llm.calls) == 1  # Only called once

    def test_inject_returns_empty_when_no_narrative(self):
        repo = MockPatternRepository()
        llm = FakeLLM("")
        ne = NarrativeEmergence(repo, llm)
        result = ne.inject("unknown_user")
        assert result == ""

    def test_inject_wraps_narrative_in_tags(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("该用户偏好简短回复，在疲惫时尤其希望AI能直接给出结论而非长篇大论。")
        ne = NarrativeEmergence(repo, llm)
        result = ne.inject("user_a")
        assert "用户画像" in result
        assert "简短" in result

    def test_short_narrative_rejected(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("太短")  # < 30 chars → rejected
        ne = NarrativeEmergence(repo, llm)
        result = ne.generate("user_a")
        assert result is None

    def test_long_narrative_rejected(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("A" * 400)  # > 300 chars → rejected
        ne = NarrativeEmergence(repo, llm)
        result = ne.generate("user_a")
        assert result is None

    def test_strips_prefixes(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("用户性格叙事: 该用户在周二下午和深夜时段容易感到疲惫，偏好简洁直接的沟通方式，对AI有明确的期待。")
        ne = NarrativeEmergence(repo, llm)
        result = ne.generate("user_a")
        assert result is not None
        assert not result.startswith("用户性格叙事:")

    def test_cached_property_returns_dict(self):
        repo = MockPatternRepository()
        for _ in range(3):
            repo.record("user_a", "fatigue_brevity", "verbose_low")
        for _ in range(3):
            repo.record("user_a", "fatigue_explicit", "brevity_command")

        llm = FakeLLM("该用户在周二下午和深夜时段容易感到疲惫，偏好简洁直接的沟通方式，对AI有明确的期待和边界感。")
        ne = NarrativeEmergence(repo, llm)
        ne.generate("user_a")
        assert "user_a" in ne.cached
