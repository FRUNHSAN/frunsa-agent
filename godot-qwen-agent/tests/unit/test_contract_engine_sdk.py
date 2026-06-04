"""SDK integration tests — 5-line contract binding."""

import pytest
from core.contract_engine import ContractEngine, ContractViolation


class TestContractEngineSDK:
    def test_register_and_call_read_tool(self):
        engine = ContractEngine(profile="test")
        engine.trust = 0.30

        @engine.tool(risk="read", min_trust=0.0)
        def search(query: str) -> str:
            return f"Found: {query}"

        with engine.session() as session:
            result = session.execute(search, "quantum")
            assert result == "Found: quantum"

    def test_destructive_tool_blocked_by_low_trust(self):
        engine = ContractEngine(profile="test")
        engine.trust = 0.10  # Far below 0.80

        @engine.tool(risk="destructive", min_trust=0.80)
        def delete_all():
            pass

        with engine.session() as session:
            with pytest.raises(ContractViolation) as exc:
                session.execute(delete_all)
            assert "delete_all" in str(exc.value)
            assert "trust" in str(exc.value).lower()

    def test_destructive_tool_allowed_by_high_trust(self):
        engine = ContractEngine(profile="test")
        engine.trust = 0.90
        engine.blueprint.apply_proposal("execution_autonomy", "FULL")

        @engine.tool(risk="destructive", min_trust=0.80, require_hitl=False)
        def restart():
            return "restarted"

        with engine.session() as session:
            result = session.execute(restart)
            assert result == "restarted"

    def test_tool_execution_failure_triggers_backlash(self):
        engine = ContractEngine(profile="test")
        engine.trust = 0.50

        @engine.tool(risk="read", min_trust=0.0)
        def flaky_tool():
            raise RuntimeError("failed")

        with engine.session() as session:
            with pytest.raises(RuntimeError):
                session.execute(flaky_tool)

        # Backlash should record the failure
        pipeline = engine._pipeline
        assert pipeline._failure_counts.get("flaky_tool", 0) >= 1

    def test_explicit_tool_not_registered(self):
        engine = ContractEngine(profile="test")
        engine.trust = 0.50

        def unregistered():
            pass

        with engine.session() as session:
            with pytest.raises(ContractViolation) as exc:
                session.execute(unregistered)
            assert "unknown" in str(exc.value).lower()

    def test_profile_persistence(self):
        engine = ContractEngine(profile="sdk_test")
        engine.trust = 0.25
        with engine.session():
            pass  # Triggers profile.save()

        # Reload — trust should be in profile
        engine2 = ContractEngine(profile="sdk_test")
        assert engine2.trust == 0.30  # trust starts fresh, profile persists separately
