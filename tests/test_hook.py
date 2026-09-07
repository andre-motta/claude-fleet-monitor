import io
import json

from claude_fleet_monitor.discovery import ProcessInfo
from tests.conftest import write_session


def read_new_record(fleet_dir):
    paths = list(fleet_dir.glob("fleet-v1-*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


def run_hook(monkeypatch, event, stdin_data, agent="claude", process_start="100"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(stdin_data)))
    process = ProcessInfo(
        pid=12345,
        ppid=1,
        name=agent,
        executable=agent,
        argv=(agent,),
        cwd=stdin_data.get("cwd"),
        start_token=process_start,
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.hook.resolve_process_identity",
        lambda value, supplied=None: process,
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.capture_terminal_info",
        lambda: {"terminal": "test", "terminal_env": {"TEST": "1"}},
    )
    from claude_fleet_monitor.hook import handle
    return handle(event, agent)


def test_session_start(fleet_dir, monkeypatch):
    assert run_hook(monkeypatch, "session-start", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = read_new_record(fleet_dir)
    assert data["status"] == "started"
    assert data["repo"] == "myrepo"
    assert data["pid"] == "12345"
    assert data["instance_id"] == "12345:100"
    assert data["schema_version"] == 1
    assert data["canonical_id"].startswith("fleet:v1:claude:")
    assert data["terminal"] == "test"
    assert data["terminal_env"] == {"TEST": "1"}
    assert data["agent"] == "claude"


def test_codex_session_start(fleet_dir, monkeypatch):
    run_hook(monkeypatch, "session-start", {
        "session_id": "thr_123", "cwd": "/tmp/myrepo"
    }, agent="codex")
    data = read_new_record(fleet_dir)
    assert data["agent"] == "codex"
    assert data["status"] == "started"


def test_prompt_submit_creates_new(fleet_dir, monkeypatch):
    run_hook(monkeypatch, "prompt-submit", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    data = read_new_record(fleet_dir)
    assert data["status"] == "running"
    assert data["detail"] == "processing prompt"


def test_prompt_submit_migrates_legacy_record(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "prompt-submit", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    assert read_new_record(fleet_dir)["status"] == "running"


def test_tool_use(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "tool-use", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "tool_name": "Bash"
    })
    data = read_new_record(fleet_dir)
    assert data["status"] == "running"
    assert data["detail"] == "using Bash"
    assert data["tool"] == "Bash"


def test_stop(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "stop", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo",
        "last_assistant_message": "Fixed the bug"
    })
    data = read_new_record(fleet_dir)
    assert data["status"] == "idle"
    assert data["detail"] == "Fixed the bug"


def test_stop_truncates_long_message(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "stop", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo",
        "last_assistant_message": "x" * 200,
    })
    assert len(read_new_record(fleet_dir)["detail"]) <= 123


def test_stop_failure(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "stop-failure", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    assert read_new_record(fleet_dir)["status"] == "error"


def test_permission_request(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "permission-request", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "tool_name": "Bash"
    })
    data = read_new_record(fleet_dir)
    assert data["status"] == "waiting"
    assert "permission needed" in data["detail"]


def test_elicitation(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "elicitation", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    assert "user input" in read_new_record(fleet_dir)["detail"]


def test_session_end(fleet_dir, monkeypatch):
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo", pid="12345")
    run_hook(monkeypatch, "session-end", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    assert read_new_record(fleet_dir)["status"] == "ended"


def test_unknown_event_does_not_touch_store(fleet_dir, monkeypatch):
    assert not run_hook(monkeypatch, "future-event", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo"
    })
    assert list(fleet_dir.iterdir()) == []


def test_malformed_payload_preserves_record(fleet_dir, monkeypatch):
    legacy = fleet_dir / "test-sess.json"
    write_session(fleet_dir, "test-sess", "myrepo", "/tmp/myrepo")
    before = legacy.read_bytes()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id":'))
    from claude_fleet_monitor.hook import handle
    assert not handle("prompt-submit")
    assert legacy.read_bytes() == before


def test_oversized_payload_is_rejected(fleet_dir, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(" " * (64 * 1024 + 1)))
    from claude_fleet_monitor.hook import handle
    assert not handle("session-start")
    assert list(fleet_dir.iterdir()) == []


def test_future_timestamp_cannot_replace_known_state(fleet_dir, monkeypatch):
    run_hook(monkeypatch, "session-start", {
        "session_id": "test-sess", "cwd": "/tmp/myrepo", "sequence": 1
    })
    before = read_new_record(fleet_dir)
    accepted = run_hook(monkeypatch, "prompt-submit", {
        "session_id": "test-sess",
        "cwd": "/tmp/myrepo",
        "sequence": 2,
        "ts": before["ts"] + 1000,
    })
    assert not accepted
    assert read_new_record(fleet_dir) == before


def test_missing_platform_start_token_reuses_random_instance(fleet_dir, monkeypatch):
    payload = {"session_id": "test-sess", "cwd": "/tmp/myrepo"}
    assert run_hook(monkeypatch, "session-start", payload, process_start="")
    first = read_new_record(fleet_dir)
    assert run_hook(monkeypatch, "prompt-submit", payload, process_start="")
    second = read_new_record(fleet_dir)
    assert second["instance_id"] == first["instance_id"]
    assert second["status"] == "running"


def test_lone_surrogate_identifier_is_rejected(fleet_dir, monkeypatch):
    assert not run_hook(monkeypatch, "session-start", {
        "session_id": "\ud800", "cwd": "/tmp/myrepo"
    })
    assert list(fleet_dir.iterdir()) == []
