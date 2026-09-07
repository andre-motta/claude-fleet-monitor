import os
from pathlib import Path
from types import SimpleNamespace


def test_linux_process_info_parses_identity(monkeypatch):
    from claude_fleet_monitor import discovery

    fields = ["S", "42"] + ["0"] * 17 + ["987654"]

    def read_text(path):
        if path.name == "stat":
            return f"123 (claude) {' '.join(fields)}"
        if path.name == "comm":
            return "claude\n"
        raise AssertionError(path)

    monkeypatch.setattr(discovery.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "read_bytes", lambda path: b"claude\0--flag\0")
    monkeypatch.setattr(
        os,
        "readlink",
        lambda path: (
            "/usr/local/bin/claude"
            if str(path).endswith("/exe")
            else "/tmp/repo"
        ),
    )
    process = discovery.get_process_info(123)
    assert process == discovery.ProcessInfo(
        pid=123,
        ppid=42,
        name="claude",
        executable="claude",
        argv=("claude", "--flag"),
        cwd="/tmp/repo",
        start_token="987654",
    )


def test_macos_process_info_parses_identity(monkeypatch):
    from claude_fleet_monitor import discovery

    def run(command, **kwargs):
        if command[:3] == ["ps", "-o", "ppid="]:
            return SimpleNamespace(
                returncode=0,
                stdout="42 /usr/local/bin/claude claude --flag\n",
            )
        if command[0] == "lsof":
            return SimpleNamespace(returncode=0, stdout="p123\nfcwd\nn/tmp/repo\n")
        if command[:3] == ["ps", "-o", "lstart="]:
            return SimpleNamespace(
                returncode=0, stdout="Mon Sep  7 10:00:00 2026\n"
            )
        raise AssertionError(command)

    monkeypatch.setattr(discovery.sys, "platform", "darwin")
    monkeypatch.setattr(discovery.subprocess, "run", run)
    process = discovery.get_process_info(123)
    assert process.ppid == 42
    assert process.executable == "claude"
    assert process.argv == ("claude", "--flag")
    assert process.cwd == "/tmp/repo"
    assert process.start_token == "Mon Sep  7 10:00:00 2026"


def test_macos_process_info_rejects_failed_query(monkeypatch):
    from claude_fleet_monitor import discovery

    monkeypatch.setattr(discovery.sys, "platform", "darwin")
    monkeypatch.setattr(
        discovery.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert discovery.get_process_info(123) is None


def test_windows_process_info_has_explicit_limitations(monkeypatch):
    from claude_fleet_monitor import discovery

    monkeypatch.setattr(discovery.sys, "platform", "win32")
    monkeypatch.setattr(
        discovery.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='"codex.exe","123","Console","1","1 K"\n',
        ),
    )
    process = discovery.get_process_info(123)
    assert process.name == "codex.exe"
    assert process.ppid is None
    assert process.cwd is None
    assert process.start_token == ""


def test_ancestor_walk_requires_exact_process_identity(monkeypatch):
    from claude_fleet_monitor import discovery

    processes = {
        500: discovery.ProcessInfo(
            500, 400, "bash", "bash", ("bash", "claude"), "/tmp", "1"
        ),
        400: discovery.ProcessInfo(
            400, 300, "python", "python", ("python",), "/tmp", "2"
        ),
        300: discovery.ProcessInfo(
            300, 1, "codex", "codex", ("codex",), "/tmp", "3"
        ),
    }
    monkeypatch.setattr(
        discovery, "get_process_info", lambda pid: processes.get(pid)
    )
    process = discovery.find_ancestor_process("codex", 500)
    assert process.pid == 300
    assert discovery.find_ancestor_process("claude", 500) is None
