"""V3 Mock Implementations — in-memory, zero-dependency test doubles."""

from __future__ import annotations


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
