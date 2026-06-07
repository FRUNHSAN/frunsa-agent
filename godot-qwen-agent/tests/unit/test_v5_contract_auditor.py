"""V5 Contract Auditor Tests — validates "contract as Markov blanket" principle.

Core V5 invariants:
  1. Auditor MUST NOT directly modify Blueprint fields (only detect + report)
  2. Proposals pass through ContractEvolutionEngine gate (trust, constitution, schema)
  3. Circuit breaker prevents cascading LLM failures
  4. Rejection log fed into auditor (System 2 learns from past rejections)
"""

import json
import time

import pytest

CT = "12:00"


class _MockLLM:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        return self.response if self.response is not None else '{"has_proposal": false}'


class _FailingLLM:
    def generate(self, prompt):
        raise RuntimeError("LLM unavailable")


def _call(auditor, history, blueprint, **kw):
    return auditor._audit_sync(
        history=history, blueprint=blueprint,
        current_time=kw.pop("current_time", CT),
        schema=kw.pop("schema", None),
        rejection_log=kw.pop("rejection_log", None),
    )


class TestNoDirectModification:
    def test_audit_returns_proposal_does_not_modify_blueprint(self):
        from core.adapters.contract_auditor import ContractAuditor

        llm = _MockLLM(json.dumps({
            "has_proposal": True, "proposal": {
                "trigger_condition": "user_exhausted",
                "target_blueprint_key": "response_verbose_level",
                "old_value": "HIGH", "new_value": "LOW",
                "human_reason": "User is tired.",
            },
        }))
        auditor = ContractAuditor(llm)
        bp = {"response_verbose_level": "HIGH"}
        result = _call(auditor, ["test1", "test2"], bp)
        assert result is not None
        assert result["new_value"] == "LOW"
        assert bp["response_verbose_level"] == "HIGH"

    def test_no_proposal_returns_none(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM('{"has_proposal": false}'))
        result = _call(auditor, ["test"], {"response_verbose_level": "HIGH"})
        assert result is None

    def test_async_uses_callback(self):
        from core.adapters.contract_auditor import ContractAuditor

        received = []
        llm = _MockLLM(json.dumps({
            "has_proposal": True, "proposal": {
                "trigger_condition": "t", "target_blueprint_key": "response_verbose_level",
                "old_value": "HIGH", "new_value": "MEDIUM", "human_reason": "T.",
            },
        }))
        auditor = ContractAuditor(llm)
        auditor.audit_async(
            history=["test"], current_blueprint={"response_verbose_level": "HIGH"},
            callback=lambda p: received.append(p),
        )
        time.sleep(0.5)
        assert len(received) == 1
        assert received[0]["new_value"] == "MEDIUM"


class TestCircuitBreaker:
    def test_three_failures_open_circuit(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_FailingLLM(), interval=1)
        for i in range(3):
            r = _call(auditor, [f"m{i}"], {"response_verbose_level": "HIGH"})
            assert r is None
        assert auditor.should_audit(1) is False

    def test_circuit_resets_after_pause(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_FailingLLM(), interval=1)
        auditor._breaker_pause = 2
        for _ in range(3):
            _call(auditor, ["x"], {"response_verbose_level": "HIGH"})
        assert auditor.should_audit(1) is False
        auditor.should_audit(1)
        auditor.should_audit(1)
        assert auditor._circuit_open is False

    def test_success_resets_failure_counter(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_FailingLLM(), interval=1)
        for _ in range(2):
            _call(auditor, ["x"], {"response_verbose_level": "HIGH"})
        assert auditor._consecutive_failures == 2
        auditor._llm = _MockLLM('{"has_proposal": false}')
        _call(auditor, ["ok"], {"response_verbose_level": "HIGH"})
        assert auditor._consecutive_failures == 0

    def test_open_circuit_blocks_audit(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM(), interval=2)
        auditor._circuit_open = True
        auditor._circuit_reset_rounds = 5
        assert auditor.should_audit(2) is False
        assert auditor.should_audit(4) is False


class TestSchemaInjection:
    def test_schema_in_prompt(self):
        from core.adapters.contract_auditor import ContractAuditor

        llm = _MockLLM()
        auditor = ContractAuditor(llm)
        _call(auditor, ["test"], {"response_verbose_level": "HIGH"},
              schema={"response_verbose_level": {"type": "enum", "values": ["HIGH", "LOW"]}})
        assert "response_verbose_level" in llm.calls[0]
        assert "allowed_values" in llm.calls[0]

    def test_rejection_log_in_prompt(self):
        from core.adapters.contract_auditor import ContractAuditor

        llm = _MockLLM()
        auditor = ContractAuditor(llm)
        _call(auditor, ["test"], {"response_verbose_level": "HIGH"},
              rejection_log=[{"key": "verbose", "reason": "Cooldown"}])
        assert "rejected" in llm.calls[0].lower() or "拒绝" in llm.calls[0]

    def test_history_in_prompt(self):
        from core.adapters.contract_auditor import ContractAuditor

        llm = _MockLLM()
        auditor = ContractAuditor(llm)
        _call(auditor, ["hello", "why JOIN"], {"response_verbose_level": "HIGH"})
        assert "hello" in llm.calls[0]
        assert "why JOIN" in llm.calls[0]


class TestMalformedResponse:
    def test_non_json_counts_as_failure(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM("not json at all"))
        result = _call(auditor, ["test"], {"response_verbose_level": "HIGH"})
        assert result is None
        assert auditor._consecutive_failures == 1

    def test_code_fence_json_parsed(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM('```json\n{"has_proposal": false}\n```'))
        result = _call(auditor, ["test"], {"response_verbose_level": "HIGH"})
        assert result is None
        assert auditor._consecutive_failures == 0

    def test_missing_proposal_key(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM('{"has_proposal": true}'))
        result = _call(auditor, ["test"], {"response_verbose_level": "HIGH"})
        assert result is None


class TestAuditScheduling:
    def test_should_audit_intervals(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM(), interval=5)
        assert auditor.should_audit(0) is False
        assert auditor.should_audit(5) is True
        assert auditor.should_audit(6) is False
        assert auditor.should_audit(10) is True

    def test_call_count_increments(self):
        from core.adapters.contract_auditor import ContractAuditor

        auditor = ContractAuditor(_MockLLM(), interval=1)
        assert auditor.call_count == 0
        # call_count incremented by audit_async, not _audit_sync
        auditor.audit_async(
            history=["test"], current_blueprint={"response_verbose_level": "HIGH"},
            callback=lambda p: None,
        )
        time.sleep(0.3)
        assert auditor.call_count == 1
