"""GNOME Terminal API: exact owner window activation through xdotool on X11.

There is no public tab API, so selection is unsupported. Activation targets
the single window-manager-managed X11 window owned by the session's
gnome-terminal-server ancestor, minimized or on another desktop included, and
is reported unavailable whenever that window is not unique.
"""

import os
import sys
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis import _x11
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

SERVER_NAME = "gnome-terminal-server"
_COMM_LIMIT = 15
_MAX_STEPS = 64
_WALK_DEADLINE = 3.0


def _is_server(process) -> bool:
    names = [process.executable, process.argv[0] if process.argv else ""]
    if any(os.path.basename(value or "") == SERVER_NAME for value in names):
        return True
    return process.name in (SERVER_NAME, SERVER_NAME[:_COMM_LIMIT])


def _find_server_pid(pid: int, deadline: float) -> int:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise LookupError("invalid agent process id")
    visited = set()
    current = pid
    for _ in range(_MAX_STEPS):
        if time.monotonic() > deadline:
            raise LookupError("process ancestry walk timed out")
        if current <= 1 or current in visited:
            break
        visited.add(current)
        process = discovery.get_process_info(current)
        if process is None:
            break
        if _is_server(process):
            return current
        if process.ppid is None:
            break
        current = process.ppid
    raise LookupError(f"no {SERVER_NAME} ancestor found")


class GnomeAPI(TerminalAPI):
    name = "gnome"
    selection_supported = False

    @staticmethod
    def detect() -> bool:
        return bool(
            os.environ.get("GNOME_TERMINAL_SERVICE")
            or os.environ.get("TERM_PROGRAM") == "gnome-terminal"
        )

    @staticmethod
    def capture_env() -> dict:
        return {
            "VTE_VERSION": os.environ.get("VTE_VERSION", ""),
            "GNOME_TERMINAL_SERVICE": os.environ.get("GNOME_TERMINAL_SERVICE", ""),
            "GNOME_TERMINAL_SCREEN": os.environ.get("GNOME_TERMINAL_SCREEN", ""),
        }

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return None

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        if sys.platform != "linux":
            raise LookupError("GNOME Terminal activation is Linux only")
        if not os.environ.get("DISPLAY"):
            raise LookupError("xdotool needs an X11 display")
        deadline = time.monotonic() + _WALK_DEADLINE
        server_pid = _find_server_pid(pid, deadline)
        try:
            return _x11.managed_window(server_pid, SERVER_NAME, deadline)
        except RuntimeError as error:
            raise LookupError(str(error)) from None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        return _x11.activate(tab_id, self._mark_raise_requested)
