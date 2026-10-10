import inspect
import subprocess

import pytest

from claude_fleet_monitor.discovery import ProcessInfo
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
SOCKET_DIR = "/run/user/1000/zellij"
SOCKET_PATH = f"{SOCKET_DIR}/contract_version_1/session"
CLIENT_PID = 300
CLIENT_START = "777"
TTY = 34816
FIND_SERVER = zellij._find_server


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
        self.envs = []

    def __call__(self, argv, env=None):
        self.calls.append(list(argv))
        self.envs.append(env)
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
    monkeypatch.setattr(zellij, "_find_server", lambda pid: None)
    monkeypatch.setattr(
        zellij._unix_peers,
        "peer_owners",
        lambda *args: pytest.fail("peer scan needs an explicit host fixture"),
    )
    monkeypatch.setattr(
        zellij.discovery,
        "get_process_info",
        lambda pid: pytest.fail("process lookup needs an explicit host fixture"),
    )


def _info(pid, argv, start="1", ppid=1, name="zellij"):
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=name,
        executable=name,
        argv=tuple(argv),
        cwd=None,
        start_token=start,
    )


class Host:
    """Mocked Linux host: a zellij server, its peer sockets and processes."""

    def __init__(self, monkeypatch):
        self.server = _info(50, ("zellij", "--server", SOCKET_PATH), start="10")
        self.processes = {}
        self.owners = {}
        self.ttys = {}
        self.starts = {}
        self.peer_calls = []
        monkeypatch.setattr(zellij.sys, "platform", "linux")
        monkeypatch.setattr(zellij, "_find_server", lambda pid: self.server)
        monkeypatch.setattr(zellij._unix_peers, "peer_owners", self._peer_owners)
        monkeypatch.setattr(
            zellij._unix_peers, "controlling_tty", lambda pid: self.ttys.get(pid)
        )
        monkeypatch.setattr(zellij.discovery, "get_process_info", self._process)

    def client(self, pid=CLIENT_PID, *args, tty=TTY, start=CLIENT_START):
        argv = ("zellij", *args) if args else ("zellij", "attach", "session")
        self.processes[pid] = _info(pid, argv, start=start, ppid=pid - 1)
        self.owners[1000 + pid] = frozenset({pid})
        self.ttys[pid] = tty
        return pid

    def _peer_owners(self, server_pid, socket_path, comm):
        self.peer_calls.append((server_pid, socket_path, comm))
        return None if self.owners is None else dict(self.owners)

    def _process(self, pid):
        process = self.processes.get(pid)
        starts = self.starts.get(pid)
        if process is not None and starts:
            process = _info(pid, process.argv, start=starts.pop(0), ppid=process.ppid)
        return process


@pytest.fixture
def host(monkeypatch):
    return Host(monkeypatch)


@pytest.fixture
def attached(host):
    host.client()
    return host


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


def test_pre_upgrade_record_reports_selection_unavailable(
    monkeypatch, fake, attached
):
    with pytest.raises(LookupError, match=f"^{PRE_CAPTURE}$"):
        ZellijAPI().find_tab(101, dict(ZELLIJ_ENV))
    monkeypatch.setattr(DETECT_PARENT, lambda pid: WindowParent())

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.selection.detail == PRE_CAPTURE
    assert result.activation.succeeded
    assert fake.actions() == ["list-clients"]


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


def test_focus_result_is_complete_with_selection_and_parent(
    monkeypatch, fake, attached
):
    fake.clients = [ON_OTHER, ON_OTHER, ON_TARGET]
    parent = WindowParent()
    detected = []
    monkeypatch.setattr(DETECT_PARENT, lambda pid: detected.append(pid) or parent)

    result = ZellijAPI().focus_result(101, dict(PANE_ENV))

    assert result.state == "complete"
    assert result.selection.succeeded
    assert result.selection.detail == "tab or pane selection"
    assert result.activation.succeeded
    assert fake.actions() == [
        "list-clients", "list-clients", "focus-pane-id", "list-clients"
    ]
    assert detected == [CLIENT_PID]
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]
    assert attached.peer_calls == [(50, SOCKET_PATH, "zellij")]
    assert all(env["ZELLIJ_SOCKET_DIR"] == SOCKET_DIR for env in fake.envs)


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


def test_zellij_parent_activation_is_truthful(monkeypatch, fake, attached):
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.activation.succeeded
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


def test_zellij_failed_parent_activation_is_not_success(monkeypatch, fake, attached):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: WindowParent(activate=False))

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == (
        f"parent terminal {WindowParent.name} did not activate"
    )


class UnconfirmedTabParent(WindowParent):
    name = "deferred"
    selection_supported = True
    deferred_selection_readback = True

    def find_tab(self, pid, env):
        return "tab"

    def switch_tab(self, tab_id, env):
        return False

    def verify_selection(self, tab_id, env):
        return False


def test_zellij_parent_with_unconfirmed_tab_is_not_success(
    monkeypatch, fake, attached
):
    parent = UnconfirmedTabParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "parent terminal deferred raised its window but could not confirm the tab"
    )
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


def test_zellij_without_parent_reports_activation_detail(monkeypatch, fake, attached):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "no parent terminal emulator found for zellij"
    )


def test_zellij_in_terminator_reports_unsupported_parent(monkeypatch, fake, attached):
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


ONE_CLIENT = f"{HEADER}\n1 terminal_3 claude"
TWO_CLIENTS = f"{HEADER}\n1 terminal_3 claude\n2 terminal_1 sh"


def _activation(monkeypatch, env=ZELLIJ_ENV):
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)
    return parent, ZellijAPI().focus_result(101, dict(env))


def _unavailable(result, detail):
    assert not result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == detail


def test_one_attached_client_routes_to_its_parent(monkeypatch, fake, attached):
    fake.clients = [ONE_CLIENT]
    detected = []
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: detected.append(pid) or parent)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.activation.succeeded
    assert detected == [CLIENT_PID]
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


def test_two_listed_clients_are_refused_before_peer_scan(monkeypatch, fake, attached):
    fake.clients = [TWO_CLIENTS]

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.SEVERAL_CLIENTS)
    assert parent.calls == []
    assert attached.peer_calls == []


def test_two_client_processes_are_refused(monkeypatch, fake, attached):
    attached.client(400)

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.SEVERAL_CLIENTS)
    assert parent.calls == []


def test_watcher_is_refused(monkeypatch, fake, attached):
    attached.client(400, "--config-dir", "/c", "watch", "session")

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.WATCHER)
    assert parent.calls == []


def test_transient_action_peer_is_ignored(monkeypatch, fake, attached):
    attached.client(400, "--session", "session", "action", "list-clients")

    parent, result = _activation(monkeypatch)

    assert result.activation.succeeded
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


def test_only_a_transient_peer_is_a_mismatch(monkeypatch, fake, host):
    host.client(400, "--session", "session", "action", "list-clients")

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.MISMATCH)
    assert parent.calls == []


@pytest.mark.parametrize(
    "owners", [frozenset(), frozenset({CLIENT_PID, 400})], ids=["unowned", "shared"]
)
def test_peer_without_exactly_one_owner_is_a_mismatch(
    monkeypatch, fake, attached, owners
):
    attached.owners[99] = owners

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.MISMATCH)
    assert parent.calls == []


def test_client_without_controlling_tty_is_refused(monkeypatch, fake, host):
    host.client(tty=0)

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.NO_TTY)
    assert parent.calls == []


def test_peer_scan_failure_is_unavailable_without_raising(monkeypatch, fake, host):
    host.owners = None

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.PEERS_UNREADABLE)
    assert parent.calls == []


def test_zero_listed_clients_is_unavailable(monkeypatch, fake, attached):
    fake.clients = [HEADER]

    parent, result = _activation(monkeypatch)

    _unavailable(result, "no attached zellij client")
    assert attached.peer_calls == []


def test_no_server_ancestor_is_unavailable_without_cli(monkeypatch, no_cli):
    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.NO_SERVER)
    assert parent.calls == []


def test_non_linux_is_unavailable_without_lookups(monkeypatch, no_cli):
    monkeypatch.setattr(zellij.sys, "platform", "darwin")
    monkeypatch.setattr(zellij, "_find_server", FIND_SERVER)

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.NOT_LINUX)
    assert parent.calls == []


def test_missing_session_name_is_unavailable(monkeypatch, attached, no_cli):
    parent, result = _activation(monkeypatch, {"ZELLIJ": "0"})

    _unavailable(result, zellij.NO_SESSION_NAME)


def test_client_replaced_before_activation_is_refused(monkeypatch, fake, attached):
    attached.starts[CLIENT_PID] = [CLIENT_START, "999"]

    parent, result = _activation(monkeypatch)

    assert result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == zellij.CLIENT_GONE
    assert parent.calls == []


def test_client_replaced_during_activation_is_not_success(monkeypatch, fake, attached):
    attached.starts[CLIENT_PID] = [CLIENT_START, CLIENT_START, "999"]

    parent, result = _activation(monkeypatch)

    assert result.activation.attempted
    assert not result.activation.succeeded
    assert result.activation.detail == zellij.CLIENT_GONE_DURING
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


@pytest.mark.parametrize(
    "target", ["300", "300:", ":7", "1:7", "-3:7", "300:7:8", "300:x", None, 300]
)
def test_raise_window_rejects_malformed_client_target(monkeypatch, target):
    monkeypatch.setattr(
        DETECT_PARENT, lambda pid: pytest.fail("no parent lookup for bad target")
    )

    assert not ZellijAPI().raise_window(target, dict(ZELLIJ_ENV))


@pytest.mark.parametrize(
    ("socket_path", "captured", "expected"),
    [
        ("/s/contract_version_1/session", None, "/s"),
        ("/s/contract_version_2/session", "/c", "/s"),
        ("/s/other/session", "/c", "/c"),
        ("relative/contract_version_1/session", "/c", "/c"),
        ("/s/other/session", None, None),
        ("/s/other/session", "relative", None),
    ],
)
def test_socket_dir_is_derived_then_captured_then_default(
    monkeypatch, fake, host, socket_path, captured, expected
):
    host.server = _info(50, ("zellij", "--server", socket_path))
    env = dict(PANE_ENV)
    if captured:
        env["ZELLIJ_SOCKET_DIR"] = captured
    fake.clients = [ON_OTHER, ON_OTHER, ON_TARGET]
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    ZellijAPI().focus_result(101, env)

    assert "focus-pane-id" in fake.actions()
    for seen in fake.envs:
        if expected is None:
            assert seen is None
        else:
            assert seen["ZELLIJ_SOCKET_DIR"] == expected


def test_switch_tab_alone_uses_captured_socket_dir(fake):
    fake.clients = [ON_OTHER, ON_TARGET]

    assert ZellijAPI().switch_tab("3", {**PANE_ENV, "ZELLIJ_SOCKET_DIR": "/c"})
    assert [env["ZELLIJ_SOCKET_DIR"] for env in fake.envs] == ["/c"] * 3


def test_socket_dir_env_keeps_the_monitor_environment(monkeypatch, fake):
    monkeypatch.setenv("FLEET_MARKER", "kept")
    fake.clients = [ON_OTHER, ON_TARGET]

    ZellijAPI().switch_tab("3", {**PANE_ENV, "ZELLIJ_SOCKET_DIR": "/c"})

    assert fake.envs[0]["FLEET_MARKER"] == "kept"


@pytest.mark.parametrize(
    ("env", "inherited", "expected"),
    [
        ({"ZELLIJ_SOCKET_DIR": "/custom"}, None, "in socket dir /custom"),
        (None, "/inherited", "in socket dir /inherited"),
        (None, None, "in the default socket dir"),
    ],
)
def test_no_active_session_names_the_socket_dir(monkeypatch, env, inherited, expected):
    if inherited:
        monkeypatch.setenv("ZELLIJ_SOCKET_DIR", inherited)
    else:
        monkeypatch.delenv("ZELLIJ_SOCKET_DIR", raising=False)
    monkeypatch.setattr(
        zellij.subprocess,
        "run",
        _completed(1, stderr="There is no active session!\n"),
    )

    with pytest.raises(RuntimeError, match=expected):
        zellij._run(["zellij", "action", "list-clients"], env)


def test_no_active_session_is_selection_detail(monkeypatch):
    monkeypatch.setattr(
        zellij.subprocess, "run", _completed(1, stderr="There is no active session!")
    )

    result = ZellijAPI().focus_result(101, {**PANE_ENV, "ZELLIJ_SOCKET_DIR": "/c"})

    assert result.selection.attempted
    assert result.selection.detail == (
        "zellij reports no active session in socket dir /c"
    )


def test_run_passes_socket_dir_env(monkeypatch):
    seen = {}

    def record(argv, **kwargs):
        seen.update(kwargs)
        return _completed()(argv, **kwargs)

    monkeypatch.setattr(zellij.subprocess, "run", record)

    zellij._run(["zellij"], {"ZELLIJ_SOCKET_DIR": "/c"})

    assert seen["env"] == {"ZELLIJ_SOCKET_DIR": "/c"}


def test_capture_env_adds_absolute_socket_dir(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "fleet")
    monkeypatch.setenv("ZELLIJ_SOCKET_DIR", "/run/user/1000/custom")

    assert ZellijAPI.capture_env()["ZELLIJ_SOCKET_DIR"] == "/run/user/1000/custom"


@pytest.mark.parametrize("value", ["", "relative/dir", "./x", "/" + "d" * 1024])
def test_capture_env_omits_unusable_socket_dir(monkeypatch, value):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SOCKET_DIR", value)

    assert "ZELLIJ_SOCKET_DIR" not in ZellijAPI.capture_env()


def _walk(monkeypatch, *processes):
    table = {process.pid: process for process in processes}
    visited = []
    monkeypatch.setattr(zellij.sys, "platform", "linux")
    monkeypatch.setattr(
        zellij.discovery,
        "get_process_info",
        lambda pid: visited.append(pid) or table.get(pid),
    )
    return visited


def test_find_server_walks_to_the_server_argv(monkeypatch):
    server = _info(50, ("/usr/bin/zellij", "--server", SOCKET_PATH), ppid=1)
    _walk(
        monkeypatch,
        _info(101, ("claude",), ppid=90, name="claude"),
        _info(90, ("sh",), ppid=50, name="sh"),
        server,
    )

    assert FIND_SERVER(101) == server


def test_find_server_skips_zellij_processes_that_are_not_servers(monkeypatch):
    _walk(
        monkeypatch,
        _info(101, ("sh",), ppid=90, name="sh"),
        _info(90, ("zellij", "attach", "--server"), ppid=1),
    )

    assert FIND_SERVER(101) is None


def test_find_server_is_cycle_safe_and_bounded(monkeypatch):
    visited = _walk(
        monkeypatch,
        _info(101, ("sh",), ppid=90, name="sh"),
        _info(90, ("sh",), ppid=101, name="sh"),
    )

    assert FIND_SERVER(101) is None
    assert visited == [101, 90]

    chain = [_info(pid, ("sh",), ppid=pid + 1, name="sh") for pid in range(2, 400)]
    visited = _walk(monkeypatch, *chain)

    assert FIND_SERVER(2) is None
    assert len(visited) == zellij.MAX_ANCESTORS


def test_find_server_survives_lookup_errors(monkeypatch):
    monkeypatch.setattr(zellij.sys, "platform", "linux")

    def broken(pid):
        raise OSError("gone")

    monkeypatch.setattr(zellij.discovery, "get_process_info", broken)

    assert FIND_SERVER(101) is None


@pytest.mark.parametrize("pid", [0, 1, -5, True, "101", None])
def test_find_server_rejects_invalid_pids(monkeypatch, pid):
    _walk(monkeypatch)

    assert FIND_SERVER(pid) is None


def test_find_server_is_linux_only(monkeypatch):
    monkeypatch.setattr(zellij.sys, "platform", "darwin")

    assert FIND_SERVER(101) is None


@pytest.mark.parametrize(
    "argv",
    [
        ("web",),
        ("--config-dir", "/c", "web", "--start"),
        ("w", "session"),
        ("watch", "session"),
        ("pipe", "--name", "x"),
        ("subscribe", "--pane-id", "terminal_1"),
        ("run", "--", "sh"),
        ("r", "--", "sh"),
        ("edit", "file"),
        ("e", "file"),
        ("plugin", "--", "zellij:strider"),
        ("p", "zellij:strider"),
        ("--unknown-flag", "attach"),
        ("-s",),
    ],
)
def test_single_non_interactive_peer_is_refused(monkeypatch, fake, host, argv):
    host.client(CLIENT_PID, *argv)

    parent, result = _activation(monkeypatch)

    assert not result.activation.attempted
    assert "cannot tell which window shows the pane" in result.activation.detail
    assert parent.calls == []


def test_single_web_server_peer_names_the_subcommand(monkeypatch, fake, host):
    host.client(CLIENT_PID, "web")

    parent, result = _activation(monkeypatch)

    assert result.activation.detail == (
        "a zellij `web` process is connected to the session; "
        "cannot tell which window shows the pane"
    )
    assert parent.calls == []


def test_watch_alias_is_refused_as_watcher(monkeypatch, fake, attached):
    attached.client(400, "w", "session")

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.WATCHER)


def test_action_alias_is_transient(monkeypatch, fake, attached):
    attached.client(400, "ac", "list-clients")

    parent, result = _activation(monkeypatch)

    assert result.activation.succeeded


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("attach", "watch"),
        ("a", "action"),
        ("-s", "watch"),
        ("--session", "action"),
        ("--session=watch",),
        ("-swatch",),
        ("--config-dir", "/c", "-d", "-l", "web", "--session", "w"),
        ("-n", "/layouts/run.kdl"),
        ("attach", "--create", "web"),
    ],
)
def test_interactive_client_shapes_are_accepted(monkeypatch, fake, host, argv):
    if argv:
        host.client(CLIENT_PID, *argv)
    else:
        host.client()
        host.processes[CLIENT_PID] = _info(
            CLIENT_PID, ("/usr/bin/zellij",), start=CLIENT_START
        )

    parent, result = _activation(monkeypatch)

    assert result.activation.succeeded
    assert parent.calls == [("target", CLIENT_PID), ("raise", "window")]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("zellij",), None),
        (("zellij", "-s", "watch", "attach"), "attach"),
        (("zellij", "--max-panes", "3", "action", "x"), "action"),
        (("zellij", "--data-dir=/d", "web"), "web"),
        (("zellij", "--bogus=1"), zellij.UNKNOWN_SHAPE),
        (("zellij", "-x"), zellij.UNKNOWN_SHAPE),
        (("zellij", "--config"), zellij.UNKNOWN_SHAPE),
    ],
)
def test_subcommand_skips_global_options(argv, expected):
    assert zellij._subcommand(argv) == expected


def test_renamed_session_is_unavailable(monkeypatch, fake, attached):
    attached.server = _info(
        50, ("zellij", "--server", f"{SOCKET_DIR}/contract_version_1/old")
    )

    parent, result = _activation(monkeypatch)

    _unavailable(result, zellij.RENAMED)
    assert attached.peer_calls == []


class RequestedParent(WindowParent):
    def raise_window(self, tab_id, env):
        self._mark_raise_requested()
        raise RuntimeError("raise sent, not confirmed")


@pytest.mark.parametrize(
    ("parent", "requested"),
    [(WindowParent(), True), (RequestedParent(), True), (WindowParent(False), False)],
    ids=["confirmed", "unconfirmed", "not-activated"],
)
def test_raise_request_is_marked_when_parent_activated(
    monkeypatch, fake, attached, parent, requested
):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)
    api = ZellijAPI()

    api.focus_result(101, dict(ZELLIJ_ENV))

    assert api.raise_requested is requested


def test_unreadable_peer_process_refuses_activation(attached):
    attached.owners[2999] = frozenset({999})

    with pytest.raises(LookupError) as raised:
        zellij._attached_client(attached.server)

    assert str(raised.value) == zellij.MISMATCH


def test_refused_peer_detail_collapses_whitespace():
    detail = zellij._refused_peer("we\nb  x")

    assert "\n" not in detail
    assert "`we b x`" in detail
