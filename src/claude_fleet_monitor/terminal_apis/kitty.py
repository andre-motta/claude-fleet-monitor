"""Kitty terminal API through opt-in remote control.

Selection needs kitty started with allow_remote_control (socket-only is
recommended) and listen_on. Fleet never edits kitty.conf. Only unix socket
addresses are used; tcp and fd addresses are rejected. Window activation is
not claimed because kitty offers no independent OS focus readback.
"""

import json
import shutil
import subprocess

from claude_fleet_monitor.terminal_apis._env import bounded_env, is_decimal_id
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

ENV_KEYS = ("KITTY_WINDOW_ID", "KITTY_LISTEN_ON")
TIMEOUT = 5
_STDERR_LIMIT = 80
REMOTE_CONTROL_UNAVAILABLE = (
    "kitty remote control unavailable (allow_remote_control/listen_on not configured)"
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
    if "remote control is disabled" in lowered:
        return f"kitty {action}: remote control is disabled (allow_remote_control)"
    if "allowed over a socket only" in lowered:
        return f"kitty {action}: remote control is allowed over a socket only"
    if "password" in lowered:
        return f"kitty {action}: remote control password was refused"
    if "failed to connect" in lowered:
        return (
            f"kitty {action}: remote control socket refused or missing"
            " (kitty closed or remote control off)"
        )
    if "no matching windows" in lowered:
        return f"kitty {action}: target window no longer exists"
    detail = f"kitty {action} exited {result.returncode}"
    return f"{detail}: {message}" if message else detail


def _address(terminal_env) -> str:
    if not isinstance(terminal_env, dict) or not terminal_env.get("KITTY_LISTEN_ON"):
        raise LookupError(REMOTE_CONTROL_UNAVAILABLE)
    address = terminal_env["KITTY_LISTEN_ON"]
    if not is_listen_address(address):
        raise LookupError("kitty listen_on address rejected (only unix sockets are used)")
    return address


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
    activation_supported = False

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
        return captured

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if not isinstance(terminal_env, dict):
            return None
        window_id = terminal_env.get("KITTY_WINDOW_ID")
        if not is_decimal_id(window_id):
            return None
        _address(terminal_env)
        return window_id

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        if not is_decimal_id(tab_id):
            return False
        address = _address(terminal_env)
        window_id = int(tab_id)
        command = [*_remote_command(), "--to", address]
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

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        return False
