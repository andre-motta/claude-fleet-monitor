import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.terminal_apis import gnome, konsole, tmux
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from tests.test_konsole import _fake_konsole


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


class SelectionUnsupportedParent(TerminalAPI):
    name = "window-only"
    selection_supported = False

    def __init__(self):
        self.calls = []

    @staticmethod
    def detect():
        return False

    @staticmethod
    def capture_env():
        return {}

    def find_tab(self, pid, env):
        return None

    def find_activation_target(self, pid, env, tab_id):
        self.calls.append(("target", pid))
        return "window-1"

    def switch_tab(self, target, env):
        pytest.fail("selection is unsupported")

    def raise_window(self, target, env):
        self.calls.append(("raise", target))
        return True


def test_raise_window_allows_selection_unsupported_parent(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed("200\t$7\t@12\t%34\t0\n"),
    )
    parent = SelectionUnsupportedParent()
    monkeypatch.setattr(tmux, "_detect_parent_terminal", lambda pid: parent)

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert parent.calls == [("target", 200), ("raise", "window-1")]


def test_raise_window_tries_next_client_after_parent_failure(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            "300\t$7\t@12\t%34\t0\n200\t$7\t@12\t%34\t0\n"
        ),
    )
    calls = []

    class Parent:
        selection_supported = True

        def find_tab(self, pid, env):
            calls.append(("find", pid))
            if pid == 200:
                raise RuntimeError("parent failed")
            return f"tab-{pid}"

        def switch_tab(self, target, env):
            calls.append(("select", target))
            return True

        def raise_window(self, target, env):
            calls.append(("raise", target))
            return True

    routed = []
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or Parent(),
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200, 300]
    assert calls == [
        ("find", 200),
        ("find", 300),
        ("select", "tab-300"),
        ("raise", "tab-300"),
    ]


def test_raise_window_stops_at_first_activated_client(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            "300\t$7\t@12\t%34\t0\n200\t$7\t@12\t%34\t0\n"
        ),
    )
    routed = []
    parent = SelectionUnsupportedParent()
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or parent,
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200]


def test_raise_window_never_constructs_generic_api(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed("200\t$7\t@12\t%34\t0\n"),
    )
    monkeypatch.setattr(
        GenericAPI,
        "__init__",
        lambda self: pytest.fail("GenericAPI must not be constructed"),
    )
    monkeypatch.setattr(tmux, "_detect_parent_terminal", lambda pid: None)

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


def _gnome_tree():
    return {
        200: process(200, 150, "tmux: client"),
        150: process(150, 100, "bash"),
        100: ProcessInfo(
            pid=100,
            ppid=1,
            name="gnome-terminal-",
            executable="/usr/libexec/gnome-terminal-server",
            argv=("/usr/libexec/gnome-terminal-server",),
            cwd=None,
            start_token="1",
        ),
    }


def _route_tmux_and_xdotool(monkeypatch, xdotool):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[0] == "tmux":
            return completed("200\t$7\t@12\t%34\t0\n")
        assert command[0] == "xdotool"
        return xdotool[command[1]]

    monkeypatch.setattr(tmux.subprocess, "run", run)
    return commands


def test_tmux_in_gnome_terminal_activates_owned_window(monkeypatch):
    monkeypatch.setattr(gnome.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tmux.discovery, "get_process_info", _gnome_tree().get)
    commands = _route_tmux_and_xdotool(
        monkeypatch,
        {
            "search": completed("4194307\n"),
            "windowactivate": completed(),
            "getactivewindow": completed("4194307\n"),
        },
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert [command[:2] for command in commands[1:]] == [
        ["xdotool", "search"],
        ["xdotool", "windowactivate"],
        ["xdotool", "getactivewindow"],
    ]
    assert commands[1][-1] == "100"
    assert commands[2][-1] == "4194307"


def test_tmux_in_gnome_terminal_with_several_windows_is_not_raised(monkeypatch):
    monkeypatch.setattr(gnome.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tmux.discovery, "get_process_info", _gnome_tree().get)
    commands = _route_tmux_and_xdotool(
        monkeypatch, {"search": completed("11\n12\n")}
    )

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert [command[:2] for command in commands[1:]] == [["xdotool", "search"]]


def test_tmux_in_background_konsole_window_is_raised_then_verified(monkeypatch):
    fake = _fake_konsole(monkeypatch)
    konsole_run = konsole.subprocess.run

    def run(command, **kwargs):
        if command[0] == "tmux":
            return completed("200\t$7\t@12\t%34\t0\n")
        return konsole_run(command, **kwargs)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    monkeypatch.setattr(
        tmux, "_detect_parent_terminal", lambda pid: konsole.KonsoleAPI()
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert fake.active
    assert fake.focused == "2"
    assert len(fake.scripts) == 1


def test_tmux_in_background_konsole_window_needs_observed_activation(
    monkeypatch,
):
    fake = _fake_konsole(monkeypatch)
    fake.activates = False
    konsole_run = konsole.subprocess.run

    def run(command, **kwargs):
        if command[0] == "tmux":
            return completed("200\t$7\t@12\t%34\t0\n")
        return konsole_run(command, **kwargs)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    monkeypatch.setattr(
        tmux, "_detect_parent_terminal", lambda pid: konsole.KonsoleAPI()
    )

    assert not TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


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
