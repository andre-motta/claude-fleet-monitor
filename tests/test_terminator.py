import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.terminal_apis import (
    capture_terminal_info,
    detect_terminal,
    tmux,
)
from claude_fleet_monitor.terminal_apis.terminator import TerminatorAPI
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from tests.terminal_env import clear_terminal_markers

TERMINATOR_ENV = {
    "TERMINATOR_UUID": "urn:uuid:00000000-0000-4000-8000-000000000000",
    "TERMINATOR_DBUS_NAME": "net.tenshu.Terminator2abc",
    "TERMINATOR_DBUS_PATH": "/net/tenshu/Terminator2",
}
TMUX_ENV = {"TMUX": "/tmp/fleet,socket,4400,7"}


def _forbid_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Terminator must not start a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def _process(pid, ppid, name):
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=name,
        executable="python3" if name == "terminator" else name,
        argv=("/usr/bin/python3", "/usr/bin/terminator")
        if name == "terminator"
        else (name,),
        cwd=None,
        start_token="1",
    )


def test_terminator_uuid_alone_detects_terminator(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("TERMINATOR_UUID", TERMINATOR_ENV["TERMINATOR_UUID"])

    assert detect_terminal().name == "terminator"


def test_empty_terminator_uuid_is_not_terminator(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("TERMINATOR_UUID", "")

    assert detect_terminal().name == "generic"


@pytest.mark.parametrize(
    ("marker", "value", "expected"),
    [
        ("KONSOLE_VERSION", "260402", "konsole"),
        ("GNOME_TERMINAL_SERVICE", ":1.2", "gnome"),
    ],
)
def test_inherited_markers_keep_precedence(monkeypatch, marker, value, expected):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("TERMINATOR_UUID", TERMINATOR_ENV["TERMINATOR_UUID"])
    monkeypatch.setenv(marker, value)

    assert detect_terminal().name == expected


def test_capture_env_returns_exactly_the_three_keys(monkeypatch):
    clear_terminal_markers(monkeypatch)
    for name, value in TERMINATOR_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TERMINATOR_OTHER", "ignored")

    info = capture_terminal_info()

    assert info == {"terminal": "terminator", "terminal_env": TERMINATOR_ENV}


def test_capture_env_fills_unset_and_oversized_keys_with_empty(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("TERMINATOR_UUID", TERMINATOR_ENV["TERMINATOR_UUID"])
    monkeypatch.setenv("TERMINATOR_DBUS_NAME", "x" * 1025)

    assert TerminatorAPI.capture_env() == {
        "TERMINATOR_UUID": TERMINATOR_ENV["TERMINATOR_UUID"],
        "TERMINATOR_DBUS_NAME": "",
        "TERMINATOR_DBUS_PATH": "",
    }


def test_focus_result_reports_honest_unsupported_failure(monkeypatch):
    _forbid_subprocess(monkeypatch)

    result = TerminatorAPI().focus_result(101, dict(TERMINATOR_ENV))

    assert result.state == "failed"
    assert result.backend == "terminator"
    assert not result.target_found
    assert not result.selection.attempted
    assert not result.selection.succeeded
    assert result.selection.detail == (
        "backend does not support exact tab or pane selection"
    )
    assert not result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == "backend does not support window activation"


def test_tmux_parent_walk_stops_at_terminator(monkeypatch):
    processes = {
        200: _process(200, 150, "tmux: client"),
        150: _process(150, 100, "bash"),
        100: _process(100, 50, "terminator"),
        50: _process(50, 1, "ghostty"),
    }
    calls = []
    monkeypatch.setattr(
        tmux.discovery,
        "get_process_info",
        lambda pid: calls.append(pid) or processes.get(pid),
    )

    parent = tmux._detect_parent_terminal(200)

    assert isinstance(parent, TerminatorAPI)
    assert calls == [200, 150, 100]


def test_tmux_raise_window_in_terminator_calls_no_other_backend(monkeypatch):
    processes = {
        200: _process(200, 150, "tmux: client"),
        150: _process(150, 100, "bash"),
        100: _process(100, 50, "terminator"),
        50: _process(50, 1, "ghostty"),
    }
    monkeypatch.setattr(tmux.discovery, "get_process_info", processes.get)
    commands = []
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command)
        or SimpleNamespace(stdout="200\t$7\t@12\t%34\t0\n", returncode=0),
    )
    monkeypatch.setattr(
        tmux.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("no process may be started"),
    )
    for method in ("switch_tab", "raise_window"):
        monkeypatch.setattr(
            TerminatorAPI,
            method,
            lambda *args, **kwargs: pytest.fail("Terminator cannot focus"),
        )

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert len(commands) == 1
    assert commands[0][-5:] == ["list-clients", "-t", "$7", "-F", tmux._CLIENT_FORMAT]
