import json
import os

from tests.conftest import write_session


def test_find_session_by_repo(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result is not None
    assert result["repo"] == "myrepo"


def test_find_session_by_id(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("abc-123")
    assert result is not None
    assert result["session_id"] == "abc-123"


def test_find_session_no_match(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("nonexistent")
    assert result is None


def test_find_session_prefers_hook_over_proc(fleet_dir):
    write_session(fleet_dir, "hook-sess", "myrepo", "/tmp/myrepo")
    write_session(fleet_dir, "proc-99999", "myrepo", "/tmp/myrepo", source="process")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result["session_id"] == "hook-sess"


def test_find_session_multiple_returns_none(fleet_dir):
    write_session(fleet_dir, "sess-1", "myrepo", "/tmp/myrepo")
    write_session(fleet_dir, "sess-2", "myrepo", "/tmp/myrepo2")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result is None


def test_get_pid_from_proc_session(fleet_dir):
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "proc-12345", "cwd": "/tmp/myrepo"}
    assert get_pid(session) == 12345


def test_get_pid_from_stored_pid(fleet_dir, monkeypatch):
    monkeypatch.setattr("os.kill", lambda pid, sig: None)
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": str(os.getpid()), "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result == os.getpid()


def test_get_pid_dead_stored_pid(fleet_dir, monkeypatch):
    def fake_kill(pid, sig):
        raise OSError("no such process")
    monkeypatch.setattr("os.kill", fake_kill)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("R", (), {"stdout": "", "returncode": 1})())
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": "999999", "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result is None
