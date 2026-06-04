"""SQLiteProfile tests — WAL mode, migration, concurrent-safe."""

import os
import tempfile
from core.adapters.sqlite_profile import SQLiteProfile


class TestSQLiteProfile:
    def test_session_tracking(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            p = SQLiteProfile("user_a", db_path=db)
            assert p.session_count == 0
            sid = p.start_session()
            assert sid == 1
            assert p.session_count == 1
            p.save()
            p.close()

            # Reload
            p2 = SQLiteProfile("user_a", db_path=db)
            assert p2.session_count == 1
            p2.close()
        finally:
            os.unlink(db)

    def test_record_modification(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            p = SQLiteProfile("user_b", db_path=db)
            p.start_session()
            p.record_modification("response_verbose_level", "LOW")
            p.record_modification("tone_style", "PRAGMATIC")
            p.save()
            p.close()

            p2 = SQLiteProfile("user_b", db_path=db)
            assert p2.sessions_modified("response_verbose_level") >= 1
            assert p2.sessions_modified("tone_style") >= 1
            p2.close()
        finally:
            os.unlink(db)

    def test_trust_delta_recorded(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            p = SQLiteProfile("user_c", db_path=db)
            p.start_session()
            p.record_trust_delta(0.15)
            p.record_trust_delta(0.10)  # Keeps max absolute
            p.save()
            p.close()

            p2 = SQLiteProfile("user_c", db_path=db)
            td = p2._data.get("session_trust_delta", {})
            assert "1" in td
            assert td["1"] >= 0.15
            p2.close()
        finally:
            os.unlink(db)

    def test_multiple_users_independent(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            a = SQLiteProfile("user_a", db_path=db)
            a.start_session()
            a.record_modification("verbose", "LOW")
            a.save()
            a.close()

            b = SQLiteProfile("user_b", db_path=db)
            assert b.session_count == 0
            assert b.sessions_modified("verbose") == 0
            b.close()
        finally:
            os.unlink(db)

    def test_wal_mode_enabled(self):
        db = tempfile.mktemp(suffix=".db")
        try:
            p = SQLiteProfile("test", db_path=db)
            mode = p._conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
            p.close()
        finally:
            os.unlink(db)
