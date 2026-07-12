import json
import time

from tests.conftest import write_session


def test_read_sessions_empty(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    from claude_fleet_monitor.discovery import read_sessions
    assert read_sessions() == []


def test_read_sessions_returns_hook_sessions(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo", pid="99999")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert len(sessions) == 1
    assert sessions[0]["repo"] == "myrepo"
    assert "age_seconds" in sessions[0]


def test_read_sessions_dedup_proc_vs_hook(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo", pid="12345")
    write_session(fleet_dir, "proc-12345", "myrepo", "/tmp/myrepo", source="process")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "abc-123"


def test_read_sessions_dedup_same_pid_keeps_newest(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    now = int(time.time())
    write_session(fleet_dir, "old-session", "myrepo", "/tmp/myrepo", pid="12345", ts=now - 100)
    write_session(fleet_dir, "new-session", "myrepo", "/tmp/myrepo", pid="12345", ts=now)
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "new-session"


def test_read_sessions_proc_shows_when_no_hook(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "proc-99999", "otherrepo", "/tmp/otherrepo", source="process")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "proc-99999"


def test_needs_attention_idle_over_2min(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    now = int(time.time())
    write_session(fleet_dir, "idle-old", "myrepo", "/tmp/myrepo",
                  status="idle", ts=now - 200, pid="99999")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert sessions[0]["needs_attention"] is True


def test_needs_attention_waiting_immediate(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "waiting-sess", "myrepo", "/tmp/myrepo",
                  status="waiting", pid="99999")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert sessions[0]["needs_attention"] is True


def test_needs_attention_running_false(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "running-sess", "myrepo", "/tmp/myrepo",
                  status="running", pid="99999")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert sessions[0]["needs_attention"] is False


def test_cleanup_removes_ended_sessions(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    now = int(time.time())
    write_session(fleet_dir, "ended-old", "myrepo", "/tmp/myrepo",
                  status="ended", ts=now - 400, pid="99999")
    from claude_fleet_monitor.discovery import _cleanup_stale_sessions
    _cleanup_stale_sessions()
    assert not (fleet_dir / "ended-old.json").exists()


def test_cleanup_keeps_recent_ended(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    import os
    write_session(fleet_dir, "ended-new", "myrepo", "/tmp/myrepo",
                  status="ended", pid=str(os.getpid()))
    from claude_fleet_monitor.discovery import _cleanup_stale_sessions
    _cleanup_stale_sessions()
    assert (fleet_dir / "ended-new.json").exists()


def test_cleanup_removes_no_pid_old(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    now = int(time.time())
    write_session(fleet_dir, "nopid-old", "myrepo", "/tmp/myrepo",
                  status="started", ts=now - 700, pid="")
    from claude_fleet_monitor.discovery import _cleanup_stale_sessions
    _cleanup_stale_sessions()
    assert not (fleet_dir / "nopid-old.json").exists()


def test_sessions_sorted_by_repo(fleet_dir, monkeypatch):
    monkeypatch.setattr("claude_fleet_monitor.discovery.discover_processes", lambda: None)
    monkeypatch.setattr("claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None)
    write_session(fleet_dir, "z-sess", "zrepo", "/tmp/zrepo", pid="11111")
    write_session(fleet_dir, "a-sess", "arepo", "/tmp/arepo", pid="22222")
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()
    assert sessions[0]["repo"] == "arepo"
    assert sessions[1]["repo"] == "zrepo"
