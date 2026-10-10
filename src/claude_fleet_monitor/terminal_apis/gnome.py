"""GNOME Terminal API: exact owner window activation through xdotool on X11.

There is no public tab API, so selection is unsupported. Activation targets
the single X11 window owned by the session's gnome-terminal-server ancestor
and is reported unavailable whenever that window is not unique.
"""

import os
import subprocess
import sys
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis._env import is_decimal_id
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

SERVER_NAME = "gnome-terminal-server"
_COMM_LIMIT = 15
_MAX_STEPS = 64
_WALK_DEADLINE = 3.0
_XDOTOOL_TIMEOUT = 2.0


def _is_server(process) -> bool:
    names = [process.executable, process.argv[0] if process.argv else ""]
    if any(os.path.basename(value or "") == SERVER_NAME for value in names):
        return True
    return process.name in (SERVER_NAME, SERVER_NAME[:_COMM_LIMIT])


def _xdotool(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["xdotool", *args], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise RuntimeError("xdotool is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xdotool {args[0]} timed out") from None
    except OSError as error:
        raise RuntimeError(f"xdotool {args[0]} failed: {error.strerror}") from None


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
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LookupError("process ancestry walk timed out")
        try:
            result = _xdotool(
                ["search", "--pid", str(server_pid)],
                min(remaining, _XDOTOOL_TIMEOUT),
            )
        except RuntimeError as error:
            raise LookupError(str(error)) from None
        if result.returncode not in (0, 1):
            raise LookupError(f"xdotool search exited {result.returncode}")
        windows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not windows:
            raise LookupError(f"{SERVER_NAME} owns no X11 window")
        if len(windows) > 1:
            raise LookupError(
                f"{SERVER_NAME} owns {len(windows)} windows; exact window unknown"
            )
        if not is_decimal_id(windows[0]):
            raise LookupError("xdotool returned an invalid window id")
        return windows[0]

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        if not is_decimal_id(tab_id):
            raise RuntimeError("invalid X11 window id")
        activated = _xdotool(["windowactivate", "--sync", tab_id], _XDOTOOL_TIMEOUT)
        if activated.returncode != 0:
            raise RuntimeError(f"xdotool windowactivate exited {activated.returncode}")
        active = _xdotool(["getactivewindow"], _XDOTOOL_TIMEOUT)
        if active.returncode != 0:
            raise RuntimeError(f"xdotool getactivewindow exited {active.returncode}")
        if active.stdout.strip() != tab_id:
            raise RuntimeError("active window readback did not match the target")
        return True
