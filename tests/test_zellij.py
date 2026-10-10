import inspect
import subprocess

import pytest

from claude_fleet_monitor.terminal_apis import zellij
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.terminator import TerminatorAPI
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI
from tests.terminal_env import clear_terminal_markers

ZELLIJ_ENV = {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": "session"}
PANE_ENV = {**ZELLIJ_ENV, "ZELLIJ_PANE_ID": "3"}
DETECT_PARENT = "claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal"
HEADER = "CLIENT_ID ZELLIJ_PANE_ID RUNNING_COMMAND"


class WindowParent(TerminalAPI):
    name = "window-only"
    selection_supported = False

    def __init__(self, activate=True):
        self.activate = activate
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
        return "window"

    def switch_tab(self, tab_id, env):
        pytest.fail("selection is unsupported")

    def raise_window(self, tab_id, env):
        self.calls.append(("raise", tab_id))
        return self.activate


class FakeZellij:
    """Scripted `_run` replacement keyed by zellij action name."""

    def __init__(self, focus=True, clients=(f"{HEADER}\n1 terminal_3 claude",)):
        self.focus = focus
        self.clients = list(clients)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        action = argv[4]
        if action == "focus-pane-id":
            return self._result(argv, "") if self.focus else None
        if action == "list-clients":
            output = self.clients.pop(0) if len(self.clients) > 1 else self.clients[0]
            return None if output is None else self._result(argv, output)
        pytest.fail(f"unexpected zellij action {action}")

    @staticmethod
    def _result(argv, stdout):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    def actions(self):
        return [call[4] for call in self.calls]


@pytest.fixture(autouse=True)
def forbid_fallbacks(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("zellij test must not start a real process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(
        GenericAPI,
        "__init__",
        lambda self: pytest.fail("GenericAPI must not be constructed"),
    )
    monkeypatch.setattr(zellij.time, "sleep", lambda seconds: None)


@pytest.fixture
def fake(monkeypatch):
    runner = FakeZellij()
    monkeypatch.setattr(zellij, "_run", runner)
    return runner


@pytest.fixture
def no_cli(monkeypatch):
    monkeypatch.setattr(
        zellij, "_run", lambda argv: pytest.fail("rejected before any subprocess call")
    )


def _completed(returncode=0, stdout="", stderr=""):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return run


def test_capture_env_adds_decimal_pane_id(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "fleet")
    monkeypatch.setenv("ZELLIJ_PANE_ID", "12")

    assert ZellijAPI.capture_env() == {
        "ZELLIJ": "0",
        "ZELLIJ_SESSION_NAME": "fleet",
        "ZELLIJ_PANE_ID": "12",
    }


@pytest.mark.parametrize(
    "value", ["", "-1", "+1", "1;2", "1 2", "terminal_1", "x1", "١", "1" * 13]
)
def test_capture_env_omits_non_decimal_pane_id(monkeypatch, value):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "fleet")
    monkeypatch.setenv("ZELLIJ_PANE_ID", value)

    assert "ZELLIJ_PANE_ID" not in ZellijAPI.capture_env()


def test_capture_env_without_zellij_keeps_legacy_shape(monkeypatch):
    clear_terminal_markers(monkeypatch)

    assert ZellijAPI.capture_env() == {"ZELLIJ": "", "ZELLIJ_SESSION_NAME": ""}


def test_capture_env_drops_oversized_session(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "s" * 1025)
    monkeypatch.setenv("ZELLIJ_PANE_ID", "1")

    assert ZellijAPI.capture_env()["ZELLIJ_SESSION_NAME"] == ""


def test_find_tab_returns_captured_pane(no_cli):
    assert ZellijAPI().find_tab(101, dict(PANE_ENV)) == "3"


def test_find_tab_without_env_is_truthfully_none(no_cli):
    assert ZellijAPI().find_tab(101, {}) is None


PRE_CAPTURE = (
    "session recorded before zellij pane capture; restart the agent session"
    " to enable selection"
)


def test_pre_upgrade_record_reports_selection_unavailable(monkeypatch, no_cli):
    with pytest.raises(LookupError, match=f"^{PRE_CAPTURE}$"):
        ZellijAPI().find_tab(101, dict(ZELLIJ_ENV))
    monkeypatch.setattr(DETECT_PARENT, lambda pid: WindowParent())

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.selection.detail == PRE_CAPTURE
    assert result.activation.succeeded


INJECTED_PANES = ["-x", "1;2", "1\x002", "", " 1", "+1", "١", "1" * 13, None, 3]
INJECTED_SESSIONS = ["-x", "--session", "", "a\x00b", "s" * 257, "é" * 129, None, 7]


@pytest.mark.parametrize("pane", INJECTED_PANES)
def test_injected_pane_id_is_rejected_before_subprocess(no_cli, pane):
    env = {**ZELLIJ_ENV, "ZELLIJ_PANE_ID": pane}

    assert ZellijAPI().find_tab(101, env) is None
    assert not ZellijAPI().switch_tab(pane, env)


@pytest.mark.parametrize("session", INJECTED_SESSIONS)
def test_injected_session_is_rejected_before_subprocess(no_cli, session):
    env = {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": session, "ZELLIJ_PANE_ID": "3"}

    assert ZellijAPI().find_tab(101, env) is None
    assert not ZellijAPI().switch_tab("3", env)


def test_session_at_byte_limit_is_accepted(no_cli):
    env = {**PANE_ENV, "ZELLIJ_SESSION_NAME": "é" * 128}

    assert ZellijAPI().find_tab(101, env) == "3"


ON_OTHER = f"{HEADER}\n1 terminal_1 sh"
ON_TARGET = f"{HEADER}\n1 terminal_3 claude"
LIST = ["zellij", "--session", "session", "action", "list-clients"]
FOCUS = ["zellij", "--session", "session", "action", "focus-pane-id", "terminal_3"]


def test_switch_tab_selects_exact_pane_with_before_and_after_readback(fake):
    fake.clients = [ON_OTHER, ON_TARGET]

    api = ZellijAPI()
    assert api.switch_tab("3", dict(PANE_ENV))
    assert fake.calls == [LIST, FOCUS, LIST]
    assert api._selection_detail is None


def test_focus_result_is_complete_with_selection_and_parent(monkeypatch, fake):
    fake.clients = [ON_OTHER, ON_TARGET]
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.state == "complete"
    assert result.selection.succeeded
    assert result.selection.detail == "tab or pane selection"
    assert result.activation.succeeded
    assert fake.actions() == ["list-clients", "focus-pane-id", "list-clients"]
    assert parent.calls == [("target", 101), ("raise", "window")]


def test_selection_without_parent_is_partial(monkeypatch, fake):
    fake.clients = [ON_OTHER, ON_TARGET]
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.state == "partial"
    assert result.selection.succeeded
    assert not result.activation.succeeded


def test_readback_waits_for_client_to_move(fake):
    fake.clients = [ON_OTHER, ON_OTHER, ON_TARGET]

    assert ZellijAPI().switch_tab("3", dict(PANE_ENV))
    assert fake.actions() == [
        "list-clients", "focus-pane-id", "list-clients", "list-clients"
    ]


def test_idle_client_already_on_target_is_not_selection_proof(fake):
    rows = f"{HEADER}\n1 terminal_1 sh\n2 terminal_3 claude"
    fake.clients = [rows]

    with pytest.raises(RuntimeError, match="no zellij client moved to pane 3"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))
    assert fake.actions().count("focus-pane-id") == 1
    assert fake.actions().count("list-clients") == 1 + zellij.READBACK_ATTEMPTS


def test_active_client_moving_to_target_is_success(fake):
    fake.clients = [
        f"{HEADER}\n1 terminal_1 sh\n2 terminal_3 claude",
        f"{HEADER}\n1 terminal_3 claude\n2 terminal_3 claude",
    ]

    assert ZellijAPI().switch_tab("3", dict(PANE_ENV))


def test_newly_attached_client_on_target_is_not_selection_proof(fake):
    fake.clients = [ON_OTHER, f"{HEADER}\n1 terminal_1 sh\n2 terminal_3 claude"]

    with pytest.raises(RuntimeError, match="no zellij client moved to pane 3"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))


@pytest.mark.parametrize(
    "rows", ["1 terminal_3 claude", "1 terminal_3 claude\n2 terminal_3 claude"]
)
def test_all_clients_already_on_target_is_success_with_detail(
    monkeypatch, fake, rows
):
    fake.clients = [f"{HEADER}\n{rows}"]
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.selection.attempted
    assert result.selection.succeeded
    assert result.selection.detail == "pane already focused"
    assert fake.actions() == ["list-clients"]


def test_already_focused_detail_does_not_leak_into_later_selection(fake):
    api = ZellijAPI()
    fake.clients = [ON_TARGET]
    assert api.switch_tab("3", dict(PANE_ENV))
    fake.clients = [ON_OTHER, ON_TARGET]

    result = api.focus_result(101, dict(PANE_ENV))

    assert result.selection.detail == "tab or pane selection"


@pytest.mark.parametrize(
    "rows", ["1 terminal_1 sh", "1 terminal_31 sh\n2 terminal_13 sh", "1 plugin_3"]
)
def test_readback_mismatch_is_failure_with_detail(fake, rows):
    fake.clients = [f"{HEADER}\n{rows}"]

    with pytest.raises(RuntimeError, match="no zellij client moved to pane 3"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))
    assert fake.actions().count("list-clients") == 1 + zellij.READBACK_ATTEMPTS


def test_zero_clients_is_failure_with_detail(monkeypatch, fake):
    fake.clients = [HEADER]
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.selection.attempted
    assert not result.selection.succeeded
    assert result.selection.detail == "no attached zellij client"
    assert fake.actions() == ["list-clients"]


def test_clients_detaching_after_selection_is_failure(fake):
    fake.clients = [ON_OTHER, HEADER]

    with pytest.raises(RuntimeError, match="no attached zellij client"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))


def test_failed_snapshot_command_is_failure_before_selection(fake):
    fake.clients = [None]

    with pytest.raises(RuntimeError, match="list-clients snapshot failed"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))
    assert fake.actions() == ["list-clients"]


def test_failed_readback_command_is_failure(fake):
    fake.clients = [ON_OTHER, None]

    with pytest.raises(RuntimeError, match="list-clients readback failed"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))


def test_failed_focus_command_skips_readback(fake):
    fake.clients = [ON_OTHER]
    fake.focus = False

    with pytest.raises(RuntimeError, match="could not focus pane 3"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))
    assert fake.actions() == ["list-clients", "focus-pane-id"]


def test_run_uses_bounded_timeout(monkeypatch):
    seen = {}

    def record(argv, **kwargs):
        seen.update(kwargs)
        return _completed()(argv, **kwargs)

    monkeypatch.setattr(zellij.subprocess, "run", record)

    assert zellij._run(["zellij", "--version"]).returncode == 0
    assert 0 < seen["timeout"] <= 5
    assert seen["stdin"] is subprocess.DEVNULL
    assert "shell" not in seen


def _raise(error):
    def run(argv, **kwargs):
        raise error

    return run


@pytest.mark.parametrize(
    "run",
    [
        pytest.param(_raise(FileNotFoundError("zellij")), id="missing-cli"),
        pytest.param(_raise(PermissionError("zellij")), id="not-executable"),
        pytest.param(_raise(subprocess.TimeoutExpired("zellij", 5)), id="timeout"),
        pytest.param(
            _completed(2, stderr="Pane with id Terminal(3) not found"), id="stale-id"
        ),
        pytest.param(_completed(1, stderr="session not found"), id="nonzero-exit"),
        pytest.param(
            _completed(2, stderr="error: unrecognized subcommand 'focus-pane-id'"),
            id="older-version-without-focus-pane-id",
        ),
    ],
)
def test_cli_failures_give_selection_failure_with_detail(monkeypatch, run):
    calls = []

    def record(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "list-clients":
            return subprocess.CompletedProcess(argv, 0, ON_OTHER, "")
        return run(argv, **kwargs)

    monkeypatch.setattr(zellij.subprocess, "run", record)
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    assert zellij._run(["zellij"]) is None
    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.state == "failed"
    assert result.selection.attempted
    assert not result.selection.succeeded
    assert result.selection.detail.startswith("zellij could not focus pane 3")
    assert len(result.selection.detail) <= 120
    assert [call[4] for call in calls[1:]] == ["list-clients", "focus-pane-id"]


@pytest.mark.parametrize(
    "run",
    [
        pytest.param(_raise(FileNotFoundError("zellij")), id="missing-cli"),
        pytest.param(_raise(subprocess.TimeoutExpired("zellij", 5)), id="timeout"),
        pytest.param(_completed(1, stderr="session not found"), id="no-session"),
    ],
)
def test_snapshot_cli_failures_skip_selection(monkeypatch, run):
    calls = []

    def record(argv, **kwargs):
        calls.append(argv)
        return run(argv, **kwargs)

    monkeypatch.setattr(zellij.subprocess, "run", record)
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.state == "failed"
    assert result.selection.attempted
    assert result.selection.detail.startswith("zellij list-clients snapshot failed")
    assert len(result.selection.detail) <= 120
    assert [call[4] for call in calls] == ["list-clients"]


@pytest.mark.parametrize(
    "output",
    ["CLIENT_ID RUNNING_COMMAND\n1 sh", "", "error: unexpected output"],
    ids=["older-version-columns", "empty", "garbage"],
)
def test_unrecognized_readback_is_failure_naming_validated_version(fake, output):
    fake.clients = [output]

    with pytest.raises(RuntimeError, match="validated with zellij 0.45.1"):
        ZellijAPI().switch_tab("3", dict(PANE_ENV))


def test_zellij_parent_activation_is_truthful(monkeypatch):
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.activation.succeeded
    assert parent.calls == [("target", 101), ("raise", "window")]


def test_zellij_failed_parent_activation_is_not_success(monkeypatch):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: WindowParent(activate=False))

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded


def test_zellij_without_parent_reports_activation_detail(monkeypatch):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "no parent terminal emulator found for zellij"
    )


def test_zellij_in_terminator_reports_unsupported_parent(monkeypatch):
    for method in ("find_tab", "switch_tab", "raise_window", "focus_result"):
        monkeypatch.setattr(
            TerminatorAPI,
            method,
            lambda *args, **kwargs: pytest.fail("Terminator cannot focus"),
        )
    monkeypatch.setattr(DETECT_PARENT, lambda pid: TerminatorAPI())

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "parent terminal terminator does not support window activation"
    )


def test_zellij_raise_window_rejects_non_numeric_target(monkeypatch):
    monkeypatch.setattr(
        DETECT_PARENT, lambda pid: pytest.fail("no parent lookup for bad target")
    )

    assert not ZellijAPI().raise_window("not-a-pid", dict(ZELLIJ_ENV))


def test_zellij_without_env_has_no_target(monkeypatch, no_cli):
    monkeypatch.setattr(
        DETECT_PARENT, lambda pid: pytest.fail("no parent lookup without zellij env")
    )

    result = ZellijAPI().focus_result(101, {})

    assert result.state == "failed"
    assert not result.target_found
    assert not result.selection.attempted
    assert not result.activation.attempted


def test_zellij_module_has_one_subprocess_seam_and_no_fallback():
    assert "GenericAPI" not in vars(zellij)
    assert inspect.getsource(zellij).count("subprocess.run(") == 1
    assert ZellijAPI.selection_supported
