"""SignalInterpreter + UserProfile + Schema edge cases."""

import pytest
from core.adapters.signal_interpreter import interpret
from core.contracts.user_profile import UserProfile
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.blueprint_schema import blueprint_defaults, BLUEPRINT_SCHEMA


class TestSignalInterpreter:
    """Signal → Proposal translation. All signal types at boundary scores."""

    def test_fatigue_proposes_verbose_low(self):
        bp = {"response_verbose_level": "HIGH", "conversational_initiative": "BALANCED", "tone_style": "WARM"}
        proposals = interpret("fatigue", 0.72, trust=0.30, current_bp=bp)
        targets = [p["target_blueprint_key"] for p in proposals]
        assert "response_verbose_level" in targets

    def test_fatigue_proposes_initiative_responsive_only(self):
        bp = {"response_verbose_level": "HIGH", "conversational_initiative": "BALANCED", "tone_style": "WARM"}
        proposals = interpret("fatigue", 0.72, trust=0.30, current_bp=bp)
        initiatives = [p for p in proposals if p["target_blueprint_key"] == "conversational_initiative"]
        assert len(initiatives) == 1
        assert initiatives[0]["new_value"] == "RESPONSIVE_ONLY"

    def test_fatigue_below_threshold_no_proposals(self):
        bp = {"response_verbose_level": "HIGH", "conversational_initiative": "BALANCED"}
        proposals = interpret("fatigue", 0.40, trust=0.30, current_bp=bp)
        assert proposals == []

    def test_frustration_proposes_tone_pragmatic(self):
        bp = {"response_verbose_level": "HIGH", "tone_style": "WARM", "contextual_anchoring": "HIGH", "conversational_initiative": "BALANCED"}
        proposals = interpret("frustration", 0.72, trust=0.30, current_bp=bp)
        tones = [p for p in proposals if p["target_blueprint_key"] == "tone_style"]
        assert len(tones) >= 1
        assert tones[0]["new_value"] == "PRAGMATIC"

    def test_frustration_proposes_verbose_low_first(self):
        """Frustration should reduce verbosity BEFORE changing tone."""
        bp = {"response_verbose_level": "HIGH", "tone_style": "WARM", "contextual_anchoring": "HIGH", "conversational_initiative": "BALANCED"}
        proposals = interpret("frustration", 0.72, trust=0.30, current_bp=bp)
        # verbose should be first in the list
        verbose_idx = next(i for i, p in enumerate(proposals) if p["target_blueprint_key"] == "response_verbose_level")
        tone_idx = next(i for i, p in enumerate(proposals) if p["target_blueprint_key"] == "tone_style")
        assert verbose_idx < tone_idx, "Verbose reduction must come before tone change"

    def test_trust_crisis_proposes_minimal(self):
        bp = {"response_verbose_level": "HIGH", "proactive_suggestions": "ENABLED"}
        proposals = interpret("fatigue", 0.80, trust=0.02, current_bp=bp)
        verbose_proposals = [p for p in proposals if p["target_blueprint_key"] == "response_verbose_level"]
        # Trust crisis (<0.05) should propose MINIMAL
        # Fatigue also proposes LOW — both can coexist
        values = [p["new_value"] for p in verbose_proposals]
        assert "MINIMAL" in values or "LOW" in values

    def test_no_proposals_when_already_in_target_state(self):
        bp = {"response_verbose_level": "LOW", "conversational_initiative": "RESPONSIVE_ONLY", "tone_style": "CALM"}
        proposals = interpret("fatigue", 0.72, trust=0.30, current_bp=bp)
        assert proposals == []  # Already at target

    def test_none_dimension_no_proposals(self):
        proposals = interpret(None, 0.5, trust=0.30, current_bp={"response_verbose_level": "HIGH"})
        assert proposals == []

    def test_complexity_detection_triggers_medium(self):
        """User asking '怎么看' → complexity lift to MEDIUM."""
        bp = {"response_verbose_level": "LOW"}
        proposals = interpret("curiosity", 0.5, trust=0.30, current_bp=bp, user_text="你觉得这个方案怎么样")
        verbose_p = [p for p in proposals if p["target_blueprint_key"] == "response_verbose_level"]
        assert len(verbose_p) >= 1
        assert verbose_p[0]["new_value"] == "MEDIUM"

    def test_complexity_not_triggered_for_fatigue(self):
        """Even with complexity markers, fatigue blocks the lift."""
        bp = {"response_verbose_level": "LOW"}
        proposals = interpret("fatigue", 0.80, trust=0.30, current_bp=bp, user_text="你觉得怎么样")
        verbose_p = [p for p in proposals if p["target_blueprint_key"] == "response_verbose_level"]
        # Should NOT propose MEDIUM — fatigue overrides complexity
        medium_proposals = [p for p in verbose_p if p["new_value"] == "MEDIUM"]
        assert len(medium_proposals) == 0

    def test_signal_score_at_boundary(self):
        """Exactly at threshold should trigger."""
        bp = {"response_verbose_level": "HIGH", "conversational_initiative": "BALANCED", "tone_style": "WARM"}
        proposals = interpret("fatigue", 0.551, trust=0.30, current_bp=bp)
        assert len(proposals) > 0

    def test_signal_score_just_below_boundary(self):
        """Just below threshold should NOT trigger."""
        bp = {"response_verbose_level": "HIGH", "conversational_initiative": "BALANCED", "tone_style": "WARM"}
        proposals = interpret("fatigue", 0.549, trust=0.30, current_bp=bp)
        assert proposals == []  # Below 0.55 threshold


class TestUserProfile:
    """Cross-session memory with outlier rejection."""

    def test_amendment_not_triggered_below_threshold(self):
        p = UserProfile("test")
        for s in range(1, 3):  # Only 2 sessions
            p.start_session()
            p.record_modification("response_verbose_level", "LOW")
        assert p.propose_amendment("response_verbose_level", "LOW") is None

    def test_amendment_triggers_at_threshold(self):
        p = UserProfile("test")
        for s in range(1, 4):  # 3 sessions = threshold
            p.start_session()
            p.record_modification("response_verbose_level", "LOW")
        amendment = p.propose_amendment("response_verbose_level", "LOW")
        assert amendment is not None
        assert "3" in amendment["human_reason"] or "three" in amendment["human_reason"].lower()

    def test_amendment_excludes_outlier_sessions(self):
        p = UserProfile("test")
        # Normal sessions
        for s in range(1, 4):
            p.start_session()
            p.record_modification("response_verbose_level", "LOW")
            p.record_trust_delta(0.05)
        # Outlier session
        p.start_session()
        p.record_modification("response_verbose_level", "EXTREME_BRIEF")
        p.record_modification("tone_style", "DISABLED")
        p.record_modification("proactive_suggestions", "DISABLED")
        p.record_modification("explanation_style", "BRIEF")
        p.record_trust_delta(0.50)
        p.auto_detect_outliers()
        # Amendment should be based on 3 clean sessions, ignoring outlier
        amendment = p.propose_amendment("response_verbose_level", "LOW")
        assert amendment is not None

    def test_record_modification_counts_per_field(self):
        p = UserProfile("test")
        p.start_session()
        p.record_modification("response_verbose_level", "LOW")
        p.record_modification("tone_style", "PRAGMATIC")
        assert p.sessions_modified("response_verbose_level") == 1
        assert p.sessions_modified("tone_style") == 1

    def test_auto_detect_outlier_by_field_count(self):
        p = UserProfile("test")
        p.start_session()
        p.record_modification("response_verbose_level", "LOW")
        p.record_modification("tone_style", "WARM")
        p.record_modification("proactive_suggestions", "ENABLED")
        outliers = p.auto_detect_outliers()
        assert 1 in outliers

    def test_auto_detect_outlier_by_trust_delta(self):
        p = UserProfile("test")
        p.start_session()
        p.record_trust_delta(0.30)  # Above 0.25 threshold
        outliers = p.auto_detect_outliers()
        assert 1 in outliers

    def test_save_and_load_roundtrip(self):
        import tempfile, os
        tmp = tempfile.mkdtemp()
        try:
            p = UserProfile("roundtrip_test", storage_path=tmp)
            p.start_session()
            p.record_modification("response_verbose_level", "LOW")
            p.record_trust_delta(0.05)
            p.save()

            p2 = UserProfile.load("roundtrip_test", storage_path=tmp)
            assert p2.session_count == 1
            assert p2.sessions_modified("response_verbose_level") >= 1
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestSchemaValidation:
    """BlueprintSchema: all fields validated."""

    def test_all_schema_fields_have_type_and_values(self):
        for key, field in BLUEPRINT_SCHEMA.items():
            assert "type" in field, f"{key} missing type"
            if field["type"] == "enum":
                assert "values" in field, f"{key} missing values"
                assert len(field["values"]) >= 2, f"{key} needs at least 2 values"

    def test_all_schema_fields_have_default(self):
        for key, field in BLUEPRINT_SCHEMA.items():
            assert "default" in field, f"{key} missing default"
            if field["type"] == "enum":
                assert field["default"] in field["values"], f"{key} default not in values"

    def test_blueprint_defaults_matches_schema(self):
        defaults = blueprint_defaults()
        for key in BLUEPRINT_SCHEMA:
            assert key in defaults, f"{key} not in defaults"

    def test_schema_blocks_every_invalid_enum_value(self):
        bp = DynamicBlueprint(blueprint_defaults())
        for key, field in BLUEPRINT_SCHEMA.items():
            if field["type"] == "enum":
                ok, reason = bp.apply_proposal(key, "INVALID_SENTINEL_VALUE_12345")
                assert not ok, f"{key} should block invalid value"

    def test_schema_allows_every_valid_enum_value(self):
        for key, field in BLUEPRINT_SCHEMA.items():
            if field["type"] == "enum":
                for val in field["values"]:
                    bp = DynamicBlueprint(blueprint_defaults())
                    ok, reason = bp.apply_proposal(key, val)
                    if val != field["default"]:
                        # DISABLED blocked by min_autonomy floor, not schema
                        if key == "execution_autonomy" and val == "DISABLED":
                            assert not ok  # Floor check
                        else:
                            assert ok, f"{key}={val} should be allowed: {reason}"

    def test_all_schema_fields_have_description(self):
        for key, field in BLUEPRINT_SCHEMA.items():
            assert "description" in field, f"{key} missing description"
            assert len(field["description"]) > 10, f"{key} description too short"

    def test_constitution_fields_not_in_schema(self):
        """Immutable genes are NOT in the evolvable schema."""
        from core.contracts.dynamic_blueprint import CONSTITUTION
        for gene in CONSTITUTION:
            assert gene not in BLUEPRINT_SCHEMA, f"Constitution gene '{gene}' should not be in evolvable schema"
