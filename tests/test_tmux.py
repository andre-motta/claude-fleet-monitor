import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.terminal_apis import tmux
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI


TMUX_ENV = {"TMUX": "/tmp/fleet,socket,4400,7"}


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def process(pid, ppid, name="python"):
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=name,
        executable=name,
        argv=(name,),
        cwd=None,
        start_token="1",
    )


def test_find_tab_returns_stable_target_from_one_snapshot(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return completed("$7\t@12\t%34\t200\n")

    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert TmuxAPI().find_tab(200, TMUX_ENV) == "$7:@12.%34"
    assert len(calls) == 1
    assert calls[0][0] == [
        "tmux",
        "-S",
        "/tmp/fleet,socket",
        "list-panes",
        "-a",
        "-F",
        tmux._PANE_FORMAT,
    ]


def test_find_tab_walks_process_ancestry(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed("$7\t@12\t%34\t200\n"),
    )
    processes = {400: process(400, 300), 300: process(300, 200)}
    monkeypatch.setattr(
        tmux.discovery, "get_process_info", lambda pid: processes.get(pid)
    )

    assert TmuxAPI().find_tab(400, TMUX_ENV) == "$7:@12.%34"


def test_find_tab_prefers_captured_session_for_linked_window(monkeypatch):
    output = "$8\t@12\t%34\t200\n$7\t@12\t%34\t200\n"
    monkeypatch.setattr(
        tmux.subprocess, "run", lambda *args, **kwargs: completed(output)
    )

    assert TmuxAPI().find_tab(200, TMUX_ENV) == "$7:@12.%34"
    assert TmuxAPI().find_tab(200, {"TMUX": "/tmp/socket,4400,9"}) is None


def test_find_tab_stops_on_process_cycle(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess, "run", lambda *args, **kwargs: completed("$7\t@1\t%1\t20\n")
    )
    processes = {400: process(400, 300), 300: process(300, 400)}
    calls = []

    def get_process_info(pid):
        calls.append(pid)
        return processes.get(pid)

    monkeypatch.setattr(tmux.discovery, "get_process_info", get_process_info)

    assert TmuxAPI().find_tab(400, TMUX_ENV) is None
    assert calls == [400, 300]


@pytest.mark.parametrize(
    "result",
    [
        completed("not tmux output\n"),
        completed("$7\t@1\t%1\tinvalid\n"),
        completed("$7\t@1\t%1\t200\n", returncode=1),
    ],
)
def test_find_tab_rejects_malformed_or_failed_snapshot(monkeypatch, result):
    monkeypatch.setattr(tmux.subprocess, "run", lambda *args, **kwargs: result)

    assert TmuxAPI().find_tab(200, TMUX_ENV) is None


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), OSError(), subprocess.TimeoutExpired("tmux", 5)]
)
def test_find_tab_handles_command_errors(monkeypatch, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert TmuxAPI().find_tab(200, TMUX_ENV) is None


@pytest.mark.parametrize(
    "terminal_env",
    [
        {},
        {"TMUX": ""},
        {"TMUX": None},
        {"TMUX": 0},
        {"TMUX": "/tmp/socket,broken"},
    ],
)
@pytest.mark.parametrize(
    ("method", "arguments"),
    [
        ("find_tab", (200,)),
        ("switch_tab", ("$7:@12.%34",)),
        ("raise_window", ("$7:@12.%34",)),
    ],
)
def test_operations_require_valid_captured_tmux_environment(
    monkeypatch, terminal_env, method, arguments
):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("tmux must not be called"),
    )

    assert not getattr(TmuxAPI(), method)(*arguments, terminal_env)


def test_switch_tab_selects_and_verifies_stable_target(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        stdout = "$7:@12.%34\n" if "display-message" in command else ""
        return completed(stdout)

    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert TmuxAPI().switch_tab("$7:@12.%34", TMUX_ENV)
    assert calls == [
        ["tmux", "-S", "/tmp/fleet,socket", "select-window", "-t", "$7:@12"],
        ["tmux", "-S", "/tmp/fleet,socket", "select-pane", "-t", "$7:@12.%34"],
        [
            "tmux",
            "-S",
            "/tmp/fleet,socket",
            "display-message",
            "-p",
            "-t",
            "$7",
            "#{session_id}:#{window_id}.#{pane_id}",
        ],
    ]


def test_switch_tab_rejects_stale_window_after_pane_move(monkeypatch):
    def run(command, **kwargs):
        stdout = "$7:@99.%34\n" if "display-message" in command else ""
        return completed(stdout)

    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert not TmuxAPI().switch_tab("$7:@12.%34", TMUX_ENV)


def test_switch_tab_stops_after_failed_selection(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return completed(returncode=1 if "select-pane" in command else 0)

    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert not TmuxAPI().switch_tab("$7:@12.%34", TMUX_ENV)
    assert len(calls) == 2


@pytest.mark.parametrize("target", ["name:1.2", "$7:@12.34", "$8:@12.%34", ""])
def test_switch_tab_rejects_invalid_or_wrong_session_target(monkeypatch, target):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("tmux must not be called"),
    )

    assert not TmuxAPI().switch_tab(target, TMUX_ENV)


def test_raise_window_routes_only_exact_selected_client(monkeypatch):
    output = (
        "400\t$8\t@12\t%34\t0\n"
        "300\t$7\t@99\t%34\t0\n"
        "250\t$7\t@12\t%34\t1\n"
        "200\t$7\t@12\t%34\t0\n"
    )
    commands = []
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command) or completed(output),
    )
    calls = []

    class Parent:
        selection_supported = True

        def find_tab(self, pid, env):
            calls.append(("find", pid))
            return "parent-tab"

        def switch_tab(self, target, env):
            calls.append(("select", target))
            return True

        def raise_window(self, target, env):
            calls.append(("raise", target))
            return True

    monkeypatch.setattr(tmux, "_detect_parent_terminal", lambda pid: Parent())

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert commands[0][-5:] == ["list-clients", "-t", "$7", "-F", tmux._CLIENT_FORMAT]
    assert calls == [
        ("find", 200),
        ("select", "parent-tab"),
        ("raise", "parent-tab"),
    ]


def test_raise_window_requires_parent_selection_success(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed("200\t$7\t@12\t%34\t0\n"),
    )
    calls = []
    parent = SimpleNamespace(
        selection_supported=True,
        find_tab=lambda pid, env: "parent-tab",
        switch_tab=lambda target, env: calls.append("select") or False,
        raise_window=lambda target, env: calls.append("raise") or True,
    )
    monkeypatch.setattr(tmux, "_detect_parent_terminal", lambda pid: parent)

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert calls == ["select"]


def test_raise_window_allows_selection_unsupported_parent(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed("200\t$7\t@12\t%34\t0\n"),
    )
    calls = []
    parent = SimpleNamespace(
        selection_supported=False,
        find_tab=lambda pid, env: "window-1",
        switch_tab=lambda target, env: pytest.fail("selection is unsupported"),
        raise_window=lambda target, env: calls.append(target) or True,
    )
    monkeypatch.setattr(tmux, "_detect_parent_terminal", lambda pid: parent)

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert calls == ["window-1"]


@pytest.mark.parametrize(
    "result",
    [completed(), completed("malformed\n"), completed(returncode=1)],
)
def test_raise_window_fails_safely_without_eligible_clients(monkeypatch, result):
    monkeypatch.setattr(tmux.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: pytest.fail("no client may be routed"),
    )

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


def test_detect_parent_terminal_uses_shared_process_discovery(monkeypatch):
    processes = {
        200: process(200, 150, "tmux: client"),
        150: process(150, 100, "bash"),
        100: process(100, 1, "/usr/bin/konsole"),
    }
    calls = []
    expected = object()
    monkeypatch.setattr(
        tmux.discovery,
        "get_process_info",
        lambda pid: calls.append(pid) or processes.get(pid),
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.get_terminal_api",
        lambda name: expected if name == "konsole" else None,
    )

    assert tmux._detect_parent_terminal(200) is expected
    assert calls == [200, 150, 100]


def test_detached_tmux_selection_is_partial_focus(monkeypatch):
    api = TmuxAPI()
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "$7:@12.%34")
    monkeypatch.setattr(api, "switch_tab", lambda target, env: True)
    monkeypatch.setattr(api, "raise_window", lambda target, env: False)

    result = api.focus_result(200, TMUX_ENV)

    assert result.state == "partial"
    assert result.selection.succeeded
    assert not result.activation.succeeded
