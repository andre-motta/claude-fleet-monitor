"""GNU screen terminal API.

Selection uses ``screen -S <STY> -X select <WINDOW>`` and is claimed only
when ``screen -S <STY> -Q number`` reads the window back. Both commands act on
the same single display, which on screen 5.0.1 was the most recently attached
one; other displays keep their window. With no attached display, select is a
silent no-op while ``-Q number`` still answers with the stale window, so an
empty ``-Q windows`` answer is treated as a failed selection. A screen session
owns no GUI window, so activation is not supported.
"""

import re
import subprocess

from claude_fleet_monitor.terminal_apis._env import bounded_env, is_decimal_id
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

ENV_KEYS = ("STY", "WINDOW")
COMMAND_TIMEOUT = 5
MAX_STY_BYTES = 256
_STY_PATTERN = re.compile(r"[0-9]+\.[^\s/\x00]+")


class ScreenFocusError(RuntimeError):
    """A failed screen step whose message is the user-facing detail."""


def _run(argv: list[str]) -> subprocess.CompletedProcess | None:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result


def _valid_sty(value) -> bool:
    return (
        isinstance(value, str)
        and len(value.encode("utf-8", "replace")) <= MAX_STY_BYTES
        and _STY_PATTERN.fullmatch(value) is not None
    )


def _window(value) -> str | None:
    if not is_decimal_id(value):
        return None
    return str(int(value))


def _session(terminal_env) -> str | None:
    if not isinstance(terminal_env, dict):
        return None
    sty = terminal_env.get("STY")
    return sty if _valid_sty(sty) else None


def _current_window(output: str) -> str | None:
    fields = output.split()
    if not fields:
        return None
    return _window(fields[0])


def _has_display(sty: str) -> bool:
    result = _run(["screen", "-S", sty, "-Q", "windows"])
    if result is None:
        raise ScreenFocusError("screen session could not be queried")
    return bool(result.stdout.strip())


class ScreenAPI(TerminalAPI):
    name = "screen"
    activation_supported = False

    @staticmethod
    def detect() -> bool:
        captured = bounded_env(ENV_KEYS)
        return _valid_sty(captured.get("STY")) and _window(
            captured.get("WINDOW")
        ) is not None

    @staticmethod
    def capture_env() -> dict:
        captured = bounded_env(ENV_KEYS)
        return {key: captured.get(key, "") for key in ENV_KEYS}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if _session(terminal_env) is None:
            return None
        return _window(terminal_env.get("WINDOW"))

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        sty = _session(terminal_env)
        window = _window(tab_id)
        if sty is None or window is None:
            raise ScreenFocusError("screen session or window is not valid")
        if not _has_display(sty):
            raise ScreenFocusError("no attached screen display")
        if _run(["screen", "-S", sty, "-X", "select", window]) is None:
            raise ScreenFocusError(f"screen could not select window {window}")
        readback = _run(["screen", "-S", sty, "-Q", "number"])
        if readback is None:
            raise ScreenFocusError("screen current window could not be read")
        current = _current_window(readback.stdout)
        if current != window:
            raise ScreenFocusError(
                f"screen shows window {current or 'unknown'}, not window {window}"
            )
        if not _has_display(sty):
            raise ScreenFocusError("no attached screen display")
        return True

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        return False
