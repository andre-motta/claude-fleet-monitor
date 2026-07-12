import io
import json
import time

from tests.conftest import write_session


def run_hook(monkeypatch, fleet_dir, event, stdin_data):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin_data)))
    monkeypatch.setattr("claude_fleet_monitor.hook._find_claude_pid", lambda: "12345")
    monkeypatch.setattr("claude_fleet_monitor.terminal_apis.capture_terminal_info",
                        lambda: {"terminal": "test", "terminal_env": {"TEST": "1"}})
    from claude_fleet_monitor.hook import handle
    handle(event)


def test_session_start(fleet_dir, monkeypatch):
    run_hook(monkeypatch, fleet_dir, "session-start", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "started"
    assert data["repo"] == "myrepo"
    assert data["pid"] == "12345"
    assert data["terminal"] == "test"
    assert data["terminal_env"] == {"TEST": "1"}


def test_prompt_submit_creates_new(fleet_dir, monkeypatch):
    run_hook(monkeypatch, fleet_dir, "prompt-submit", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "running"
    assert data["detail"] == "processing prompt"


def test_prompt_submit_updates_existing(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "prompt-submit", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "running"


def test_tool_use(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "tool-use", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "tool_name": "Bash"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "running"
    assert data["detail"] == "using Bash"
    assert data["tool"] == "Bash"


def test_stop(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "stop", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo",
        "last_assistant_message": "Fixed the bug"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "idle"
    assert data["detail"] == "Fixed the bug"


def test_stop_truncates_long_message(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    long_msg = "x" * 200
    run_hook(monkeypatch, fleet_dir, "stop", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo",
        "last_assistant_message": long_msg
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert len(data["detail"]) <= 124


def test_stop_failure(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "stop-failure", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "error"


def test_permission_request(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "permission-request", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "tool_name": "Bash"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "waiting"
    assert "permission needed" in data["detail"]


def test_elicitation(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "elicitation", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "waiting"
    assert "user input" in data["detail"]


def test_session_end(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, fleet_dir, "session-end", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["status"] == "ended"


def test_tool_use_backfills_pid(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="")
    run_hook(monkeypatch, fleet_dir, "tool-use", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "tool_name": "Read"
    })
    data = json.loads((fleet_dir / "test-sess.json").read_text())
    assert data["pid"] == "12345"
