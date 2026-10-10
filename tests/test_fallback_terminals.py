import subprocess
import sys
from itertools import count
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import generic, gnome, windows_terminal
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.gnome import GnomeAPI
from claude_fleet_monitor.terminal_apis.windows_terminal import WindowsTerminalAPI


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"pywinctl.{name} must not be used")


def _forbid_activation(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no subprocess may run")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)
    monkeypatch.setitem(sys.modules, "pywinctl", _Forbidden())


def test_generic_module_has_no_activation_imports():
    assert "subprocess" not in vars(generic)
    assert "pywinctl" not in vars(generic)


def test_generic_reports_unsupported_without_activation(monkeypatch):
    _forbid_activation(monkeypatch)
    api = GenericAPI()
    assert not api.selection_supported
    assert not api.activation_supported
    assert api.find_tab(101, {}) is None
    assert api.find_activation_target(101, {}, None) is None
    assert not api.switch_tab("101", {})
    assert not api.raise_window("101", {})

    result = api.focus_result(101, {})

    assert result.state == "failed"
    assert not result.target_found
    assert not result.selection.attempted
    assert not result.activation.attempted
    assert "backend does not support" in result.selection.detail
    assert "backend does not support" in result.activation.detail
    assert not api.focus(101, {})


def _process(pid, ppid, name, executable=None):
    return SimpleNamespace(
        pid=pid, ppid=ppid, name=name, executable=executable or name, argv=(name,)
    )


def _tree(*processes):
    table = {process.pid: process for process in processes}
    return lambda pid: table.get(pid)


@pytest.fixture
def gnome_env(monkeypatch):
    monkeypatch.setattr(gnome.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(
        gnome.discovery,
        "get_process_info",
        _tree(
            _process(300, 200, "claude"),
            _process(200, 100, "bash"),
            _process(100, 1, "gnome-terminal-", "gnome-terminal-server"),
        ),
    )
    calls = []

    def install(responses):
        def run(argv, **kwargs):
            calls.append(argv)
            assert argv[0] == "xdotool"
            assert kwargs["timeout"] <= 3
            response = responses[argv[1]]
            if isinstance(response, BaseException):
                raise response
            return response

        monkeypatch.setattr(gnome.subprocess, "run", run)
        return calls

    return install


def _completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, returncode=returncode)


def test_gnome_activates_single_owned_window_with_readback(gnome_env):
    calls = gnome_env({
        "search": _completed("4194307\n"),
        "windowactivate": _completed(),
        "getactivewindow": _completed("4194307\n"),
    })

    result = GnomeAPI().focus_result(300, {})

    assert result.state == "partial"
    assert result.target_found
    assert result.activation.succeeded
    assert not result.selection.attempted
    assert calls == [
        ["xdotool", "search", "--pid", "100"],
        ["xdotool", "windowactivate", "--sync", "4194307"],
        ["xdotool", "getactivewindow"],
    ]


def test_gnome_several_windows_is_unavailable(gnome_env):
    calls = gnome_env({"search": _completed("11\n12\n13\n")})

    result = GnomeAPI().focus_result(300, {})

    assert result.state == "failed"
    assert not result.target_found
    assert not result.activation.attempted
    assert result.activation.detail == (
        "gnome-terminal-server owns 3 windows; exact window unknown"
    )
    assert len(calls) == 1


def test_gnome_no_owned_window_is_unavailable(gnome_env):
    gnome_env({"search": _completed("", returncode=1)})

    result = GnomeAPI().focus_result(300, {})

    assert not result.activation.attempted
    assert "owns no X11 window" in result.activation.detail


def test_gnome_activation_readback_mismatch_is_not_success(gnome_env):
    gnome_env({
        "search": _completed("4194307\n"),
        "windowactivate": _completed(),
        "getactivewindow": _completed("999\n"),
    })

    result = GnomeAPI().focus_result(300, {})

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded
    assert "readback" in result.activation.detail


def test_gnome_failed_windowactivate_is_not_success(gnome_env):
    gnome_env({"windowactivate": _completed(returncode=1)})

    with pytest.raises(RuntimeError, match="windowactivate exited 1"):
        GnomeAPI().raise_window("100", {})


def test_gnome_rejects_non_numeric_window_id(gnome_env):
    calls = gnome_env({})

    with pytest.raises(RuntimeError):
        GnomeAPI().raise_window("-100", {})
    assert calls == []


def test_gnome_missing_xdotool_fails_safely(gnome_env):
    gnome_env({
        "search": FileNotFoundError("xdotool"),
        "windowactivate": FileNotFoundError("xdotool"),
    })

    result = GnomeAPI().focus_result(300, {})

    assert result.state == "failed"
    assert not result.activation.attempted
    assert result.activation.detail == "xdotool is not installed"
    with pytest.raises(RuntimeError, match="not installed"):
        GnomeAPI().raise_window("4194307", {})


def test_gnome_search_timeout_is_unavailable(gnome_env):
    gnome_env({"search": subprocess.TimeoutExpired("xdotool", 2)})

    result = GnomeAPI().focus_result(300, {})

    assert not result.activation.attempted
    assert result.activation.detail == "xdotool search timed out"


def test_gnome_without_x11_display_is_unavailable(gnome_env, monkeypatch):
    calls = gnome_env({})
    monkeypatch.delenv("DISPLAY")

    result = GnomeAPI().focus_result(300, {})

    assert not result.activation.attempted
    assert result.activation.detail == "xdotool needs an X11 display"
    assert calls == []


def test_gnome_is_linux_only(gnome_env, monkeypatch):
    calls = gnome_env({})
    monkeypatch.setattr(gnome.sys, "platform", "darwin")

    result = GnomeAPI().focus_result(300, {})

    assert not result.activation.attempted
    assert "Linux only" in result.activation.detail
    assert calls == []


def test_gnome_walk_without_server_is_bounded_in_steps(gnome_env, monkeypatch):
    calls = gnome_env({})
    visited = []

    def endless(pid):
        visited.append(pid)
        return _process(pid, pid + 1, "bash")

    monkeypatch.setattr(gnome.discovery, "get_process_info", endless)

    result = GnomeAPI().focus_result(300, {})

    assert len(visited) == 64
    assert not result.activation.attempted
    assert result.activation.detail == "no gnome-terminal-server ancestor found"
    assert calls == []


def test_gnome_walk_without_server_is_bounded_in_time(gnome_env, monkeypatch):
    calls = gnome_env({})
    clock = count(0.0, 1.0)
    visited = []

    def slow(pid):
        visited.append(pid)
        return _process(pid, pid + 1, "bash")

    monkeypatch.setattr(gnome.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(gnome.discovery, "get_process_info", slow)

    result = GnomeAPI().focus_result(300, {})

    assert len(visited) <= 3
    assert result.activation.detail == "process ancestry walk timed out"
    assert calls == []


def test_gnome_walk_is_cycle_safe(gnome_env, monkeypatch):
    gnome_env({})
    visited = []

    def cycle(pid):
        visited.append(pid)
        return _process(pid, 301 if pid == 300 else 300, "bash")

    monkeypatch.setattr(gnome.discovery, "get_process_info", cycle)

    result = GnomeAPI().focus_result(300, {})

    assert visited == [300, 301]
    assert not result.activation.attempted


def test_gnome_matches_full_server_executable(gnome_env, monkeypatch):
    gnome_env({"search": _completed("7\n11\n")})
    monkeypatch.setattr(
        gnome.discovery,
        "get_process_info",
        _tree(
            _process(300, 250, "claude"),
            _process(250, 1, "gnome-terminal-", "gnome-terminal-server"),
        ),
    )

    result = GnomeAPI().focus_result(300, {})

    assert "owns 2 windows" in result.activation.detail


def test_gnome_selection_stays_unsupported():
    api = GnomeAPI()
    assert not api.selection_supported
    assert api.find_tab(300, {}) is None
    assert not api.switch_tab("1", {})


class _Window:
    def __init__(self, handle, active_after=True):
        self.handle = handle
        self.active_after = active_after
        self.isActive = False
        self.activated = 0

    def getHandle(self):
        return self.handle

    def activate(self):
        self.activated += 1
        self.isActive = self.active_after
        return True


def _pywinctl(monkeypatch, windows):
    titles = []

    def get_windows(title):
        titles.append(title)
        return list(windows)

    monkeypatch.setitem(
        sys.modules, "pywinctl", SimpleNamespace(getWindowsWithTitle=get_windows)
    )
    return titles


@pytest.mark.parametrize("count_", [0, 2])
def test_windows_terminal_non_unique_window_is_unavailable(monkeypatch, count_):
    windows = [_Window(100 + index) for index in range(count_)]
    _pywinctl(monkeypatch, windows)

    result = WindowsTerminalAPI().focus_result(101, {"WT_SESSION": "guid"})

    assert result.state == "failed"
    assert not result.target_found
    assert not result.activation.attempted
    assert all(window.activated == 0 for window in windows)


def test_windows_terminal_two_windows_detail(monkeypatch):
    _pywinctl(monkeypatch, [_Window(1), _Window(2)])

    result = WindowsTerminalAPI().focus_result(101, {})

    assert result.activation.detail == (
        "2 Windows Terminal windows; exact window unknown"
    )


def test_windows_terminal_unique_window_with_readback_succeeds(monkeypatch):
    window = _Window(4242)
    titles = _pywinctl(monkeypatch, [window])

    result = WindowsTerminalAPI().focus_result(101, {"WT_SESSION": "guid"})

    assert result.state == "partial"
    assert result.target_found
    assert not result.selection.attempted
    assert result.activation.succeeded
    assert window.activated == 1
    assert set(titles) == {windows_terminal.WINDOW_TITLE}


def test_windows_terminal_inactive_after_activate_is_not_success(monkeypatch):
    window = _Window(4242, active_after=False)
    _pywinctl(monkeypatch, [window])

    result = WindowsTerminalAPI().focus_result(101, {})

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded
    assert "did not become active" in result.activation.detail


def test_windows_terminal_without_pywinctl_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "pywinctl", None)

    result = WindowsTerminalAPI().focus_result(101, {})

    assert not result.activation.attempted
    assert result.activation.detail == "pywinctl is not installed"


def test_windows_terminal_target_change_is_not_activated(monkeypatch):
    window = _Window(7)
    _pywinctl(monkeypatch, [window])

    with pytest.raises(RuntimeError, match="changed"):
        WindowsTerminalAPI().raise_window("8", {})
    assert window.activated == 0
