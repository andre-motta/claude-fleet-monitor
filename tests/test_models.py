"""Tests for models.py."""

import time

from claude_fleet_monitor.models import (
    FleetSession,
    SessionStatus,
    format_age,
    parse_session,
)


class TestSessionStatus:
    def test_all_statuses(self):
        for val in ("started", "running", "idle", "waiting", "error", "ended", "discovered"):
            assert SessionStatus(val).value == val

    def test_invalid_status_raises(self):
        import pytest
        with pytest.raises(ValueError):
            SessionStatus("bogus")


class TestParseSession:
    def test_minimal_dict(self):
        s = parse_session({"session_id": "abc", "repo": "myrepo", "cwd": "/tmp/myrepo"})
        assert s.session_id == "abc"
        assert s.repo == "myrepo"
        assert s.status == SessionStatus.DISCOVERED

    def test_full_dict(self):
        now = int(time.time())
        data = {
            "session_id": "s1",
            "repo": "proj",
            "cwd": "/home/user/proj",
            "status": "running",
            "detail": "processing prompt",
            "ts": now,
            "started": now - 60,
            "pid": "12345",
            "terminal": "konsole",
            "terminal_env": {"KONSOLE_DBUS_SERVICE": "org.kde.konsole-1234"},
            "source": "hook",
            "tool": "Bash",
            "age_seconds": 30,
            "needs_attention": False,
        }
        s = parse_session(data)
        assert s.status == SessionStatus.RUNNING
        assert s.pid == "12345"
        assert s.terminal == "konsole"
        assert s.tool == "Bash"
        assert s.age_seconds == 30
        assert not s.needs_attention

    def test_unknown_status_falls_back(self):
        s = parse_session({"status": "unknown_state"})
        assert s.status == SessionStatus.DISCOVERED

    def test_pid_coerced_to_string(self):
        s = parse_session({"pid": 9999})
        assert s.pid == "9999"

    def test_empty_dict(self):
        s = parse_session({})
        assert s.session_id == ""
        assert s.source == "hook"

    def test_frozen(self):
        import pytest
        s = parse_session({"session_id": "x"})
        with pytest.raises(AttributeError):
            s.session_id = "y"


class TestFormatAge:
    def test_seconds(self):
        assert format_age(45) == "45s"

    def test_minutes(self):
        assert format_age(150) == "2m"

    def test_hours(self):
        assert format_age(3700) == "1h1m"

    def test_zero(self):
        assert format_age(0) == "0s"

    def test_exact_hour(self):
        assert format_age(3600) == "1h0m"
