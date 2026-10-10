import json
import os
import shutil
import subprocess
from itertools import chain, repeat
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import _qdbus, ghostty
from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI

QDBUS = "/usr/bin/qdbus-qt6"
GHOSTTY_PID = 4242
WINDOW = "62914563"
LEADER = "62914561"
HIDDEN = "62914570"
NODE = shutil.which("node")


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def _process(pid, ppid, name, executable=None):
    return SimpleNamespace(
        pid=pid, ppid=ppid, name=name, executable=executable or name, argv=(name,)
    )


def _tree(*processes):
    table = {process.pid: process for process in processes}
    return lambda pid: table.get(pid)


SESSION_TREE = (
    _process(101, 900, "claude"),
    _process(900, GHOSTTY_PID, "bash"),
    _process(GHOSTTY_PID, 1, "ghostty"),
)


class FakeDesktop:
    """KWin over qdbus plus xdotool, with no real process ever started.

    windows maps every X11 window of the Ghostty pid, as an unfiltered
    `xdotool search --pid` lists it, to whether the window manager manages it.
    """

    def __init__(self, qdbus=True):
        self.qdbus = qdbus
        self.calls = []
        self.scripts = []
        self.unloaded = []
        self.load_result = completed("9\n")
        self.run_result = completed()
        self.windows = {LEADER: False, WINDOW: True}
        self.xdotool = {
            "windowactivate": completed(),
            "getactivewindow": completed(f"{WINDOW}\n"),
        }

    def which(self, name):
        return QDBUS if self.qdbus and name == "qdbus-qt6" else None

    def run(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs["timeout"] <= 5
        if command[0] == QDBUS:
            return self._kwin(command[1:])
        assert command[0] == "xdotool", command
        assert "--onlyvisible" not in command
        if command[1] == "search" and "search" not in self.xdotool:
            assert command == ["xdotool", "search", "--pid", str(GHOSTTY_PID)]
            return completed("".join(f"{wid}\n" for wid in self.windows))
        if command[1] == "get_desktop_for_window":
            managed = self.windows[command[2]]
            return completed("0\n" if managed else "", 0 if managed else 1)
        response = self.xdotool[command[1]]
        if isinstance(response, BaseException):
            raise response
        return response

    def _kwin(self, args):
        assert args[0] == "org.kde.KWin", args
        method = args[2]
        if method == "org.kde.kwin.Scripting.loadScript":
            with open(args[3]) as script:
                self.scripts.append((script.read(), args[4], args[3]))
            return self.load_result
        if method == "org.kde.kwin.Script.run":
            return self.run_result
        if method == "org.kde.kwin.Scripting.unloadScript":
            self.unloaded.append(args[3])
            return completed("true\n")
        raise AssertionError(args)

    def xdotool_calls(self):
        return [command for command in self.calls if command[0] == "xdotool"]

    def xdotool_verbs(self):
        return [command[1] for command in self.xdotool_calls()]


@pytest.fixture
def desktop(monkeypatch):
    fake = FakeDesktop()
    monkeypatch.setattr(ghostty.sys, "platform", "linux")
    monkeypatch.setattr(ghostty.discovery, "get_process_info", _tree(*SESSION_TREE))
    monkeypatch.setattr(_qdbus.shutil, "which", fake.which)
    monkeypatch.setattr(ghostty.subprocess, "run", fake.run)
    return fake


def test_activation_targets_the_single_managed_ghostty_window(desktop):
    assert GhosttyAPI().raise_window("101:2", {})

    assert desktop.xdotool_calls() == [
        ["xdotool", "search", "--pid", str(GHOSTTY_PID)],
        ["xdotool", "get_desktop_for_window", LEADER],
        ["xdotool", "get_desktop_for_window", WINDOW],
        ["xdotool", "windowactivate", "--sync", WINDOW],
        ["xdotool", "getactivewindow"],
    ]


def test_minimized_session_window_beside_a_visible_one_is_not_activated(desktop):
    desktop.windows = {LEADER: False, WINDOW: True, HIDDEN: True}

    with pytest.raises(
        RuntimeError, match="^Ghostty owns 2 windows; exact window unknown;"
    ):
        GhosttyAPI().raise_window("101:2", {})
    assert "windowactivate" not in desktop.xdotool_verbs()


def test_minimized_session_window_skips_tab_keys(desktop, monkeypatch):
    desktop.windows = {LEADER: False, WINDOW: True, HIDDEN: True}
    api = GhosttyAPI()
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "101:2")
    monkeypatch.setattr(
        api,
        "switch_tab",
        lambda target, env: pytest.fail("Alt+N must not be sent"),
    )

    result = api.focus_result(101, {})

    assert result.state == "failed"
    assert not result.selection.attempted
    assert result.activation.attempted and not result.activation.succeeded
    assert result.activation.detail.startswith("Ghostty owns 2 windows")
    assert "windowactivate" not in desktop.xdotool_verbs()


def test_window_lookup_is_bounded(desktop):
    desktop.windows = {str(10 + index): True for index in range(17)}

    with pytest.raises(RuntimeError, match="^Ghostty owns 17 X11 windows;"):
        GhosttyAPI().raise_window("101:2", {})
    assert desktop.xdotool_verbs() == ["search"]


def test_window_lookup_keeps_its_deadline(desktop, monkeypatch):
    desktop.qdbus = False
    clock = chain([0.0] * 5, [0.5, 2.5], repeat(4.0))
    monkeypatch.setattr(ghostty.time, "monotonic", lambda: next(clock))

    with pytest.raises(RuntimeError, match="^X11 window lookup timed out$"):
        GhosttyAPI().raise_window("101:2", {})
    assert desktop.xdotool_verbs() == ["search", "get_desktop_for_window"]


def test_kwin_script_filters_by_owner_and_is_always_unloaded(desktop):
    GhosttyAPI().raise_window("101:2", {})

    script, plugin, path = desktop.scripts[0]
    assert f"var owner = {json.dumps(GHOSTTY_PID)};" in script
    assert "resourceClass" not in script
    assert plugin.startswith("claude-fleet-ghostty-")
    assert plugin != "claude-fleet-ghostty-"
    assert desktop.unloaded == [plugin]
    assert not os.path.exists(path)


def test_kwin_plugin_names_are_unique_per_activation(desktop):
    GhosttyAPI().raise_window("101:2", {})
    GhosttyAPI().raise_window("101:2", {})

    plugins = [plugin for _, plugin, _ in desktop.scripts]
    assert len(set(plugins)) == 2


def test_kwin_request_alone_is_never_success(desktop):
    desktop.xdotool["search"] = FileNotFoundError("xdotool")

    with pytest.raises(
        RuntimeError,
        match="^xdotool is not installed; KWin: activation requested but"
        " unconfirmed$",
    ):
        GhosttyAPI().raise_window("101:2", {})
    assert desktop.unloaded == [desktop.scripts[0][1]]


def test_failed_kwin_load_is_named_and_cleaned_up(desktop):
    desktop.load_result = completed("-1\n")
    desktop.windows = {LEADER: False}

    with pytest.raises(
        RuntimeError,
        match="^Ghostty owns no managed X11 window;"
        " KWin: KWin script could not be loaded$",
    ):
        GhosttyAPI().raise_window("101:2", {})
    _, plugin, path = desktop.scripts[0]
    assert desktop.unloaded == [plugin]
    assert not os.path.exists(path)


def test_failed_kwin_run_is_named_and_cleaned_up(desktop):
    desktop.run_result = completed(returncode=1)
    desktop.xdotool["getactivewindow"] = completed("77\n")

    with pytest.raises(
        RuntimeError,
        match="^active window readback did not match the target;"
        " KWin: KWin script could not be run$",
    ):
        GhosttyAPI().raise_window("101:2", {})
    _, plugin, path = desktop.scripts[0]
    assert desktop.unloaded == [plugin]
    assert not os.path.exists(path)


def test_failed_kwin_run_still_allows_confirmed_x11_activation(desktop):
    desktop.run_result = completed(returncode=1)

    assert GhosttyAPI().raise_window("101:2", {})
    assert desktop.unloaded == [desktop.scripts[0][1]]


def test_unwritable_kwin_script_continues_to_x11(desktop, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(_qdbus.tempfile, "mkstemp", refuse)
    desktop.xdotool["getactivewindow"] = completed("77\n")

    with pytest.raises(
        RuntimeError,
        match="^active window readback did not match the target;"
        " KWin: KWin script could not be written: No space left on device$",
    ):
        GhosttyAPI().raise_window("101:2", {})
    assert "windowactivate" in desktop.xdotool_verbs()
    assert not desktop.scripts


def test_kwin_fdopen_failure_closes_the_descriptor(monkeypatch, tmp_path):
    opened = []
    real_mkstemp = _qdbus.tempfile.mkstemp

    def mkstemp(**kwargs):
        descriptor, path = real_mkstemp(dir=tmp_path, **kwargs)
        opened.append(descriptor)
        return descriptor, path

    def fdopen(*args, **kwargs):
        raise OSError(24, "Too many open files")

    def run(command, **kwargs):
        return completed()

    monkeypatch.setattr(_qdbus.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(_qdbus.os, "fdopen", fdopen)
    monkeypatch.setattr(_qdbus.subprocess, "run", run)

    with pytest.raises(OSError, match="Too many open files"):
        _qdbus.run_kwin_script(QDBUS, "", "claude-fleet-test")
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert not list(tmp_path.iterdir())


def test_without_qdbus_only_xdotool_runs(desktop):
    desktop.qdbus = False

    assert GhosttyAPI().raise_window("101:2", {})
    assert all(command[0] == "xdotool" for command in desktop.calls)


def test_kwin_is_linux_only(desktop, monkeypatch):
    monkeypatch.setattr(ghostty.sys, "platform", "darwin")

    assert GhosttyAPI().raise_window("101:2", {})
    assert not desktop.scripts


def test_several_managed_windows_are_never_activated(desktop):
    desktop.windows = {"11": True, "12": True}

    with pytest.raises(
        RuntimeError,
        match="^Ghostty owns 2 windows; exact window unknown;",
    ):
        GhosttyAPI().raise_window("101:2", {})
    assert "windowactivate" not in desktop.xdotool_verbs()


def test_readback_mismatch_is_not_success(desktop):
    desktop.xdotool["getactivewindow"] = completed("77\n")

    with pytest.raises(RuntimeError, match="readback did not match"):
        GhosttyAPI().raise_window("101:2", {})


def test_failed_windowactivate_is_not_success(desktop):
    desktop.xdotool["windowactivate"] = completed(returncode=1)

    with pytest.raises(RuntimeError, match="windowactivate exited 1"):
        GhosttyAPI().raise_window("101:2", {})
    assert desktop.xdotool_verbs()[-2:] == [
        "get_desktop_for_window",
        "windowactivate",
    ]


def test_xdotool_timeout_fails_with_detail(desktop):
    desktop.xdotool["search"] = subprocess.TimeoutExpired("xdotool", 2)

    with pytest.raises(RuntimeError, match="^xdotool search timed out;"):
        GhosttyAPI().raise_window("101:2", {})


def test_invalid_window_id_is_not_activated(desktop):
    desktop.xdotool["search"] = completed("0x3c00003\n")

    with pytest.raises(RuntimeError, match="invalid window id"):
        GhosttyAPI().raise_window("101:2", {})
    assert desktop.xdotool_verbs() == ["search"]


@pytest.mark.parametrize(
    ("tab_id", "tree", "detail"),
    [
        ("bad", SESSION_TREE, "invalid Ghostty tab target"),
        (
            "101:2",
            (_process(101, 900, "claude"), _process(900, 1, "bash")),
            "no Ghostty ancestor found",
        ),
        (
            "555:2",
            SESSION_TREE + (_process(555, 1, "claude"),),
            "no Ghostty ancestor found",
        ),
        (
            "101:2",
            (_process(101, 900, "claude"), _process(900, 101, "bash")),
            "no Ghostty ancestor found",
        ),
        ("4242:1", SESSION_TREE, "no Ghostty ancestor found"),
        ("1:1", SESSION_TREE, "invalid agent process id"),
    ],
    ids=["bad-tab", "no-ghostty", "unrelated", "cycle", "ghostty-itself", "init"],
)
def test_unidentified_session_runs_nothing(desktop, monkeypatch, tab_id, tree, detail):
    monkeypatch.setattr(ghostty.discovery, "get_process_info", _tree(*tree))

    with pytest.raises(RuntimeError, match=f"^{detail}$"):
        GhosttyAPI().raise_window(tab_id, {})
    assert not desktop.calls


def test_other_ghostty_process_is_never_chosen(desktop, monkeypatch):
    other = _process(5000, 1, "ghostty")
    monkeypatch.setattr(
        ghostty.discovery, "get_process_info", _tree(other, *SESSION_TREE)
    )

    assert GhosttyAPI().raise_window("101:2", {})
    assert desktop.xdotool_calls()[0] == [
        "xdotool", "search", "--pid", str(GHOSTTY_PID)
    ]


def test_ghostty_matched_by_executable(monkeypatch):
    tree = (
        _process(101, 900, "claude"),
        _process(900, 777, "bash"),
        _process(777, 1, "ghostty-wrapped", "/usr/bin/ghostty"),
    )
    monkeypatch.setattr(ghostty.discovery, "get_process_info", _tree(*tree))

    assert ghostty._find_ghostty(101, ghostty.time.monotonic() + 3) == (777, 900)


def test_ancestry_walk_is_bounded(monkeypatch):
    visited = []

    def endless(pid):
        visited.append(pid)
        return _process(pid, pid + 1, "bash")

    monkeypatch.setattr(ghostty.discovery, "get_process_info", endless)

    with pytest.raises(LookupError, match="^no Ghostty ancestor found$"):
        ghostty._find_ghostty(300, ghostty.time.monotonic() + 3)
    assert len(visited) == 64


def test_ancestry_walk_keeps_its_deadline(monkeypatch):
    clock = iter(float(tick) for tick in range(10))
    monkeypatch.setattr(ghostty.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        ghostty.discovery,
        "get_process_info",
        lambda pid: _process(pid, pid + 1, "bash"),
    )

    with pytest.raises(LookupError, match="^process ancestry walk timed out$"):
        ghostty._find_ghostty(300, 2.5)


def test_find_tab_indexes_the_ghostty_child_on_the_session_path(desktop, monkeypatch):
    monkeypatch.setattr(
        ghostty, "_get_ghostty_children", lambda pid: [800, 900, 1000]
    )

    assert GhosttyAPI().find_tab(101, {}) == "101:2"


def test_find_tab_without_ghostty_ancestor_is_none(desktop, monkeypatch):
    monkeypatch.setattr(
        ghostty,
        "_get_ghostty_children",
        lambda pid: pytest.fail("children must not be listed"),
    )
    monkeypatch.setattr(ghostty.discovery, "get_process_info", lambda pid: None)

    assert GhosttyAPI().find_tab(101, {}) is None


def _run_kwin_script(windows):
    script = ghostty._KWIN_ACTIVATE_SCRIPT.replace(
        "__OWNER__", json.dumps(GHOSTTY_PID)
    )
    harness = (
        "const fakeWindows = " + json.dumps(windows) + ";\n"
        "const workspace = {activeWindow: null, windowList: () => fakeWindows};\n"
        + script
        + "\nconst active = workspace.activeWindow;"
        "\nconsole.log(JSON.stringify(active && active.caption));"
    )
    result = subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("windows", "activated"),
    [
        ([("mine", GHOSTTY_PID), ("other", 7)], "mine"),
        ([("first", GHOSTTY_PID), ("second", GHOSTTY_PID)], None),
        ([("other", 7)], None),
    ],
    ids=["single-owned", "two-owned", "none-owned"],
)
def test_kwin_script_activates_only_a_unique_owned_window(windows, activated):
    fake = [
        {
            "caption": caption,
            "pid": pid,
            "resourceClass": "com.mitchellh.ghostty",
            "minimized": True,
        }
        for caption, pid in windows
    ]

    assert _run_kwin_script(fake) == activated
