"""Conformance tests: Critic Engine (Phase 16).

Verifies the StubCriticEngine emits correct trace_context keys
with proper types, including critic.* keys and agent.identity.
"""

from __future__ import annotations

import asyncio

import pytest

from core.observability.trace_registry import TRACE_KEY_REGISTRY
from engines.critic.identity import CriticAgent


async def _collect():
    from engines.critic.stub import StubCriticEngine

    engine = StubCriticEngine()
    items = []
    async for item in engine.evaluate():
        items.append(item)
    return items


# ── TestCriticStubOutput ────────────────────────────────────────────────


class TestCriticStubOutput:
    """Verify the critic stub produces correct StreamItems."""

    def test_produces_three_items(self):
        items = asyncio.run(_collect())
        assert len(items) == 3, f"Expected 3 items, got {len(items)}"

    def test_critic_score_present_on_all_items(self):
        items = asyncio.run(_collect())
        for i, item in enumerate(items):
            assert "critic.score" in item.trace_context, (
                f"Item {i}: missing critic.score"
            )

    def test_critic_verdict_present_on_all_items(self):
        items = asyncio.run(_collect())
        for i, item in enumerate(items):
            assert "critic.verdict" in item.trace_context, (
                f"Item {i}: missing critic.verdict"
            )

    def test_agent_identity_present(self):
        items = asyncio.run(_collect())
        for i, item in enumerate(items):
            assert "agent.identity" in item.trace_context, (
                f"Item {i}: missing agent.identity"
            )

    def test_last_item_is_terminal(self):
        items = asyncio.run(_collect())
        assert items[-1].is_terminal, "Last item should be terminal"
        assert items[-1].finish_reason == "stop"


# ── TestCriticTraceKeyTypes ─────────────────────────────────────────────


class TestCriticTraceKeyTypes:
    """Verify critic trace key types match registry definitions."""

    def test_score_is_float(self):
        items = asyncio.run(_collect())
        for item in items:
            score = item.trace_context["critic.score"]
            assert isinstance(score, float), (
                f"critic.score should be float, got {type(score)}"
            )

    def test_verdict_is_valid_string(self):
        items = asyncio.run(_collect())
        valid = {"accept", "reject", "rework"}
        for item in items:
            verdict = item.trace_context["critic.verdict"]
            assert verdict in valid, (
                f"critic.verdict should be one of {valid}, got {verdict}"
            )

    def test_agent_identity_is_dict(self):
        items = asyncio.run(_collect())
        for item in items:
            identity = item.trace_context["agent.identity"]
            assert isinstance(identity, dict), (
                f"agent.identity should be dict, got {type(identity)}"
            )

    def test_agent_identity_role_is_critic(self):
        items = asyncio.run(_collect())
        for item in items:
            identity = item.trace_context["agent.identity"]
            assert identity["role"] == "critic", (
                f"Expected role='critic', got {identity['role']}"
            )


# ── TestCriticKeyRegistration ───────────────────────────────────────────


class TestCriticKeyRegistration:
    """Verify critic.* keys are properly registered."""

    def test_critic_score_in_registry(self):
        assert "critic.score" in TRACE_KEY_REGISTRY, "critic.score missing from registry"

    def test_critic_verdict_in_registry(self):
        assert "critic.verdict" in TRACE_KEY_REGISTRY, "critic.verdict missing from registry"

    def test_both_critic_keys_engine_is_critic(self):
        for key in ("critic.score", "critic.verdict"):
            assert "critic" in TRACE_KEY_REGISTRY[key].engines, (
                f"{key} engines should include 'critic', got {TRACE_KEY_REGISTRY[key].engines}"
            )

    def test_critic_keys_not_component_candidates(self):
        for key in ("critic.score", "critic.verdict"):
            assert TRACE_KEY_REGISTRY[key].component_candidate == False, (
                f"{key} should not be component_candidate"
            )

    def test_agent_identity_registered_to_critic(self):
        """Phase 17: agent.identity is multi-engine, includes critic."""
        assert "agent.identity" in TRACE_KEY_REGISTRY
        key_def = TRACE_KEY_REGISTRY["agent.identity"]
        assert "critic" in key_def.engines, (
            f"agent.identity engines={key_def.engines}, expected 'critic' to be included"
        )


# ── TestCriticAgentIdentity ─────────────────────────────────────────────


class TestCriticAgentIdentity:
    """Verify CriticAgent follows the agent.* namespace convention."""

    def test_default_agent_has_expected_fields(self):
        agent = CriticAgent(
            id="critic-v1",
            role="critic",
            version="1.0.0",
        )
        trace_value = agent.to_trace_value()
        assert trace_value["id"] == "critic-v1"
        assert trace_value["role"] == "critic"
        assert trace_value["version"] == "1.0.0"
        assert isinstance(trace_value["capabilities"], list)

    def test_to_trace_value_and_back(self):
        agent = CriticAgent(
            id="critic-v2",
            role="critic",
            version="2.0.0",
            capabilities=("result_evaluation", "quality_scoring"),
        )
        trace_value = agent.to_trace_value()
        restored = CriticAgent.from_trace_value(trace_value)
        assert restored.id == agent.id
        assert restored.role == agent.role
        assert restored.version == agent.version
        assert restored.capabilities == agent.capabilities

    def test_stub_engine_uses_default_agent(self):
        from engines.critic.stub import StubCriticEngine

        engine = StubCriticEngine()
        assert engine._agent.id == "critic-v1"
        assert engine._agent.role == "critic"

    def test_stub_engine_accepts_custom_agent(self):
        from engines.critic.stub import StubCriticEngine

        custom = CriticAgent(
            id="custom-critic",
            role="critic",
            version="3.0.0",
            capabilities=("strict_evaluation",),
        )
        engine = StubCriticEngine(agent=custom)
        assert engine._agent.id == "custom-critic"
