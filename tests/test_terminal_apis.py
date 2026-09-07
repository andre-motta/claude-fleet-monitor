import os
from types import SimpleNamespace

import pytest


def test_detect_konsole(monkeypatch):
    monkeypatch.setenv("KONSOLE_VERSION", "260402")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "konsole"


def test_detect_tmux(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,12345,0")
    monkeypatch.delenv("ZELLIJ", raising=False)
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "tmux"


def test_detect_tmux_over_konsole(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,12345,0")
    monkeypatch.setenv("KONSOLE_VERSION", "260402")
    monkeypatch.delenv("ZELLIJ", raising=False)
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "tmux"


def test_detect_zellij(monkeypatch):
    monkeypatch.setenv("ZELLIJ", "1")
    monkeypatch.delenv("TMUX", raising=False)
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "zellij"


def test_detect_iterm2(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:12345")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "iterm2"


def test_detect_macos_terminal(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "macos_terminal"


def test_detect_ghostty(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "ghostty"


def test_detect_ghostty_capture_env(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.setenv("GHOSTTY_BIN_DIR", "/usr/bin")
    from claude_fleet_monitor.terminal_apis import capture_terminal_info
    info = capture_terminal_info()
    assert info["terminal"] == "ghostty"
    assert info["terminal_env"]["GHOSTTY_BIN_DIR"] == "/usr/bin"


def test_detect_gnome(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("VTE_VERSION", "7200")
    monkeypatch.setenv("GNOME_TERMINAL_SERVICE", ":1.2")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "gnome"


def test_vte_alone_does_not_claim_gnome_terminal(monkeypatch):
    for var in (
        "TMUX", "ZELLIJ", "KONSOLE_VERSION", "ITERM_SESSION_ID",
        "TERM_PROGRAM", "GNOME_TERMINAL_SERVICE", "WT_SESSION",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VTE_VERSION", "7200")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    assert detect_terminal().name == "generic"


def test_failed_xdotool_activation_is_not_success(monkeypatch):
    from types import SimpleNamespace
    from claude_fleet_monitor.terminal_apis.gnome import GnomeAPI
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.gnome.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    assert not GnomeAPI().raise_window("100", {})


def test_ghostty_missing_ancestry_is_not_a_tab(monkeypatch):
    from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.ghostty._find_ghostty_pid",
        lambda: None,
    )
    result = GhosttyAPI().focus_result(101, {})
    assert result.state == "failed"
    assert not result.target_found


def test_ghostty_activates_before_global_tab_keys(monkeypatch):
    from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI

    calls = []
    api = GhosttyAPI()
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.ghostty.time.sleep",
        lambda seconds: calls.append(("delay", seconds)),
    )
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "101:2")
    monkeypatch.setattr(
        api, "raise_window", lambda target, env: calls.append("activate") or True
    )
    monkeypatch.setattr(
        api, "switch_tab", lambda target, env: calls.append("select") or True
    )
    result = api.focus_result(101, {})
    assert calls == ["activate", ("delay", 0.15), "select"]
    assert result.complete


def test_ghostty_skips_global_keys_when_activation_fails(monkeypatch):
    from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI

    api = GhosttyAPI()
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "101:2")
    monkeypatch.setattr(api, "raise_window", lambda target, env: False)
    monkeypatch.setattr(
        api,
        "switch_tab",
        lambda target, env: pytest.fail("global keys must not be sent"),
    )
    result = api.focus_result(101, {})
    assert result.state == "failed"
    assert not result.selection.attempted


def test_windows_terminal_can_report_activation_only(monkeypatch):
    from claude_fleet_monitor.terminal_apis.windows_terminal import WindowsTerminalAPI

    api = WindowsTerminalAPI()
    monkeypatch.setattr(api, "raise_window", lambda target, env: True)
    result = api.focus_result(101, {"WT_SESSION": "guid"})
    assert result.state == "partial"
    assert result.target_found
    assert not result.selection.attempted
    assert result.activation.succeeded


def test_zellij_parent_activation_is_truthful(monkeypatch):
    from claude_fleet_monitor.models import FocusOperation, FocusResult
    from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI

    parent = SimpleNamespace(
        focus_result=lambda pid, env: FocusResult(
            state="partial",
            reason="window activated",
            activation=FocusOperation(True, True, "window activation"),
        )
    )
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal",
        lambda pid: parent,
    )
    result = ZellijAPI().focus_result(
        101, {"ZELLIJ": "1", "ZELLIJ_SESSION_NAME": "session"}
    )
    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.activation.succeeded


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("claude_fleet_monitor.terminal_apis.iterm2", "ITerm2API"),
        ("claude_fleet_monitor.terminal_apis.macos_terminal", "MacOSTerminalAPI"),
    ],
)
def test_macos_selection_reads_text_output(monkeypatch, module_name, class_name):
    module = __import__(module_name, fromlist=[class_name])
    api = getattr(module, class_name)()
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="focused\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert api.switch_tab("target", {})
    assert calls[0]["text"] is True


def test_detect_windows_terminal(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.delenv("VTE_VERSION", raising=False)
    monkeypatch.delenv("GNOME_TERMINAL_SERVICE", raising=False)
    monkeypatch.setenv("WT_SESSION", "some-guid")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "windows_terminal"


def test_detect_generic_fallback(monkeypatch):
    for var in ("TMUX", "ZELLIJ", "KONSOLE_VERSION", "ITERM_SESSION_ID",
                "TERM_PROGRAM", "VTE_VERSION", "GNOME_TERMINAL_SERVICE", "WT_SESSION"):
        monkeypatch.delenv(var, raising=False)
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "generic"


def test_capture_terminal_info_konsole(monkeypatch):
    monkeypatch.setenv("KONSOLE_VERSION", "260402")
    monkeypatch.setenv("KONSOLE_DBUS_SERVICE", "org.kde.konsole-12345")
    monkeypatch.setenv("KONSOLE_DBUS_SESSION", "/Sessions/3")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    from claude_fleet_monitor.terminal_apis import capture_terminal_info
    info = capture_terminal_info()
    assert info["terminal"] == "konsole"
    assert info["terminal_env"]["KONSOLE_DBUS_SERVICE"] == "org.kde.konsole-12345"


def test_capture_terminal_info_tmux(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,12345,0")
    monkeypatch.delenv("ZELLIJ", raising=False)
    from claude_fleet_monitor.terminal_apis import capture_terminal_info
    info = capture_terminal_info()
    assert info["terminal"] == "tmux"
    assert "/tmp/tmux-1000/default" in info["terminal_env"]["TMUX"]


def test_get_terminal_api(monkeypatch):
    from claude_fleet_monitor.terminal_apis import get_terminal_api
    api = get_terminal_api("konsole")
    assert api.name == "konsole"
    api = get_terminal_api("tmux")
    assert api.name == "tmux"
    api = get_terminal_api("nonexistent")
    assert api.name == "generic"
