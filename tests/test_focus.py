import json
import os

import pytest

import claude_fleet_monitor.focus as focus_module
import claude_fleet_monitor.mcp_server as mcp_server
from claude_fleet_monitor.focus import focus, focus_notification, focus_session
from claude_fleet_monitor.models import FocusOperation, FocusResult
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from tests.conftest import write_session


def test_find_session_by_repo(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result is not None
    assert result["repo"] == "myrepo"


def test_find_session_by_id(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("abc-123")
    assert result is not None
    assert result["session_id"] == "abc-123"


def test_find_session_no_match(fleet_dir):
    write_session(fleet_dir, "abc-123", "myrepo", "/tmp/myrepo")
    from claude_fleet_monitor.focus import find_session
    result = find_session("nonexistent")
    assert result is None


def test_find_session_prefers_hook_over_proc(fleet_dir):
    write_session(fleet_dir, "hook-sess", "myrepo", "/tmp/myrepo")
    write_session(fleet_dir, "proc-99999", "myrepo", "/tmp/myrepo", source="process")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result["session_id"] == "hook-sess"


def test_find_session_multiple_returns_none(fleet_dir):
    write_session(fleet_dir, "sess-1", "myrepo", "/tmp/myrepo")
    write_session(fleet_dir, "sess-2", "myrepo", "/tmp/myrepo2")
    from claude_fleet_monitor.focus import find_session
    result = find_session("myrepo")
    assert result is None


def test_get_pid_from_proc_session(fleet_dir):
    from claude_fleet_monitor.discovery import ProcessInfo
    import claude_fleet_monitor.focus as focus_module
    from claude_fleet_monitor.focus import get_pid
    process = ProcessInfo(
        12345, 1, "claude", "claude", ("claude",), "/tmp/myrepo", "1"
    )
    original = focus_module.resolve_session_process
    focus_module.resolve_session_process = lambda value: process
    session = {"session_id": "proc-12345", "pid": "12345", "cwd": "/tmp/myrepo"}
    try:
        assert get_pid(session) == 12345
    finally:
        focus_module.resolve_session_process = original


def test_get_pid_from_stored_pid(fleet_dir, monkeypatch):
    from claude_fleet_monitor.discovery import ProcessInfo
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.resolve_session_process",
        lambda value: ProcessInfo(
            os.getpid(), 1, "claude", "claude", ("claude",), value["cwd"], "1"
        ),
    )
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": str(os.getpid()), "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result == os.getpid()


def test_get_pid_dead_stored_pid(fleet_dir, monkeypatch):
    monkeypatch.setattr(
        "claude_fleet_monitor.focus.resolve_session_process", lambda value: None
    )
    from claude_fleet_monitor.focus import get_pid
    session = {"session_id": "abc-123", "pid": "999999", "cwd": "/tmp/myrepo"}
    result = get_pid(session)
    assert result is None


def _operation(succeeded, detail, attempted=True):
    return FocusOperation(attempted, succeeded, detail)


@pytest.mark.parametrize(
    ("result", "message", "severity"),
    [
        (
            FocusResult(
                state="complete",
                reason="target selected and window activated",
                target_found=True,
                selection=_operation(True, "tab or pane selection"),
                activation=_operation(True, "window activation"),
            ),
            "Focused: repo",
            "information",
        ),
        (
            FocusResult(
                state="partial",
                reason="only some terminal focus operations failed",
                target_found=True,
                selection=FocusOperation.unavailable(
                    "backend does not support exact tab or pane selection"
                ),
                activation=_operation(True, "window activation"),
            ),
            "Partially focused: repo (selection: unsupported; activation: ok)",
            "warning",
        ),
        (
            FocusResult(
                state="partial",
                reason="only some terminal focus operations failed",
                target_found=True,
                selection=_operation(True, "tab or pane selection"),
                activation=_operation(False, "window activation"),
            ),
            "Partially focused: repo (selection: ok; activation: failed)",
            "warning",
        ),
        (
            FocusResult(
                state="failed",
                reason="terminal focus operations failed",
                target_found=True,
                selection=_operation(False, "Konsole could not select tab 2"),
                activation=_operation(False, "KWin script could not be loaded"),
            ),
            "Focus Failed: repo: terminal focus operations failed"
            " (selection: Konsole could not select tab 2;"
            " activation: KWin script could not be loaded)",
            "error",
        ),
        (
            FocusResult(
                state="failed",
                reason="terminal focus operations failed",
                selection=FocusOperation.unavailable(
                    "exact tab or pane target was not found"
                ),
                activation=FocusOperation.unavailable(
                    "window activation target was not found"
                ),
            ),
            "Focus Failed: repo: terminal focus operations failed"
            " (selection: exact tab or pane target was not found;"
            " activation: window activation target was not found)",
            "error",
        ),
        (
            FocusResult(
                state="unavailable",
                reason="stored process identity is unavailable or stale",
            ),
            "Focus Unavailable: repo: stored process identity is unavailable"
            " or stale",
            "error",
        ),
        (
            FocusResult(state="not-found", reason="no session matching 'repo'"),
            "Focus Not found: repo: no session matching 'repo'",
            "error",
        ),
    ],
)
def test_focus_notification_names_failed_steps(result, message, severity):
    assert focus_notification(result, "repo") == (message, severity)


def test_focus_notification_bounds_and_strips_details():
    result = FocusResult(
        state="partial",
        reason="only some terminal focus operations failed",
        target_found=True,
        selection=_operation(False, "line\nbreak\0 \u2014 " + "x" * 300),
        activation=_operation(True, "window activation"),
    )

    message, severity = focus_notification(result, "repo")

    assert severity == "warning"
    assert "\n" not in message and "\0" not in message
    prefix = "Partially focused: repo (selection: "
    assert message.startswith(prefix + "line break \u2014 x")
    detail = message.removeprefix(prefix)
    detail = detail.split("; activation:")[0]
    assert len(detail) == 120 and detail.endswith("...")
    assert message.endswith("; activation: ok)")


def test_focus_notification_keeps_activation_after_long_selection():
    result = FocusResult(
        state="failed",
        reason="terminal focus operations failed",
        selection=_operation(False, "s" * 150),
        activation=_operation(False, "KWin script could not be loaded"),
    )

    message, _ = focus_notification(result, "repo")

    assert message.endswith(
        "; activation: KWin script could not be loaded)"
    )
    selection = message.split("(selection: ")[1].split("; activation:")[0]
    assert selection.endswith("...")
    assert len(selection) == 120 - len("KWin script could not be loaded")


def test_focus_notification_caps_each_long_detail_separately():
    result = FocusResult(
        state="failed",
        reason="terminal focus operations failed",
        selection=_operation(False, "s" * 150),
        activation=_operation(False, "a" * 150),
    )

    message, _ = focus_notification(result, "repo")

    details = message.split(" (selection: ")[1].removesuffix(")")
    selection, activation = details.split("; activation: ")
    assert selection == "s" * 57 + "..."
    assert activation == "a" * 57 + "..."


@pytest.mark.parametrize(
    "result",
    [
        FocusResult(state="unavailable", reason="no  captured\tterminal  "),
        FocusResult(state="not-found", reason="no session matching 'x' " * 20),
    ],
)
def test_focus_notification_keeps_terminal_states_verbatim(result):
    label = result.state.replace("-", " ").capitalize()

    assert focus_notification(result, "repo") == (
        f"Focus {label}: repo: {result.reason}",
        "error",
    )


def test_focus_notification_keeps_ambiguous_identities_verbatim(fleet_dir):
    for index in range(12):
        write_session(
            fleet_dir, f"session-{index:02d}-" + "z" * 20, "repo", "/tmp/repo"
        )

    result = focus_session("repo")
    message, severity = focus_notification(result, "repo")

    assert result.state == "ambiguous"
    assert message == f"Focus Ambiguous: repo: {result.reason}"
    assert severity == "error"
    assert len(message) > 200
    assert all(f"session-{index:02d}-" in message for index in range(12))


class _RaisingSelectionAPI(TerminalAPI):
    name = "stub"

    def __init__(self, verified):
        self.verified = verified

    @staticmethod
    def detect():
        return False

    @staticmethod
    def capture_env():
        return {}

    def find_tab(self, pid, terminal_env):
        return "tab"

    def switch_tab(self, tab_id, terminal_env):
        raise RuntimeError("readback is stale until activation")

    def raise_window(self, tab_id, terminal_env):
        return True

    def verify_selection(self, tab_id, terminal_env):
        return self.verified


@pytest.mark.parametrize(
    ("verified", "state", "detail"),
    [
        (True, "complete", "tab or pane selection verified after activation"),
        (False, "partial", "readback is stale until activation"),
    ],
)
def test_raising_selection_step_still_reaches_verification(
    verified, state, detail
):
    result = _RaisingSelectionAPI(verified).focus_result(42, {})

    assert result.state == state
    assert result.selection.attempted
    assert result.selection.detail == detail


def test_unsupported_step_leaves_the_budget_to_the_other_step():
    result = FocusResult(
        state="failed",
        reason="terminal focus operations failed",
        target_found=True,
        selection=FocusOperation.unavailable(
            "backend does not support exact tab or pane selection"
        ),
        activation=_operation(False, "a" * 150),
    )

    message, _ = focus_notification(result, "repo")

    details = message.split(" (selection: ")[1].removesuffix(")")
    selection, activation = details.split("; activation: ")
    assert selection == "unsupported"
    assert activation == "a" * (120 - len("unsupported") - 3) + "..."


def test_attempted_unsupported_wording_is_kept_verbatim():
    detail = "parent terminal kitty does not support window activation"
    result = FocusResult(
        state="partial",
        reason="only some terminal focus operations succeeded",
        target_found=True,
        selection=_operation(True, "tab or pane selection"),
        activation=_operation(False, detail),
    )

    message, _ = focus_notification(result, "repo")

    assert message.endswith(f"activation: {detail})")


PARTIAL = FocusResult(
    state="partial",
    reason="only some terminal focus operations succeeded",
    backend="konsole",
    pid=42,
    target_found=True,
    selection=_operation(True, "tab or pane selection"),
    activation=_operation(False, "window did not become active within 1s"),
)
FAILED = FocusResult(
    state="failed",
    reason="terminal focus operations failed",
    backend="tmux",
    pid=42,
    target_found=True,
    selection=_operation(False, "tab or pane selection"),
    activation=_operation(False, "no attached tmux client shows the pane"),
)
COMPLETE = FocusResult(
    state="complete",
    reason="target selected and window activated",
    backend="konsole",
    pid=42,
    target_found=True,
    selection=_operation(True, "tab or pane selection"),
    activation=_operation(True, "window activation"),
)


@pytest.mark.parametrize(
    ("result", "succeeded", "stdout", "stderr"),
    [
        (COMPLETE, True, "Focused session via konsole (PID 42)\n", ""),
        (
            PARTIAL,
            True,
            "Partially focused session via konsole (PID 42) (selection: ok;"
            " activation: window did not become active within 1s)\n",
            "",
        ),
        (
            FAILED,
            False,
            "",
            "terminal focus operations failed (selection: failed;"
            " activation: no attached tmux client shows the pane)\n",
        ),
        (
            FocusResult(state="unavailable", reason="no safe target"),
            False,
            "",
            "no safe target\n",
        ),
        (
            FocusResult(state="not-found", reason="no session matching 'x'"),
            False,
            "",
            "no session matching 'x'\n",
        ),
    ],
    ids=["complete", "partial", "failed", "unavailable", "not-found"],
)
def test_cli_focus_prints_step_details(
    monkeypatch, capsys, result, succeeded, stdout, stderr
):
    monkeypatch.setattr(focus_module, "focus_session", lambda query: result)

    assert focus("repo") is succeeded
    assert capsys.readouterr() == (stdout, stderr)


@pytest.mark.parametrize(
    ("result", "payload"),
    [
        (
            PARTIAL,
            {
                "success": True,
                "message": "Partially focused session via konsole (PID 42)"
                " (selection: ok; activation: window did not become active"
                " within 1s)",
            },
        ),
        (
            FAILED,
            {
                "success": False,
                "error": "terminal focus operations failed (selection: failed;"
                " activation: no attached tmux client shows the pane)",
            },
        ),
    ],
    ids=["partial", "failed"],
)
def test_mcp_focus_reports_step_details(monkeypatch, result, payload):
    monkeypatch.setattr(focus_module, "focus_session", lambda query: result)

    assert json.loads(mcp_server.fleet_focus("repo")) == payload
