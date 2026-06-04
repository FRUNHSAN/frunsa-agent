"""RelationalPatterns tests — CBO model, decay, confidence, proactive hints."""

import os
import tempfile
import time
from core.adapters.relational_patterns import RelationalPatterns, _context_tags


class TestContextTags:
    def test_tags_are_non_empty(self):
        tags = _context_tags()
        assert len(tags) > 0
        assert "," in tags  # Multiple tags

    def test_tags_contain_time_period(self):
        tags = _context_tags()
        assert any(t in tags for t in ["morning", "afternoon", "evening", "night", "late_morning", "late_afternoon"])

    def test_tags_contain_weekday_or_weekend(self):
        tags = _context_tags()
        assert "weekday" in tags or "weekend" in tags


class TestRelationalPatterns:
    def test_record_new_pattern(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            created = rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                                tags="Tuesday,afternoon,weekday")
            assert created  # New pattern
            rp.close()
        finally:
            os.unlink(db)

    def test_record_duplicate_increments(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                      tags="Tuesday,afternoon")
            created = rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                                tags="Tuesday,afternoon")
            assert not created  # Duplicate
            rp.close()
        finally:
            os.unlink(db)

    def test_query_requires_min_occurrence(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for _ in range(2):  # Only 2 — below threshold of 3
                rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                          tags="Tuesday,afternoon,weekday")
            results = rp.query_active("frunhsan")
            assert len(results) == 0  # Below threshold
            rp.close()
        finally:
            os.unlink(db)

    def test_query_returns_above_threshold(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for _ in range(3):
                rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                          tags="Tuesday,afternoon,weekday")
            results = rp.query_active("frunhsan")
            assert len(results) >= 1
            rp.close()
        finally:
            os.unlink(db)

    def test_low_confidence_below_threshold(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for i in range(3):
                rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                          tags="Tuesday,afternoon,weekday", success=(i < 1))
            # 1 success out of 3 = 33% confidence
            results = rp.query_active("frunhsan", min_confidence=0.8)
            assert len(results) == 0
            rp.close()
        finally:
            os.unlink(db)

    def test_decay_reduces_success_on_old_patterns(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            # Manually insert old pattern
            rp._conn.execute(
                "INSERT INTO patterns (user_id, context_tags, behavior, action, "
                "occurrence_count, success_count, last_triggered) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("frunhsan", "Monday,morning,weekday", "fatigue_brevity",
                 "verbose_low", 5, 5, 0),  # 0 = epoch, very old
            )
            rp._conn.commit()
            decayed = rp.decay_all("frunhsan", days=28)
            assert decayed >= 1  # At least one row decayed
            rp.close()
        finally:
            os.unlink(db)

    def test_generate_hint_returns_none_when_no_patterns(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            hint = rp.generate_hint("unknown_user")
            assert hint is None
            rp.close()
        finally:
            os.unlink(db)

    def test_generate_hint_returns_string_when_pattern_exists(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for _ in range(3):
                rp.record("frunhsan", "fatigue_brevity", "verbose_low")
            hint = rp.generate_hint("frunhsan")
            assert hint is not None
            assert "关系预判" in hint
            rp.close()
        finally:
            os.unlink(db)

    def test_context_mismatch_skips_pattern(self):
        """Pattern with different context tags shouldn't match."""
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for _ in range(3):
                # Context that will NEVER match current time
                rp.record("frunhsan", "fatigue_brevity", "verbose_low",
                          tags="FakeDay,NonexistentTime")
            results = rp.query_active("frunhsan")
            assert len(results) == 0  # No context overlap
            rp.close()
        finally:
            os.unlink(db)

    def test_independent_per_user(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            rp = RelationalPatterns(db_path=db)
            for _ in range(3):
                rp.record("user_a", "fatigue_brevity", "verbose_low")
            # user_b should see no patterns
            hint = rp.generate_hint("user_b")
            assert hint is None
            rp.close()
        finally:
            os.unlink(db)
