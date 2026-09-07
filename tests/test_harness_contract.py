import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.models import SCHEMA_VERSION, canonical_session_id


def make_record(
    harness="claude", session="session-1", instance="101:20", sequence=None
):
    canonical = canonical_session_id(harness, session, instance)
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "session",
        "canonical_id": canonical,
        "session_id": session,
        "instance_id": instance,
        "harness_id": harness,
        "agent": harness,
        "repo": "repo",
        "cwd": "/tmp/repo",
        "pid": "101",
        "process_start": "20",
        "status": "running",
        "detail": "working",
        "tool": "",
        "ts": int(time.time()),
        "started": int(time.time()),
        "source": "hook",
        "terminal": "generic",
        "terminal_env": {},
        "focus_target": {
            "kind": "terminal", "terminal": "generic", "terminal_env": {}
        },
    }
    if sequence is not None:
        record["sequence"] = sequence
    return record


def test_registry_declares_process_identity_and_capabilities():
    from claude_fleet_monitor.harnesses import ProcessIdentity, get_harness
    assert get_harness("claude").process_identity is ProcessIdentity.DISCOVERABLE
    assert "terminal-focus" in get_harness("codex").capabilities
    assert get_harness("pi").process_identity is ProcessIdentity.EMITTER
    assert get_harness("unknown") is None


def test_hostile_native_id_never_becomes_a_path(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    hostile = "../../outside/\N{SNOWMAN}"
    record = make_record(session=hostile)
    assert write_session_record(record)
    paths = list(fleet_dir.glob("*.json"))
    assert len(paths) == 1
    assert paths[0].parent == fleet_dir
    assert hostile not in paths[0].name
    assert read_stored_sessions()[0]["session_id"] == hostile


def test_mixed_harnesses_with_same_native_id_are_distinct(fleet_dir, monkeypatch):
    from claude_fleet_monitor.discovery import read_sessions, write_session_record
    monkeypatch.setattr(
        "claude_fleet_monitor.discovery.discover_processes", lambda: None
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.discovery._cleanup_stale_sessions", lambda: None
    )
    claude = make_record("claude", "same", "101:20")
    codex = make_record("codex", "same", "202:30")
    codex["pid"] = "202"
    codex["process_start"] = "30"
    assert write_session_record(claude)
    assert write_session_record(codex)
    sessions = read_sessions()
    assert {(item["harness_id"], item["session_id"]) for item in sessions} == {
        ("claude", "same"), ("codex", "same")
    }


def test_symlink_record_is_ignored_and_never_followed(fleet_dir, tmp_path):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    target = tmp_path / "target.json"
    target.write_text('{"sentinel": true}')
    link = fleet_dir / "legacy.json"
    link.symlink_to(target)
    assert read_stored_sessions() == []

    record = make_record()
    digest = record["canonical_id"].rsplit(":", 1)[-1]
    destination = fleet_dir / f"fleet-v1-{digest}.json"
    destination.symlink_to(target)
    assert not write_session_record(record)
    assert target.read_text() == '{"sentinel": true}'


def test_oversized_and_malformed_records_are_ignored(fleet_dir):
    from claude_fleet_monitor.discovery import (
        MAX_RECORD_BYTES,
        read_stored_sessions,
        write_session_record,
    )
    valid = make_record(session="valid")
    assert write_session_record(valid)
    (fleet_dir / "large.json").write_bytes(b"{" + b"x" * MAX_RECORD_BYTES + b"}")
    (fleet_dir / "bad.json").write_text('{"session_id": 4}')
    (fleet_dir / "bad-status.json").write_text(json.dumps({
        "session_id": "bad", "status": ["running"], "ts": 1
    }))
    (fleet_dir / "bad-unicode.json").write_text(
        '{"session_id":"\\ud800","status":"idle","ts":1}'
    )
    (fleet_dir / "huge-integer.json").write_text(
        '{"session_id":"probe","ts":' + "9" * 5000 + "}"
    )
    bad_target = make_record(session="bad-target")
    bad_target["focus_target"]["kind"] = []
    assert not write_session_record(bad_target)
    assert [record["session_id"] for record in read_stored_sessions()] == ["valid"]


def test_schema_one_record_requires_derived_id_and_filename(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions

    wrong_id = make_record(session="wrong-id")
    wrong_id["canonical_id"] = canonical_session_id(
        "claude", "different", wrong_id["instance_id"]
    )
    wrong_id_digest = canonical_session_id(
        "claude", "wrong-id", wrong_id["instance_id"]
    ).rsplit(":", 1)[-1]
    (fleet_dir / f"fleet-v1-{wrong_id_digest}.json").write_text(
        json.dumps(wrong_id)
    )

    wrong_path = make_record(session="wrong-path")
    (fleet_dir / f"fleet-v1-{'0' * 64}.json").write_text(
        json.dumps(wrong_path)
    )
    assert read_stored_sessions() == []


def test_explicit_sequence_rejects_replay_and_out_of_order(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    newest = make_record(sequence=2)
    newest["detail"] = "newest"
    stale = make_record(sequence=1)
    stale["detail"] = "stale"
    unsequenced = make_record()
    assert write_session_record(newest)
    assert not write_session_record(stale)
    assert not write_session_record(newest)
    assert not write_session_record(unsequenced)
    stored = read_stored_sessions()[0]
    assert stored["sequence"] == 2
    assert stored["detail"] == "newest"


def test_instance_token_cannot_move_to_another_process(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    original = make_record(sequence=1)
    moved = make_record(sequence=2)
    moved["pid"] = "202"
    moved["process_start"] = "30"
    assert write_session_record(original)
    assert not write_session_record(moved)
    assert read_stored_sessions()[0]["pid"] == "101"


def test_unsequenced_events_use_serialized_arrival_order(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    first = make_record()
    first["detail"] = "first"
    second = make_record()
    second["detail"] = "second"
    assert write_session_record(first)
    assert write_session_record(second)
    stored = read_stored_sessions()[0]
    assert stored["arrival_sequence"] == 2
    assert stored["detail"] == "second"


def test_concurrent_sequenced_writers_keep_highest_event(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    barrier = threading.Barrier(12)

    def emit(sequence):
        record = make_record(sequence=sequence)
        record["detail"] = str(sequence)
        barrier.wait()
        return write_session_record(record)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(emit, range(1, 13)))
    stored = read_stored_sessions()[0]
    assert stored["sequence"] == 12
    assert stored["detail"] == "12"


def test_atomic_readers_never_observe_partial_json(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    assert write_session_record(make_record(sequence=0))
    failures = []

    def read_repeatedly():
        for _ in range(100):
            records = read_stored_sessions()
            if len(records) != 1 or records[0].get("session_id") != "session-1":
                failures.append(records)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(read_repeatedly)
        for sequence in range(1, 101):
            record = make_record(sequence=sequence)
            record["detail"] = "x" * (sequence % 100)
            assert write_session_record(record)
        reader.result()
    assert failures == []


def test_denied_replace_preserves_known_record(fleet_dir, monkeypatch):
    from claude_fleet_monitor.discovery import read_stored_sessions, write_session_record
    first = make_record(sequence=1)
    assert write_session_record(first)
    update = make_record(sequence=2)
    update["detail"] = "must not appear"
    monkeypatch.setattr(
        "claude_fleet_monitor.discovery.os.replace",
        lambda *args: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert not write_session_record(update)
    stored = read_stored_sessions()[0]
    assert stored["sequence"] == 1
    assert stored["detail"] == "working"


def test_process_match_uses_executable_identity_not_arguments():
    from claude_fleet_monitor.discovery import process_matches_harness
    unrelated = ProcessInfo(
        1, 0, "python", "python3", ("python3", "--label", "claude"), "/tmp", "1"
    )
    exact = ProcessInfo(2, 0, "claude", "node", ("node",), "/tmp", "1")
    assert not process_matches_harness(unrelated, "claude")
    assert process_matches_harness(exact, "claude")


def test_explicit_instance_rejects_reused_pid(monkeypatch):
    from claude_fleet_monitor.discovery import resolve_session_process
    process = ProcessInfo(101, 1, "claude", "claude", ("claude",), "/tmp", "new")
    monkeypatch.setattr(
        "claude_fleet_monitor.discovery.get_process_info", lambda pid: process
    )
    assert resolve_session_process({
        "pid": "101", "agent": "claude", "instance_id": "old-run",
        "process_start": "old",
    }) is None


def test_windows_liveness_uses_read_only_process_query(monkeypatch):
    from claude_fleet_monitor.discovery import _is_pid_alive
    monkeypatch.setattr("claude_fleet_monitor.discovery.sys.platform", "win32")
    monkeypatch.setattr(
        "claude_fleet_monitor.discovery.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {
            "stdout": '"claude.exe","101","Console","1","1 K"\n',
            "returncode": 0,
        })(),
    )
    monkeypatch.setattr(
        os, "kill", lambda *args: pytest.fail("os.kill must not run on Windows")
    )
    assert _is_pid_alive("101")


def test_legacy_record_without_agent_defaults_to_claude(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions
    (fleet_dir / "legacy.json").write_text(json.dumps({
        "session_id": "legacy", "cwd": "/tmp/repo", "repo": "repo",
        "status": "idle", "detail": "", "ts": int(time.time()),
        "started": int(time.time()), "pid": "",
    }))
    assert read_stored_sessions()[0]["harness_id"] == "claude"


def test_legacy_records_cannot_inject_canonical_identity(fleet_dir):
    from claude_fleet_monitor.discovery import read_stored_sessions
    from claude_fleet_monitor.models import parse_session

    for index, session_id in enumerate(("legacy-a", "legacy-b")):
        (fleet_dir / f"legacy-{index}.json").write_text(json.dumps({
            "session_id": session_id,
            "agent": "codex",
            "harness_id": "pi",
            "canonical_id": "fleet:v1:claude:collision",
            "instance_id": "injected",
            "cwd": "/tmp/repo",
            "status": "idle",
            "ts": 1,
        }))
    records = read_stored_sessions()
    assert {parse_session(record).identity for record in records} == {
        "legacy-a", "legacy-b"
    }
    assert all("canonical_id" not in record for record in records)
    assert {record["harness_id"] for record in records} == {"codex"}


def test_record_lookup_rejects_invalid_identifier_text(fleet_dir):
    from claude_fleet_monitor.discovery import (
        delete_session_record,
        read_session_record,
    )

    assert read_session_record("claude", "\ud800", "instance") is None
    assert not delete_session_record("claude", "session", [])


def test_terminal_focus_reports_partial_and_boolean_compatibility():
    from claude_fleet_monitor.terminal_apis.base import TerminalAPI

    class WindowOnly(TerminalAPI):
        name = "window-only"
        selection_supported = False
        detect = staticmethod(lambda: False)
        capture_env = staticmethod(dict)
        find_tab = lambda self, pid, env: "target"
        switch_tab = lambda self, target, env: False
        raise_window = lambda self, target, env: True

    result = WindowOnly().focus_result(101, {})
    assert result.state == "partial"
    assert not result.complete
    assert not result.selection.attempted
    assert result.activation.succeeded
    assert WindowOnly().focus(101, {}) is True


def test_terminal_target_lookup_exception_is_structured():
    from claude_fleet_monitor.terminal_apis.base import TerminalAPI

    class BrokenLookup(TerminalAPI):
        name = "broken"
        detect = staticmethod(lambda: False)
        capture_env = staticmethod(dict)

        def find_tab(self, pid, env):
            raise FileNotFoundError("missing integration command")

        switch_tab = lambda self, target, env: True
        raise_window = lambda self, target, env: True

    result = BrokenLookup().focus_result(101, {})
    assert result.state == "failed"
    assert not result.target_found
    assert "missing integration command" in result.selection.detail


def test_focus_does_not_fallback_from_captured_terminal(monkeypatch):
    from claude_fleet_monitor.focus import focus_session
    session = make_record()
    session["terminal"] = "missing-terminal"
    session["focus_target"]["terminal"] = "missing-terminal"
    session["_process"] = False
    session["_legacy"] = False
    process = ProcessInfo(101, 1, "claude", "claude", ("claude",), "/tmp", "20")
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.read_session_records", lambda: [session]
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.resolve_session_process", lambda value: process
    )
    result = focus_session("session-1")
    assert result.state == "unavailable"
    assert result.backend == "missing-terminal"


def test_ambiguous_native_session_id_reports_ambiguity(monkeypatch):
    from claude_fleet_monitor.focus import focus_session
    claude = make_record("claude", "shared", "101:20")
    codex = make_record("codex", "shared", "202:30")
    for record in (claude, codex):
        record["_process"] = False
        record["_legacy"] = False
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.read_session_records", lambda: [claude, codex]
    )
    result = focus_session("shared")
    assert result.state == "ambiguous"
    assert not result.successful
    assert claude["canonical_id"] in result.reason
    assert codex["canonical_id"] in result.reason


def test_normalized_emitter_event_requires_sequence_and_namespace(
    fleet_dir, monkeypatch
):
    from claude_fleet_monitor.hook import handle
    process = ProcessInfo(303, 1, "node", "node", ("node",), "/tmp/repo", "40")
    monkeypatch.setattr(
        "claude_fleet_monitor.hook.resolve_process_identity",
        lambda harness, pid=None: process,
    )
    payload = {
        "schema_version": 1,
        "event_id": "pi.session-start",
        "session_id": "pi-native",
        "instance_id": "extension-process-token",
        "sequence": 1,
        "pid": 303,
        "cwd": "/tmp/repo",
        "status": "started",
        "detail": "session started",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert handle("fleet-event", "pi")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert not handle("fleet-event", "pi")


def test_emitter_instance_named_unresolved_is_not_deleted(fleet_dir, monkeypatch):
    from claude_fleet_monitor.discovery import read_session_records
    from claude_fleet_monitor.hook import handle

    process = ProcessInfo(303, 1, "node", "node", ("node",), "/tmp/repo", "40")
    monkeypatch.setattr(
        "claude_fleet_monitor.hook.resolve_process_identity",
        lambda harness, pid=None: process,
    )
    payload = {
        "schema_version": 1,
        "event_id": "pi.session-start",
        "session_id": "pi-native",
        "instance_id": "unresolved",
        "sequence": 1,
        "pid": 303,
        "cwd": "/tmp/repo",
        "status": "started",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert handle("fleet-event", "pi")
    assert read_session_records()[0]["instance_id"] == "unresolved"
    assert read_session_records()[0]["process_identity"] == "identified"
    payload["event_id"] = "claude.session-start"
    payload["sequence"] = 2
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert not handle("fleet-event", "pi")


def test_cli_quotes_hook_executable_with_spaces(monkeypatch):
    from claude_fleet_monitor.cli import _install_hooks
    monkeypatch.setattr("claude_fleet_monitor.cli.os.name", "posix")
    config = {}
    _install_hooks(config, [("SessionStart", "session-start")], "/opt/Fleet App/hook", "claude")
    command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert command == "'/opt/Fleet App/hook' session-start --agent claude"


def test_cli_quotes_windows_hook_executable(monkeypatch):
    from claude_fleet_monitor.cli import _install_hooks
    monkeypatch.setattr("claude_fleet_monitor.cli.os.name", "nt")
    config = {}
    _install_hooks(
        config,
        [("SessionStart", "session-start")],
        r"C:\Program Files\Fleet\hook.exe",
        "codex",
    )
    command = config["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith('"C:\\Program Files\\Fleet\\hook.exe"')
