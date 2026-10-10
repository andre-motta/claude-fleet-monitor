from types import SimpleNamespace

from claude_fleet_monitor.models import FocusOperation, FocusResult
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI


def test_zellij_parent_activation_is_truthful(monkeypatch):
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
