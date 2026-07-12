import os

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


def test_detect_gnome(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("ZELLIJ", raising=False)
    monkeypatch.delenv("KONSOLE_VERSION", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    monkeypatch.setenv("VTE_VERSION", "7200")
    from claude_fleet_monitor.terminal_apis import detect_terminal
    t = detect_terminal()
    assert t.name == "gnome"


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
