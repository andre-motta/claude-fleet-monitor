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
    from claude_fleet_monitor.discovery import ProcessInfo
    import claude_fleet_monitor.focus as focus_module
    from claude_fleet_monitor.focus import get_pid
    process = ProcessInfo(
        12345, 1, "claude", "claude", ("claude",), "/tmp/myrepo", "1"
    )
    original = focus_module.resolve_session_process
    focus_module.resolve_session_process = lambda value: process
    session = {"session_id": "proc-12345", "pid": "12345", "cwd": "/tmp/myrepo"}
    try:
        assert get_pid(session) == 12345
    finally:
        focus_module.resolve_session_process = original


def test_get_pid_from_stored_pid(fleet_dir, monkeypatch):
    from claude_fleet_monitor.discovery import ProcessInfo
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.resolve_session_process",
        lambda value: ProcessInfo(
            os.getpid(), 1, "claude", "claude", ("claude",), value["cwd"], "1"
        ),
    )
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": str(os.getpid()), "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result == os.getpid()


def test_get_pid_dead_stored_pid(fleet_dir, monkeypatch):
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.resolve_session_process", lambda value: None
    )
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": "999999", "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result is None
