from types import SimpleNamespace

from claude_fleet_monitor.terminal_apis.gnome import GnomeAPI
from claude_fleet_monitor.terminal_apis.windows_terminal import WindowsTerminalAPI


def test_failed_xdotool_activation_is_not_success(monkeypatch):
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.gnome.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    assert not GnomeAPI().raise_window("100", {})


def test_windows_terminal_can_report_activation_only(monkeypatch):
    api = WindowsTerminalAPI()
    monkeypatch.setattr(api, "raise_window", lambda target, env: True)
    result = api.focus_result(101, {"WT_SESSION": "guid"})
    assert result.state == "partial"
    assert result.target_found
    assert not result.selection.attempted
    assert result.activation.succeeded
