"""V3 Mock Implementations — in-memory, zero-dependency test doubles."""

from __future__ import annotations


class MockPatternRepository:
    """In-memory PatternRepository for fast unit tests."""

    def __init__(self) -> None:
        self._patterns: dict[str, list[dict]] = {}  # user_id → [pattern_rows]

    def record(
        self, user_id: str, behavior: str, action: str,
        success: bool = True, tags: str = "",
    ) -> bool:
        self._patterns.setdefault(user_id, [])
        for p in self._patterns[user_id]:
            if (p["behavior"] == behavior and p["action"] == action
                    and p["tags"] == tags):
                p["count"] += 1
                if success:
                    p["success"] += 1
                return False
        self._patterns[user_id].append({
            "tags": tags, "behavior": behavior, "action": action,
            "count": 1, "success": 1 if success else 0,
        })
        return True

    def query_active(
        self, user_id: str, min_occurrence: int = 3,
        min_confidence: float = 0.8,
    ) -> list[dict]:
        results = []
        for p in self._patterns.get(user_id, []):
            if p["count"] >= min_occurrence:
                conf = p["success"] / p["count"]
                if conf >= min_confidence:
                    results.append({
                        "context": p["tags"],
                        "behavior": p["behavior"],
                        "action": p["action"],
                        "occurrence": p["count"],
                        "confidence": round(conf, 3),
                    })
        return results

    def generate_hint(self, user_id: str) -> str | None:
        patterns = self.query_active(user_id)
        if patterns:
            p = patterns[0]
            return f"[关系预判] ({p['confidence']:.0%}) {p['behavior']} → {p['action']}"
        return None

    def decay_all(self, user_id: str, days: int = 28) -> int:
        # Mock: no time tracking, just reduce success by 1
        count = 0
        for p in self._patterns.get(user_id, []):
            if p["success"] > 0:
                p["success"] -= 1
                count += 1
        return count


class MockSemanticTrustDetector:
    """Controllable SemanticTrustDetector for testing."""

    def __init__(self, fixed_response: dict | None = None) -> None:
        self._fixed = fixed_response or {"dimension": None, "score": 0.0, "all_scores": {}}
        self._calls: list[str] = []

    def detect(self, text: str) -> dict:
        self._calls.append(text)
        return dict(self._fixed)

    def set_response(self, dim: str | None, score: float) -> None:
        self._fixed = {
            "dimension": dim, "score": score,
            "all_scores": {"fatigue": score if dim == "fatigue" else 0.3,
                           "frustration": score if dim == "frustration" else 0.3},
        }

    @property
    def dimensions(self) -> list[str]:
        return ["fatigue", "frustration", "gratitude", "curiosity"]

    @property
    def call_count(self) -> int:
        return len(self._calls)


class MockToolRegistry:
    """In-memory ToolRegistry for testing."""

    def __init__(self, tools: dict | None = None) -> None:
        self._tools: dict = dict(tools or {})

    def get_contract(self, tool_name: str) -> dict | None:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def register(self, name: str, contract: dict) -> None:
        self._tools[name] = contract
