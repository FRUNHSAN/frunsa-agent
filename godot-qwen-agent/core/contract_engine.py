"""ContractEngine — PLAN8 SDK: 5-line integration for contract-bound agents.

Usage:
    from core.contract_engine import ContractEngine

    engine = ContractEngine(profile="user_123")

    @engine.tool(risk="DESTRUCTIVE", min_trust=0.8)
    def delete_logs():
        os.system("rm -rf /var/log/*")

    with engine.session() as session:
        session.execute(delete_logs)
        # → ContractViolation if trust < 0.8
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.tool_contract import RiskLevel, TOOLS as _TOOLS


class ContractViolation(Exception):
    """Raised when a tool execution violates the contract."""
    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"[Contract] '{tool_name}' blocked: {reason}")
        self.tool_name = tool_name
        self.reason = reason


@dataclass
class _RegisteredTool:
    fn: Callable
    risk: RiskLevel
    min_trust: float
    require_hitl: bool
    category: str


class ContractEngine:
    """Main entry point for contract-bound agent systems.

    Holds Blueprint, UserProfile, and ActionPipeline.
    Provides tool registration and session management.
    """

    def __init__(self, profile: str = "default") -> None:
        self.profile = UserProfile.load(profile)
        self._bp = DynamicBlueprint(blueprint_defaults())
        self._pipeline = ActionPipeline(self._bp, trust=0.30)
        self._tools: dict[str, _RegisteredTool] = {}

    def tool(
        self,
        risk: str = "read",
        min_trust: float = 0.0,
        require_hitl: bool = False,
        category: str = "general",
    ) -> Callable:
        """Register a function as a contract-bound tool.

        Usage:
            @engine.tool(risk="DESTRUCTIVE", min_trust=0.8, require_hitl=True)
            def restart_server():
                ...
        """
        risk_level = RiskLevel(risk)

        def decorator(fn: Callable) -> Callable:
            self._tools[fn.__name__] = _RegisteredTool(
                fn=fn, risk=risk_level, min_trust=min_trust,
                require_hitl=require_hitl, category=category,
            )
            # Register into the shared tool registry so ActionPipeline can see it
            _TOOLS[fn.__name__] = {
                "name": fn.__name__,
                "description": fn.__doc__ or "",
                "risk_level": risk_level,
                "min_trust": min_trust,
                "require_hitl": require_hitl,
                "category": category,
            }
            return fn
        return decorator

    @contextmanager
    def session(self):
        """Context manager for contract-bound execution sessions."""
        session = _ContractSession(self)
        try:
            yield session
        finally:
            self.profile.save()

    @property
    def trust(self) -> float:
        return self._pipeline.trust

    @trust.setter
    def trust(self, value: float) -> None:
        self._pipeline.trust = max(0.0, min(1.0, value))

    @property
    def blueprint(self) -> DynamicBlueprint:
        return self._bp


class _ContractSession:
    def __init__(self, engine: ContractEngine) -> None:
        self._engine = engine
        self._pipeline = engine._pipeline

    def execute(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a registered tool with contract enforcement.

        Raises ContractViolation if the tool is blocked.
        """
        name = fn.__name__
        result = self._pipeline.check(name)
        if not result["allowed"]:
            raise ContractViolation(name, result["reason"])

        try:
            ret = fn(*args, **kwargs)
            self._pipeline.record_result(name, success=True)
            return ret
        except Exception:
            self._pipeline.record_result(name, success=False)
            raise
