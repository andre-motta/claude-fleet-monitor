import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import _qdbus, ghostty
from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI

QDBUS = "/usr/bin/qdbus-qt6"
GHOSTTY_PID = 4242
WINDOW = "62914563"
NODE = shutil.which("node")


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


class FakeDesktop:
    """KWin over qdbus plus xdotool, with no real process ever started."""

    def __init__(self, qdbus=True):
        self.qdbus = qdbus
        self.calls = []
        self.scripts = []
        self.unloaded = []
        self.load_result = completed("9\n")
        self.xdotool = {
            "search": completed(f"{WINDOW}\n"),
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
            return completed()
        if method == "org.kde.kwin.Scripting.unloadScript":
            self.unloaded.append(args[3])
            return completed("true\n")
        raise AssertionError(args)

    def xdotool_calls(self):
        return [command for command in self.calls if command[0] == "xdotool"]


@pytest.fixture
def desktop(monkeypatch):
    fake = FakeDesktop()
    monkeypatch.setattr(ghostty.sys, "platform", "linux")
    monkeypatch.setattr(ghostty, "_find_ghostty_pid", lambda: GHOSTTY_PID)
    monkeypatch.setattr(
        ghostty,
        "_find_ancestor_child",
        lambda pid, owner: 900 if (pid, owner) == (101, GHOSTTY_PID) else None,
    )
    monkeypatch.setattr(_qdbus.shutil, "which", fake.which)
    monkeypatch.setattr(ghostty.subprocess, "run", fake.run)
    return fake


def test_activation_targets_the_single_visible_ghostty_window(desktop):
    assert GhosttyAPI().raise_window("101:2", {})

    assert desktop.xdotool_calls() == [
        ["xdotool", "search", "--onlyvisible", "--pid", str(GHOSTTY_PID)],
        ["xdotool", "windowactivate", "--sync", WINDOW],
        ["xdotool", "getactivewindow"],
    ]


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
    desktop.xdotool["search"] = completed(returncode=1)

    with pytest.raises(
        RuntimeError,
        match="^Ghostty owns no visible X11 window;"
        " KWin: KWin script could not be loaded$",
    ):
        GhosttyAPI().raise_window("101:2", {})
    _, plugin, path = desktop.scripts[0]
    assert desktop.unloaded == [plugin]
    assert not os.path.exists(path)


def test_without_qdbus_only_xdotool_runs(desktop):
    desktop.qdbus = False

    assert GhosttyAPI().raise_window("101:2", {})
    assert all(command[0] == "xdotool" for command in desktop.calls)


def test_kwin_is_linux_only(desktop, monkeypatch):
    monkeypatch.setattr(ghostty.sys, "platform", "darwin")

    assert GhosttyAPI().raise_window("101:2", {})
    assert not desktop.scripts


def test_several_visible_windows_are_never_activated(desktop):
    desktop.xdotool["search"] = completed("11\n12\n")

    with pytest.raises(
        RuntimeError,
        match="^Ghostty owns 2 visible windows; exact window unknown;",
    ):
        GhosttyAPI().raise_window("101:2", {})
    assert [command[1] for command in desktop.xdotool_calls()] == ["search"]


def test_readback_mismatch_is_not_success(desktop):
    desktop.xdotool["getactivewindow"] = completed("77\n")

    with pytest.raises(RuntimeError, match="readback did not match"):
        GhosttyAPI().raise_window("101:2", {})


def test_failed_windowactivate_is_not_success(desktop):
    desktop.xdotool["windowactivate"] = completed(returncode=1)

    with pytest.raises(RuntimeError, match="windowactivate exited 1"):
        GhosttyAPI().raise_window("101:2", {})
    assert [command[1] for command in desktop.xdotool_calls()] == [
        "search",
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
    assert [command[1] for command in desktop.xdotool_calls()] == ["search"]


@pytest.mark.parametrize(
    ("tab_id", "ghostty_pid", "detail"),
    [
        ("bad", GHOSTTY_PID, "invalid Ghostty tab target"),
        ("101:2", None, "Ghostty process not found"),
        ("555:2", GHOSTTY_PID, "session is not inside the running Ghostty process"),
    ],
)
def test_unidentified_session_runs_nothing(
    desktop, monkeypatch, tab_id, ghostty_pid, detail
):
    monkeypatch.setattr(ghostty, "_find_ghostty_pid", lambda: ghostty_pid)

    with pytest.raises(RuntimeError, match=f"^{detail}$"):
        GhosttyAPI().raise_window(tab_id, {})
    assert not desktop.calls


def test_ambiguous_window_skips_tab_keys(desktop, monkeypatch):
    desktop.xdotool["search"] = completed("11\n12\n")
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
    assert result.activation.detail.startswith("Ghostty owns 2 visible windows")


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
