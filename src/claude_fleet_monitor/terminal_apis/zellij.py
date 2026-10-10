"""Zellij terminal API.

Selection runs `zellij --session <S> action focus-pane-id terminal_<id>` and
is confirmed only when `action list-clients` shows a client that was not on
that pane before the action is on it afterwards, or when every attached client
already showed the pane. focus-pane-id moves only the client that most recently
sent input and exits 0 even with no client attached, so neither its exit status
nor an idle client already on the pane proves the selection.
The isolated validator passes on zellij 0.44.2 through 0.45.1; 0.44.0 and
older lack focus-pane-id and fail selection. Unrecognized output is treated as
unsupported rather than gated by version.

Every CLI call targets the session's socket directory: derived from the
daemonized server's `--server <dir>/contract_version_N/<session>` argv found in
the agent's ancestry, else the captured ZELLIJ_SOCKET_DIR, else zellij's own
default. The server's ancestry never reaches a GUI, so on Linux the emulator is
found from the one attached client process, identified by its socket peer.
Several clients, any connected zellij process other than `attach`, a bare
client or a transient `action`, or any mismatch with list-clients is refused.
"""

import dataclasses
import os
import subprocess
import sys
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.models import FocusResult
from claude_fleet_monitor.terminal_apis import _unix_peers, tmux
from claude_fleet_monitor.terminal_apis._env import bounded_env, is_decimal_id
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.parent import (
    activate_parent,
    parent_activation_supported,
    unsupported_detail,
)

SOCKET_DIR_KEY = "ZELLIJ_SOCKET_DIR"
ENV_KEYS = ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID", SOCKET_DIR_KEY)
VALIDATED_VERSION = "0.45.1"
MAX_SESSION_BYTES = 256
COMMAND_TIMEOUT = 5
READBACK_ATTEMPTS = 5
READBACK_INTERVAL = 0.1
LIST_CLIENTS_COLUMNS = ("CLIENT_ID", "ZELLIJ_PANE_ID")
ALREADY_FOCUSED = "pane already focused"
SERVER_FLAG = "--server"
CONTRACT_PREFIX = "contract_version_"
MAX_ANCESTORS = 128
NO_SESSION = "no active session"
VALUE_OPTIONS = frozenset({
    "-s", "--session", "-l", "--layout", "--layout-string", "-n",
    "--new-session-with-layout", "-c", "--config", "--config-dir", "--data-dir",
    "--max-panes",
})
FLAG_OPTIONS = frozenset({"-d", "--debug"})
INTERACTIVE_COMMANDS = frozenset({None, "attach", "a"})
TRANSIENT_COMMANDS = frozenset({"action", "ac"})
WATCH_COMMANDS = frozenset({"watch", "w"})
UNKNOWN_SHAPE = object()
NOT_LINUX = "zellij client discovery is only implemented on Linux"
NO_SERVER = "no zellij server found in the agent process ancestry"
NO_SESSION_NAME = "zellij session name was not captured"
PEERS_UNREADABLE = "zellij client sockets could not be inspected"
SEVERAL_CLIENTS = (
    "several zellij clients attached; cannot tell which one shows the pane"
)
WATCHER = (
    "a zellij watch client is attached; cannot tell which window shows the pane"
)
MISMATCH = "zellij client processes do not match list-clients"
NO_TTY = "zellij client has no controlling terminal"
CLIENT_GONE = "zellij client exited before its window was activated"
CLIENT_GONE_DURING = "zellij client exited during window activation"
RENAMED = (
    "zellij session name does not match its server socket (renamed session?); "
    "cannot identify the client"
)
NO_PARENT = "no parent terminal emulator found for zellij"


def _no_session_detail(env: dict | None) -> str:
    socket_dir = (env if env is not None else os.environ).get(SOCKET_DIR_KEY)
    if socket_dir:
        return f"zellij reports no active session in socket dir {socket_dir}"
    return (
        "zellij reports no active session in the default socket dir; "
        "the session may use a custom ZELLIJ_SOCKET_DIR"
    )


def _run(
    argv: list[str], env: dict | None = None
) -> subprocess.CompletedProcess | None:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        if NO_SESSION in (result.stderr or "").lower():
            raise RuntimeError(_no_session_detail(env))
        return None
    return result


def _absolute_dir(value) -> str | None:
    if not isinstance(value, str) or "\0" in value or not os.path.isabs(value):
        return None
    return value


def _process(pid: int):
    try:
        return discovery.get_process_info(pid)
    except Exception:
        return None


def _is_server(process) -> bool:
    argv = process.argv
    return (
        len(argv) >= 3
        and argv[1] == SERVER_FLAG
        and "zellij" in {process.name, process.executable, os.path.basename(argv[0])}
    )


def _find_server(pid):
    """Walk bounded, cycle-safe ancestry to the daemonized zellij server."""
    if (
        sys.platform != "linux"
        or not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 1
    ):
        return None
    current, visited = pid, set()
    for _ in range(MAX_ANCESTORS):
        if current <= 1 or current in visited:
            return None
        visited.add(current)
        process = _process(current)
        if process is None:
            return None
        if _is_server(process):
            return process
        if process.ppid is None:
            return None
        current = process.ppid
    return None


def _socket_dir(server, terminal_env) -> str | None:
    if server is not None:
        socket_path = server.argv[2]
        parent = os.path.dirname(socket_path)
        if os.path.isabs(socket_path) and os.path.basename(parent).startswith(
            CONTRACT_PREFIX
        ):
            return os.path.dirname(parent)
    if isinstance(terminal_env, dict):
        return _absolute_dir(terminal_env.get(SOCKET_DIR_KEY))
    return None


def _cli_env(socket_dir: str | None) -> dict | None:
    if socket_dir is None:
        return None
    return {**os.environ, SOCKET_DIR_KEY: socket_dir}


def _subcommand(argv):
    """Return the zellij subcommand (None for none) or UNKNOWN_SHAPE.

    Global options and their values are skipped, so a session named like a
    subcommand is never mistaken for one.
    """
    arguments = iter(argv[1:])
    for argument in arguments:
        if argument in VALUE_OPTIONS:
            if next(arguments, None) is None:
                return UNKNOWN_SHAPE
        elif argument in FLAG_OPTIONS:
            continue
        elif argument.startswith("--") and "=" in argument:
            if argument.split("=", 1)[0] not in VALUE_OPTIONS:
                return UNKNOWN_SHAPE
        elif argument.startswith("-"):
            if len(argument) > 2 and argument[:2] in VALUE_OPTIONS:
                continue
            return UNKNOWN_SHAPE
        else:
            return argument
    return None


def _refused_peer(command) -> str:
    if command in WATCH_COMMANDS:
        return WATCHER
    shown = (
        "unrecognized"
        if command is UNKNOWN_SHAPE
        else "`" + " ".join(str(command).split())[:40] + "`"
    )
    return (
        f"a zellij {shown} process is connected to the session; "
        "cannot tell which window shows the pane"
    )[:160]


def _attached_client(server):
    """Return the one interactive client process connected to the server."""
    owners = _unix_peers.peer_owners(server.pid, server.argv[2], "zellij")
    if owners is None:
        raise LookupError(PEERS_UNREADABLE)
    if any(len(pids) != 1 for pids in owners.values()):
        raise LookupError(MISMATCH)
    candidates = []
    for pid in sorted({pid for pids in owners.values() for pid in pids}):
        process = _process(pid)
        if process is None:
            raise LookupError(MISMATCH)
        command = _subcommand(process.argv)
        if command in TRANSIENT_COMMANDS:
            continue
        if command not in INTERACTIVE_COMMANDS:
            raise LookupError(_refused_peer(command))
        candidates.append(process)
    if len(candidates) > 1:
        raise LookupError(SEVERAL_CLIENTS)
    if not candidates:
        raise LookupError(MISMATCH)
    client = candidates[0]
    if not _unix_peers.controlling_tty(client.pid):
        raise LookupError(NO_TTY)
    return client


def _client_target(tab_id) -> tuple[int, str] | None:
    if not isinstance(tab_id, str):
        return None
    pid, _, start = tab_id.partition(":")
    if not is_decimal_id(pid) or not is_decimal_id(start, 20) or int(pid) <= 1:
        return None
    return int(pid), start


def _same_process(pid: int, start: str) -> bool:
    process = _process(pid)
    return process is not None and process.start_token == start


def _safe_session(value) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or "\0" in value
        or len(value.encode("utf-8", "surrogatepass")) > MAX_SESSION_BYTES
    ):
        return None
    return value


def _target(tab_id, terminal_env) -> tuple[str, str] | None:
    if not isinstance(terminal_env, dict) or not is_decimal_id(tab_id):
        return None
    session = _safe_session(terminal_env.get("ZELLIJ_SESSION_NAME"))
    if session is None:
        return None
    return session, tab_id


def _client_panes(output: str) -> dict[str, str]:
    lines = output.splitlines()
    if not lines or tuple(lines[0].split()[:2]) != LIST_CLIENTS_COLUMNS:
        raise RuntimeError(
            "unrecognized zellij list-clients output "
            f"(validated with zellij {VALIDATED_VERSION})"
        )
    rows = (line.split() for line in lines[1:])
    return {parts[0]: parts[1] for parts in rows if len(parts) >= 2}


def _list_clients(
    command: list[str], failure: str, env: dict | None = None
) -> dict[str, str]:
    listed = _run([*command, "list-clients"], env)
    if listed is None:
        raise RuntimeError(failure)
    clients = _client_panes(listed.stdout)
    if not clients:
        raise RuntimeError("no attached zellij client")
    return clients


class ZellijAPI(TerminalAPI):
    name = "zellij"
    selection_supported = True

    def __init__(self):
        self._selection_detail = None
        self._context = None

    def _server(self, pid):
        if self._context is not None and self._context[0] == pid:
            return self._context[1]
        return _find_server(pid)

    def _cli_env(self, terminal_env) -> dict | None:
        server = self._context[1] if self._context is not None else None
        return _cli_env(_socket_dir(server, terminal_env))

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("ZELLIJ"))

    @staticmethod
    def capture_env() -> dict:
        captured = bounded_env(ENV_KEYS)
        env = {
            "ZELLIJ": captured.get("ZELLIJ", ""),
            "ZELLIJ_SESSION_NAME": captured.get("ZELLIJ_SESSION_NAME", ""),
        }
        if is_decimal_id(captured.get("ZELLIJ_PANE_ID")):
            env["ZELLIJ_PANE_ID"] = captured["ZELLIJ_PANE_ID"]
        socket_dir = _absolute_dir(captured.get(SOCKET_DIR_KEY))
        if socket_dir:
            env[SOCKET_DIR_KEY] = socket_dir
        return env

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if not isinstance(terminal_env, dict) or not terminal_env:
            return None
        if "ZELLIJ_PANE_ID" not in terminal_env:
            raise LookupError(
                "session recorded before zellij pane capture; restart the agent"
                " session to enable selection"
            )
        target = _target(terminal_env["ZELLIJ_PANE_ID"], terminal_env)
        return target[1] if target else None

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        if not isinstance(terminal_env, dict) or not (
            terminal_env.get("ZELLIJ") or terminal_env.get("ZELLIJ_SESSION_NAME")
        ):
            return None
        if sys.platform != "linux":
            raise LookupError(NOT_LINUX)
        server = self._server(pid)
        if server is None:
            raise LookupError(NO_SERVER)
        session = _safe_session(terminal_env.get("ZELLIJ_SESSION_NAME"))
        if session is None:
            raise LookupError(NO_SESSION_NAME)
        if os.path.basename(server.argv[2]) != session:
            raise LookupError(RENAMED)
        clients = _list_clients(
            ["zellij", "--session", session, "action"],
            "zellij list-clients failed: CLI missing, timed out, unknown session "
            "or unsupported version",
            _cli_env(_socket_dir(server, terminal_env)),
        )
        if len(clients) > 1:
            raise LookupError(SEVERAL_CLIENTS)
        client = _attached_client(server)
        return f"{client.pid}:{client.start_token}"

    def focus_result(self, pid: int, terminal_env: dict) -> FocusResult:
        self._selection_detail = None
        self._context = (pid, _find_server(pid))
        try:
            result = super().focus_result(pid, terminal_env)
        finally:
            self._context = None
        if result.selection.succeeded and self._selection_detail:
            selection = dataclasses.replace(
                result.selection, detail=self._selection_detail
            )
            return dataclasses.replace(result, selection=selection)
        return result

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        self._selection_detail = None
        target = _target(tab_id, terminal_env)
        if target is None:
            return False
        session, pane = target
        command = ["zellij", "--session", session, "action"]
        expected = f"terminal_{pane}"
        env = self._cli_env(terminal_env)
        before = _list_clients(
            command,
            "zellij list-clients snapshot failed: CLI missing, timed out, "
            "unknown session or unsupported version",
            env,
        )
        if all(shown == expected for shown in before.values()):
            self._selection_detail = ALREADY_FOCUSED
            return True
        if _run([*command, "focus-pane-id", expected], env) is None:
            raise RuntimeError(
                f"zellij could not focus pane {pane}: CLI missing, timed out, "
                "unknown pane or unsupported version"
            )
        for attempt in range(READBACK_ATTEMPTS):
            after = _list_clients(
                command, "zellij list-clients readback failed", env
            )
            if any(
                after.get(client) == expected and shown != expected
                for client, shown in before.items()
            ):
                return True
            if attempt + 1 < READBACK_ATTEMPTS:
                time.sleep(READBACK_INTERVAL)
        raise RuntimeError(f"no zellij client moved to pane {pane}")

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        target = _client_target(tab_id)
        if target is None:
            return False
        client_pid, start = target
        parent = tmux._detect_parent_terminal(client_pid)
        if not _same_process(client_pid, start):
            raise RuntimeError(CLIENT_GONE)
        if parent is None:
            raise RuntimeError(NO_PARENT)
        if not parent_activation_supported(parent):
            raise RuntimeError(unsupported_detail(parent))
        outcome = activate_parent(parent, client_pid)
        if outcome.activated:
            self._mark_raise_requested()
        if not _same_process(client_pid, start):
            raise RuntimeError(CLIENT_GONE_DURING)
        if not outcome:
            raise RuntimeError(outcome.detail)
        return True
