"""Kitty terminal API through opt-in remote control.

Selection needs kitty started with allow_remote_control (socket-only is
recommended) and listen_on. Fleet never edits kitty.conf. Only unix socket
addresses are used; tcp and fd addresses are rejected. Selection also needs
the captured KITTY_PID: the session and the listed window's child process must
descend from it, so a socket inherited from an outer kitty or kitty variables
leaked into another terminal never select a same-numbered window.

Window activation needs KDE Plasma: KWin activates the single normal window
owned by the captured KITTY_PID, and only kitty's own is_focused readback for
that OS window confirms it. KWin cannot tell two OS windows of one kitty
process apart, so such processes are never activated.
"""

import json
import re
import shutil
import subprocess
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis._env import bounded_env, is_decimal_id
from claude_fleet_monitor.terminal_apis._kwin import (
    activate_owned_window,
    kwin_available,
)
from claude_fleet_monitor.terminal_apis._qdbus import KWinScriptError, resolve_qdbus
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

ENV_KEYS = ("KITTY_WINDOW_ID", "KITTY_LISTEN_ON", "KITTY_PID")
TIMEOUT = 5
ACTIVATION_SETTLE_SECONDS = 1.0
ACTIVATION_POLL_SECONDS = 0.05
_MAX_ANCESTORS = 64
_ACTIVATION_TARGET = re.compile(r"^(\d{1,12}):(\d{1,12})$")
KITTY_PID_MISSING = (
    "kitty process id was not captured; restart the agent session to enable"
    " kitty focus"
)
NOT_AN_ANCESTOR = (
    "captured kitty process is not an ancestor of the session (kitty variables"
    " may have leaked from another terminal)"
)
_STDERR_LIMIT = 80
REMOTE_CONTROL_UNAVAILABLE = (
    "kitty remote control unavailable: needs allow_remote_control and a unix:"
    " listen_on socket"
)
_SOCKET_FAILURE = (
    "remote control socket refused or missing (kitty closed or remote control off)"
)
# Matched against the start of kitty's message only, since connect errors echo
# the socket address and that path may contain any of these words.
_KNOWN_ERRORS = (
    ("failed to connect to ", _SOCKET_FAILURE),
    ("remote control is disabled", "remote control is disabled (allow_remote_control)"),
    (
        "remote control is allowed over a socket only",
        "remote control is allowed over a socket only",
    ),
    ("the user rejected this password", "remote control password was refused"),
    (
        "remote control disallowed by window specific password",
        "remote control password was refused",
    ),
    ("the user rejected this request", "remote control request was rejected"),
    ("no matching windows", "target window no longer exists"),
)


def is_listen_address(value) -> bool:
    if not isinstance(value, str) or not value.startswith("unix:"):
        return False
    target = value[len("unix:"):]
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return False
    if target.startswith("/"):
        return True
    return target.startswith("@") and len(target) > 1


def _run(argv: list[str]) -> subprocess.CompletedProcess | None:
    # Nonzero exits are returned so callers can report kitty's own error.
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _remote_command() -> list[str]:
    if shutil.which("kitten"):
        return ["kitten", "@"]
    if shutil.which("kitty"):
        return ["kitty", "@"]
    raise RuntimeError("kitty remote control tool not found (kitten or kitty)")


def _first_line(text) -> str:
    for line in str(text or "").splitlines():
        line = "".join(
            character for character in line if character.isprintable()
        ).strip()
        if line:
            return line[:_STDERR_LIMIT]
    return ""


def _failure(action: str, result: subprocess.CompletedProcess | None) -> str:
    if result is None:
        return f"kitty {action} did not complete within {TIMEOUT}s"
    message = _first_line(result.stderr) or _first_line(result.stdout)
    lowered = message.lower()
    if lowered.startswith("error:"):
        lowered = lowered[len("error:"):].lstrip()
    for prefix, label in _KNOWN_ERRORS:
        if lowered.startswith(prefix):
            return f"kitty {action}: {label}"
    detail = f"kitty {action} exited {result.returncode}"
    return f"{detail}: {message}" if message else detail


def _address(terminal_env) -> str:
    if not isinstance(terminal_env, dict) or not terminal_env.get("KITTY_LISTEN_ON"):
        raise LookupError(REMOTE_CONTROL_UNAVAILABLE)
    address = terminal_env["KITTY_LISTEN_ON"]
    if not is_listen_address(address):
        raise LookupError("kitty listen_on address rejected (only unix sockets are used)")
    return address


def _is_kitty_ancestor(pid, kitty_pid: int) -> bool:
    """Whether kitty_pid is a process named kitty above pid.

    Guards against KITTY_* variables leaked into another terminal.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    visited = set()
    current = pid
    for _ in range(_MAX_ANCESTORS):
        if current <= 1 or current in visited:
            return False
        visited.add(current)
        try:
            process = discovery.get_process_info(current)
        except Exception:
            return False
        if process is None:
            return False
        if current == kitty_pid:
            return current != pid and process.name == "kitty"
        if process.ppid is None:
            return False
        current = process.ppid
    return False


def _list(command: list[str], action: str):
    listed = _run([*command, "ls"])
    if listed is None or listed.returncode != 0:
        raise RuntimeError(_failure(action, listed))
    try:
        listing = json.loads(listed.stdout)
    except ValueError:
        raise RuntimeError("kitty ls readback returned malformed JSON") from None
    if not isinstance(listing, list):
        raise RuntimeError("kitty ls readback returned malformed JSON")
    return listing


def _single_os_window(listing, window_id: int) -> dict:
    """Return the only OS window, which must contain window_id."""
    if len(listing) != 1:
        raise RuntimeError(
            f"kitty process has {len(listing)} OS windows and KWin cannot tell"
            " them apart; activation needs one OS window per kitty process"
        )
    try:
        found = _locate(listing, window_id)
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("kitty ls readback returned malformed JSON") from None
    if found is None:
        raise RuntimeError("kitty ls readback: target window no longer exists")
    os_window = listing[0]
    if not isinstance(os_window, dict):
        raise RuntimeError("kitty ls readback returned malformed JSON")
    return os_window


def _kitty_pid(terminal_env) -> int:
    value = terminal_env.get("KITTY_PID") if isinstance(terminal_env, dict) else None
    if not is_decimal_id(value):
        raise LookupError(KITTY_PID_MISSING)
    return int(value)


def _require_owned(listing, window_id: int, kitty_pid: int) -> None:
    """Refuse a socket served by another kitty, such as an inherited outer one."""
    try:
        found = _locate(listing, window_id)
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("kitty ls readback returned malformed JSON") from None
    if found is None:
        raise RuntimeError("kitty ls readback: target window no longer exists")
    child = found[1].get("pid")
    if not (
        type(child) is int and child > 1 and _is_kitty_ancestor(child, kitty_pid)
    ):
        raise RuntimeError(
            "kitty remote control socket does not belong to the captured kitty"
            " process (KITTY_LISTEN_ON may be inherited from an outer kitty)"
        )


def _locate(listing, window_id: int):
    if not isinstance(listing, list):
        raise ValueError("listing is not a list")
    for os_window in listing:
        for tab in os_window["tabs"]:
            for window in tab["windows"]:
                if type(window["id"]) is int and window["id"] == window_id:
                    return tab, window
    return None


class KittyAPI(TerminalAPI):
    name = "kitty"
    # A multiplexer client env carries no KITTY_LISTEN_ON or KITTY_PID.
    parent_activation_supported = False

    @staticmethod
    def detect() -> bool:
        return is_decimal_id(bounded_env(("KITTY_WINDOW_ID",)).get("KITTY_WINDOW_ID"))

    @staticmethod
    def capture_env() -> dict:
        captured = bounded_env(ENV_KEYS)
        if not is_decimal_id(captured.get("KITTY_WINDOW_ID")):
            captured.pop("KITTY_WINDOW_ID", None)
        if not is_listen_address(captured.get("KITTY_LISTEN_ON")):
            captured.pop("KITTY_LISTEN_ON", None)
        if not is_decimal_id(captured.get("KITTY_PID")):
            captured.pop("KITTY_PID", None)
        return captured

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        """Return the window only if the socket and session belong to KITTY_PID."""
        if not isinstance(terminal_env, dict):
            return None
        window_id = terminal_env.get("KITTY_WINDOW_ID")
        if not is_decimal_id(window_id):
            return None
        address = _address(terminal_env)
        kitty_pid = _kitty_pid(terminal_env)
        command = [*_remote_command(), "--to", address]
        try:
            _require_owned(_list(command, "ls"), int(window_id), kitty_pid)
        except RuntimeError as error:
            raise LookupError(str(error)) from None
        if not _is_kitty_ancestor(pid, kitty_pid):
            raise LookupError(NOT_AN_ANCESTOR)
        return window_id

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        if not is_decimal_id(tab_id):
            return False
        address = _address(terminal_env)
        kitty_pid = _kitty_pid(terminal_env)
        window_id = int(tab_id)
        command = [*_remote_command(), "--to", address]
        _require_owned(_list(command, "ls"), window_id, kitty_pid)
        selected = _run([*command, "focus-window", "--match", f"id:{window_id}"])
        if selected is None or selected.returncode != 0:
            raise RuntimeError(_failure("focus-window", selected))
        listed = _run([*command, "ls"])
        if listed is None or listed.returncode != 0:
            raise RuntimeError(_failure("ls readback", listed))
        try:
            found = _locate(json.loads(listed.stdout), window_id)
        except (ValueError, TypeError, KeyError):
            raise RuntimeError("kitty ls readback returned malformed JSON") from None
        if found is None:
            raise RuntimeError("kitty ls readback: target window no longer exists")
        tab, window = found
        if tab.get("is_active") is True and window.get("is_active") is True:
            return True
        raise RuntimeError(
            "kitty ls readback: target window is not active in the active tab"
        )

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        """Check every activation precondition before any KWin call."""
        if not isinstance(terminal_env, dict):
            return None
        window_id = terminal_env.get("KITTY_WINDOW_ID")
        if not is_decimal_id(window_id):
            raise LookupError("kitty window id was not captured")
        address = _address(terminal_env)
        kitty_pid = _kitty_pid(terminal_env)
        if not _is_kitty_ancestor(pid, kitty_pid):
            raise LookupError(NOT_AN_ANCESTOR)
        executable = resolve_qdbus()
        if not executable:
            raise LookupError(
                "kitty window activation needs KDE Plasma KWin; qdbus not found"
            )
        if not kwin_available(executable):
            raise LookupError(
                "kitty window activation needs KDE Plasma KWin; KWin is not"
                " running on the session bus"
            )
        command = [*_remote_command(), "--to", address]
        try:
            listing = _list(command, "ls")
            _single_os_window(listing, int(window_id))
            _require_owned(listing, int(window_id), int(kitty_pid))
        except RuntimeError as error:
            raise LookupError(str(error)) from None
        return f"{int(kitty_pid)}:{int(window_id)}"

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        match = _ACTIVATION_TARGET.fullmatch(tab_id) if isinstance(tab_id, str) else None
        if match is None:
            return False
        kitty_pid, window_id = int(match.group(1)), int(match.group(2))
        address = _address(terminal_env)
        executable = resolve_qdbus()
        if not executable:
            raise RuntimeError("qdbus is not available")
        command = [*_remote_command(), "--to", address]
        listing = _list(command, "ls")
        _single_os_window(listing, window_id)
        _require_owned(listing, window_id, kitty_pid)
        try:
            confirmed = activate_owned_window(
                executable,
                kitty_pid,
                plugin_prefix="claude-fleet-kitty",
                report=True,
            )
        except KWinScriptError as error:
            raise RuntimeError(str(error)) from None
        self._mark_raise_requested()
        if not confirmed:
            raise RuntimeError(
                f"KWin did not confirm a single normal window owned by kitty"
                f" process {kitty_pid}"
            )
        deadline = time.monotonic() + ACTIVATION_SETTLE_SECONDS
        while True:
            os_window = _single_os_window(_list(command, "ls readback"), window_id)
            if os_window.get("is_focused") is True:
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(ACTIVATION_POLL_SECONDS)
        raise RuntimeError(
            f"kitty did not report its OS window focused within"
            f" {ACTIVATION_SETTLE_SECONDS:g}s (KWin focus stealing prevention"
            " may have refused it)"
        )
