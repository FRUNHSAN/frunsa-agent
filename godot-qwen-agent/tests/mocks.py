"""V3 Mock Implementations — in-memory, zero-dependency test doubles."""

from __future__ import annotations


class MockSemanticTrustDetector:
    """Controllable SemanticTrustDetector for testing — V7.7 extended."""

    def __init__(self, fixed_response: dict | None = None) -> None:
        self._fixed = fixed_response or {"dimension": None, "score": 0.0, "all_scores": {}}
        self._calls: list[str] = []
        # V7.7: command classification state
        self._cmd_fixed: dict | None = None
        self._cmd_candidates: list[dict] = []
        self._amb_flag: bool = False
        self._null_region: bool = False
        self._gap_region: bool = False
        self._confidence: float = 0.0

    # ── V5.3: existing API ──

    def detect(self, text: str) -> dict:
        self._calls.append(text)
        return dict(self._fixed)

    def set_response(self, dim: str | None, score: float) -> None:
        self._fixed = {
            "dimension": dim, "score": score,
            "all_scores": {"fatigue": score if dim == "fatigue" else 0.3,
                           "frustration": score if dim == "frustration" else 0.3,
                           "gratitude": score if dim == "gratitude" else 0.3,
                           "curiosity": score if dim == "curiosity" else 0.3},
        }

    @property
    def dimensions(self) -> list[str]:
        return ["fatigue", "frustration", "gratitude", "curiosity"]

    @property
    def call_count(self) -> int:
        return len(self._calls)

    # ── V7.7: sheaf-theoretic observer API ──

    def observe(self, text: str):
        """Return a dict mimicking ObservationResult for testing."""
        self._calls.append(text)
        return {
            "emotion": dict(self._fixed),
            "command": self._cmd_fixed,
            "command_candidates": self._cmd_candidates,
            "ambiguity": self._amb_flag and not self._null_region,
            "null_region": self._null_region,
            "confidence": self._confidence,
            "gap_region": self._gap_region,
        }

    def classify_command(self, text: str) -> dict | None:
        """Mimic SemanticTrustEngine.classify_command()."""
        self._calls.append(text)
        return self._cmd_fixed

    def set_command(self, key: str | None, value: str | None, score: float = 0.8) -> None:
        """Set what classify_command / observe should return as the best command."""
        if key and value:
            self._cmd_fixed = {"key": key, "value": value, "score": score}
        else:
            self._cmd_fixed = None

    def set_ambiguity(self, candidates: list[dict], ambiguity: bool = True) -> None:
        """Set ambiguity state for observe() returns."""
        self._cmd_candidates = candidates
        self._cmd_fixed = candidates[0] if candidates else None
        self._amb_flag = ambiguity

    def set_null_region(self, null_region: bool = True) -> None:
        """Set null_region state."""
        self._null_region = null_region
        if null_region:
            self._cmd_fixed = None

    def set_gap_region(self, gap: bool = True) -> None:
        """Set gap_region state."""
        self._gap_region = gap

    def set_confidence(self, confidence: float) -> None:
        """Set confidence level."""
        self._confidence = confidence

    @property
    def model(self):
        """Mock has no real model — returns None."""
        return None


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
