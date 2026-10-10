import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.terminal_apis import _qdbus, ghostty, gnome, konsole, tmux
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from tests.konsole_fakes import fake_konsole as _fake_konsole


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

    with pytest.raises(
        RuntimeError,
        match=r"^parent terminal unknown did not activate "
        r"\(tab selection failed\)$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
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


class DeferredWindowParent(TerminalAPI):
    """Records window raises; selection is confirmed only after activation."""

    deferred_selection_readback = True

    def __init__(self, name, raised, activate=True, verify=True):
        self.name = name
        self.raised = raised
        self.activate = activate
        self.verify = verify

    @staticmethod
    def detect():
        return False

    @staticmethod
    def capture_env():
        return {}

    def find_tab(self, pid, env):
        return f"tab-{pid}"

    def find_activation_target(self, pid, env, tab_id):
        return f"window-{pid}"

    def switch_tab(self, target, env):
        return False

    def raise_window(self, target, env):
        if self.activate:
            self.raised.append((self.name, target))
        return self.activate

    def verify_selection(self, target, env):
        return self.verify


def _two_clients_in_different_parents(monkeypatch, parents):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            "300\t$7\t@12\t%34\t0\n200\t$7\t@12\t%34\t0\n"
        ),
    )
    routed = []
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or parents[pid],
    )
    return routed


def test_raise_window_raises_one_window_when_tab_is_unconfirmed(monkeypatch):
    raised = []
    routed = _two_clients_in_different_parents(
        monkeypatch,
        {
            200: DeferredWindowParent("first", raised, verify=False),
            300: DeferredWindowParent("second", raised),
        },
    )

    with pytest.raises(
        RuntimeError,
        match="^parent terminal first raised its window but could not "
        "confirm the tab$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200]
    assert raised == [("first", "window-200")]


def test_raise_window_unconfirmed_tab_is_not_success_in_focus_result(
    monkeypatch,
):
    raised = []
    _two_clients_in_different_parents(
        monkeypatch,
        {
            200: DeferredWindowParent("first", raised, verify=False),
            300: DeferredWindowParent("second", raised),
        },
    )
    monkeypatch.setattr(TmuxAPI, "find_tab", lambda self, pid, env: "$7:@12.%34")
    monkeypatch.setattr(TmuxAPI, "switch_tab", lambda self, tab_id, env: True)

    result = TmuxAPI().focus_result(101, TMUX_ENV)

    assert result.state == "partial"
    assert result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "parent terminal first raised its window but could not confirm the tab"
    )
    assert raised == [("first", "window-200")]


def test_raise_window_tries_second_parent_when_first_does_not_activate(
    monkeypatch,
):
    raised = []
    routed = _two_clients_in_different_parents(
        monkeypatch,
        {
            200: DeferredWindowParent("first", raised, activate=False),
            300: DeferredWindowParent("second", raised),
        },
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200, 300]
    assert raised == [("second", "window-300")]


def test_raise_window_reports_every_parent_failure(monkeypatch):
    raised = []
    routed = _two_clients_in_different_parents(
        monkeypatch,
        {200: DeferredWindowParent("first", raised, activate=False), 300: None},
    )

    with pytest.raises(
        RuntimeError,
        match="^parent terminal first did not activate; "
        "no parent terminal emulator found$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200, 300]
    assert raised == []


def test_raise_window_reports_unsupported_parent_activation(monkeypatch):
    unsupported = SimpleNamespace(name="terminator", activation_supported=False)
    _two_clients_in_different_parents(
        monkeypatch, {200: unsupported, 300: unsupported}
    )

    with pytest.raises(
        RuntimeError,
        match="^parent terminal terminator does not support window activation$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


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

    with pytest.raises(
        RuntimeError, match="^no parent terminal emulator found$"
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


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
        if command[1] == "get_desktop_for_window":
            return completed("0\n")
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
        ["xdotool", "get_desktop_for_window"],
        ["xdotool", "windowactivate"],
        ["xdotool", "getactivewindow"],
    ]
    assert commands[1][-1] == "100"
    assert commands[3][-1] == "4194307"


def test_tmux_in_gnome_terminal_with_several_windows_is_not_raised(monkeypatch):
    monkeypatch.setattr(gnome.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tmux.discovery, "get_process_info", _gnome_tree().get)
    commands = _route_tmux_and_xdotool(
        monkeypatch, {"search": completed("11\n12\n")}
    )

    with pytest.raises(
        RuntimeError,
        match=r"^parent terminal gnome did not activate \(gnome-terminal-server "
        r"owns 2 windows; exact window unknown\)$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert "windowactivate" not in [command[1] for command in commands]


def test_tmux_in_background_konsole_window_is_raised_then_verified(monkeypatch):
    fake = _fake_konsole(monkeypatch)
    konsole_run = _qdbus.subprocess.run

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
    konsole_run = _qdbus.subprocess.run

    def run(command, **kwargs):
        if command[0] == "tmux":
            return completed("200\t$7\t@12\t%34\t0\n")
        return konsole_run(command, **kwargs)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    monkeypatch.setattr(
        tmux, "_detect_parent_terminal", lambda pid: konsole.KonsoleAPI()
    )

    with pytest.raises(
        RuntimeError,
        match=r"^parent terminal konsole may have raised its window but could "
        r"not confirm it \(no unique Konsole window matched the tab title",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


@pytest.mark.parametrize(
    ("result", "detail"),
    [
        (completed(), "no attached tmux client shows the pane"),
        (
            completed("201\t$7\t@12\t%35\t0\n202\t$7\t@12\t%34\t1\n"),
            "no attached tmux client shows the pane",
        ),
        (completed("malformed\n"), "unrecognized tmux list-clients output"),
        (completed(returncode=1), "tmux client list could not be read"),
    ],
    ids=["no-clients", "other-pane-or-control", "malformed", "failed"],
)
def test_raise_window_fails_safely_without_eligible_clients(
    monkeypatch, result, detail
):
    monkeypatch.setattr(tmux.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: pytest.fail("no client may be routed"),
    )

    with pytest.raises(RuntimeError, match=f"^{detail}$"):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)


def test_raise_window_names_each_distinct_client_failure(monkeypatch):
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *args, **kwargs: completed(
            "300\t$7\t@12\t%34\t0\n200\t$7\t@12\t%34\t0\n"
            "400\t$7\t@12\t%34\t0\n"
        ),
    )
    unsupported = SimpleNamespace(name="kitty", activation_supported=False)
    parents = {200: None, 300: unsupported, 400: None}
    routed = []
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or parents[pid],
    )

    with pytest.raises(
        RuntimeError,
        match="^no parent terminal emulator found;"
        " parent terminal kitty does not support window activation$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200, 300, 400]


def test_failed_client_routing_is_reported_as_failed_activation(monkeypatch):
    api = TmuxAPI()
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "$7:@12.%34")
    monkeypatch.setattr(api, "switch_tab", lambda target, env: True)
    monkeypatch.setattr(
        tmux.subprocess, "run", lambda *args, **kwargs: completed()
    )

    result = api.focus_result(200, TMUX_ENV)

    assert result.state == "partial"
    assert result.activation.attempted and not result.activation.succeeded
    assert result.activation.detail == "no attached tmux client shows the pane"


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


TWO_CLIENTS = "300\t$7\t@12\t%34\t0\n200\t$7\t@12\t%34\t0\n"


def _konsole_behind_two_clients(monkeypatch, fake, parents):
    konsole_run = _qdbus.subprocess.run

    def run(command, **kwargs):
        if command[0] == "tmux":
            return completed(TWO_CLIENTS)
        return konsole_run(command, **kwargs)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    routed = []
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or parents[pid],
    )
    return routed


def _kwin_raises(fake):
    return [
        command
        for command in fake.calls
        if command[1:2] == ["org.kde.KWin"]
        and command[3] == "org.kde.kwin.Script.run"
    ]


def test_two_konsole_parents_send_one_kwin_raise_when_tab_stays_wrong(
    monkeypatch,
):
    fake = _fake_konsole(monkeypatch)
    fake_run = fake.run

    def tab_never_becomes_current(command, **kwargs):
        if command[3:4] == ["org.kde.konsole.Window.setCurrentSession"]:
            fake.calls.append(command)
            return completed()
        return fake_run(command, **kwargs)

    monkeypatch.setattr(_qdbus.subprocess, "run", tab_never_becomes_current)
    routed = _konsole_behind_two_clients(
        monkeypatch,
        fake,
        {200: konsole.KonsoleAPI(), 300: konsole.KonsoleAPI()},
    )

    with pytest.raises(RuntimeError) as error:
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)

    assert str(error.value).startswith(
        "parent terminal konsole may have raised its window but could not "
        "confirm it ("
    )
    assert routed == [200]
    assert len(fake.scripts) == 1
    assert len(_kwin_raises(fake)) == 1
    assert fake.active and fake.focused == "5"


def test_konsole_parent_failing_before_raise_lets_next_client_activate(
    monkeypatch,
):
    fake = _fake_konsole(monkeypatch)
    fake_run = fake.run

    def owner_unreadable_for_dead_service(command, **kwargs):
        if command[1:] == ["dead"]:
            return fake_run(command[:1] + ["svc"], **kwargs)
        if command[-1] == "dead" and "GetConnectionUnixProcessID" in command[3]:
            fake.calls.append(command)
            return completed(returncode=1)
        return fake_run(command, **kwargs)

    monkeypatch.setattr(_qdbus.subprocess, "run", owner_unreadable_for_dead_service)
    first = konsole.KonsoleAPI()
    first.find_tab = lambda pid, env: "dead|7|2"
    routed = _konsole_behind_two_clients(
        monkeypatch, fake, {200: first, 300: konsole.KonsoleAPI()}
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200, 300]
    assert len(fake.scripts) == 1
    assert fake.active and fake.focused == "2"


def test_two_ghostty_parents_send_one_raise_when_readback_fails(monkeypatch):
    calls = []
    tree = {
        200: process(200, 4242, "tmux: client"),
        300: process(300, 4242, "tmux: client"),
        4242: process(4242, 1, "ghostty"),
    }
    monkeypatch.setattr(ghostty.sys, "platform", "linux")
    monkeypatch.setattr(ghostty.discovery, "get_process_info", tree.get)
    monkeypatch.setattr(_qdbus.shutil, "which", lambda name: "/usr/bin/qdbus-qt6")
    monkeypatch.setattr(
        ghostty.GhosttyAPI, "find_tab", lambda self, pid, env: f"{pid}:1"
    )

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "tmux":
            return completed(TWO_CLIENTS)
        if command[0] == "/usr/bin/qdbus-qt6":
            if command[3] == "org.kde.kwin.Scripting.loadScript":
                return completed("9\n")
            return completed("true\n")
        verb = command[1]
        if verb == "search":
            return completed("62914563\n")
        if verb == "get_desktop_for_window":
            return completed("0\n")
        if verb == "windowactivate":
            return completed()
        assert verb == "getactivewindow", command
        return completed("777\n")

    monkeypatch.setattr(tmux.subprocess, "run", run)
    routed = []
    parents = {200: ghostty.GhosttyAPI(), 300: ghostty.GhosttyAPI()}
    monkeypatch.setattr(
        tmux,
        "_detect_parent_terminal",
        lambda pid: routed.append(pid) or parents[pid],
    )

    with pytest.raises(
        RuntimeError,
        match=r"^parent terminal ghostty may have raised its window but could "
        r"not confirm it \(active window readback did not match the target",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    assert routed == [200]
    assert sum(
        command[3:4] == ["org.kde.kwin.Script.run"] for command in calls
    ) == 1
    assert [command[1] for command in calls].count("windowactivate") == 1


def _two_gnome_servers():
    tree = {
        200: process(200, 100, "tmux: client"),
        300: process(300, 110, "tmux: client"),
    }
    for server in (100, 110):
        tree[server] = ProcessInfo(
            pid=server,
            ppid=1,
            name="gnome-terminal-",
            executable="/usr/libexec/gnome-terminal-server",
            argv=("/usr/libexec/gnome-terminal-server",),
            cwd=None,
            start_token="1",
        )
    return tree


def _route_two_gnome_servers(monkeypatch, windows, active):
    monkeypatch.setattr(gnome.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tmux.discovery, "get_process_info", _two_gnome_servers().get)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[0] == "tmux":
            return completed(TWO_CLIENTS)
        assert command[0] == "xdotool"
        verb = command[1]
        if verb == "search":
            return completed(windows[command[-1]])
        if verb == "get_desktop_for_window":
            return completed("0\n")
        if verb == "windowactivate":
            return completed()
        assert verb == "getactivewindow", command
        return completed(active)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    return commands


def test_two_gnome_parents_send_one_activation_when_readback_disagrees(
    monkeypatch,
):
    commands = _route_two_gnome_servers(
        monkeypatch, {"100": "11\n", "110": "12\n"}, "99\n"
    )

    with pytest.raises(
        RuntimeError,
        match=r"^parent terminal gnome may have raised its window but could not "
        r"confirm it \(active window readback did not match the target\)$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    activations = [command for command in commands if command[1] == "windowactivate"]
    assert activations == [["xdotool", "windowactivate", "--sync", "11"]]
    assert ["xdotool", "search", "--pid", "110"] not in commands


def test_gnome_parent_failing_before_raise_lets_next_client_activate(
    monkeypatch,
):
    commands = _route_two_gnome_servers(
        monkeypatch, {"100": "11\n13\n", "110": "12\n"}, "12\n"
    )

    assert TmuxAPI().raise_window("$7:@12.%34", TMUX_ENV)
    activations = [command for command in commands if command[1] == "windowactivate"]
    assert activations == [["xdotool", "windowactivate", "--sync", "12"]]
