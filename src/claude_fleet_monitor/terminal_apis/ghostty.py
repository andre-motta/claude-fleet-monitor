"""Ghostty terminal API.

Activation targets only the single window-manager-managed window owned by the
Ghostty process that is an ancestor of the session, minimized or on another
desktop included. KWin is asked first when available, but KWin cannot report
back, so success needs xdotool to read the target as the active X11 window.
Tab selection sends Alt+N and therefore runs only after confirmed activation.
"""

import json
import os
import subprocess
import sys
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis import _x11
from claude_fleet_monitor.terminal_apis._env import is_decimal_id
from claude_fleet_monitor.terminal_apis._qdbus import (
    KWinScriptError,
    resolve_qdbus,
    run_kwin_script,
)
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

_PROCESS_NAME = "ghostty"
_MAX_STEPS = 64
_LOOKUP_DEADLINE = 3.0
_KWIN_ACTIVATE_SCRIPT = """
var owner = __OWNER__;
var matches = [];
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    if (windows[i].pid === owner) {
        matches.push(windows[i]);
    }
}
if (matches.length === 1) {
    matches[0].minimized = false;
    workspace.activeWindow = matches[0];
}
"""

# ydotool evdev keycodes for number keys 1-9
_YDOTOOL_NUM_KEYS = {
    1: "2", 2: "3", 3: "4", 4: "5", 5: "6",
    6: "7", 7: "8", 8: "9", 9: "10",
}


def _tab_pid(tab_id) -> int | None:
    if not isinstance(tab_id, str):
        return None
    pid, separator, _ = tab_id.partition(":")
    if not separator or not is_decimal_id(pid):
        return None
    return int(pid)


def _is_ghostty(process) -> bool:
    names = [
        process.name,
        process.executable,
        process.argv[0] if process.argv else "",
    ]
    return any(os.path.basename(value or "") == _PROCESS_NAME for value in names)


def _find_ghostty(pid: int, deadline: float) -> tuple[int, int]:
    """Return the Ghostty ancestor of pid and its direct child on that path."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise LookupError("invalid agent process id")
    visited = set()
    child = None
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
        if _is_ghostty(process):
            if child is None:
                break
            return current, child
        if process.ppid is None:
            break
        child = current
        current = process.ppid
    raise LookupError("no Ghostty ancestor found")


def _get_ghostty_children(ghostty_pid: int) -> list[int]:
    """Get direct child PIDs of ghostty, sorted by start time."""
    try:
        result = subprocess.run(
            ["ps", "--ppid", str(ghostty_pid), "-o", "pid,lstart",
             "--no-headers", "--sort=lstart"],
            capture_output=True, text=True, timeout=5
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    children = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        pid_str = line.strip().split()[0]
        try:
            children.append(int(pid_str))
        except ValueError:
            continue
    return children


class GhosttyAPI(TerminalAPI):
    name = "ghostty"
    activation_before_selection = True

    def prepare_selection_after_activation(self) -> None:
        time.sleep(0.15)

    @staticmethod
    def detect() -> bool:
        return os.environ.get("TERM_PROGRAM") == "ghostty"

    @staticmethod
    def capture_env() -> dict:
        return {
            "TERM_PROGRAM": os.environ.get("TERM_PROGRAM", ""),
            "GHOSTTY_BIN_DIR": os.environ.get("GHOSTTY_BIN_DIR", ""),
        }

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        try:
            ghostty_pid, ancestor = _find_ghostty(
                pid, time.monotonic() + _LOOKUP_DEADLINE
            )
        except LookupError:
            return None

        children = _get_ghostty_children(ghostty_pid)
        if ancestor not in children:
            return None

        tab_index = children.index(ancestor) + 1
        return f"{pid}:{tab_index}"

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        if ":" not in tab_id:
            return False
        try:
            tab_num = int(tab_id.split(":")[1])
        except (ValueError, IndexError):
            return False
        if tab_num < 1 or tab_num > 9:
            return False

        if self._try_ydotool_goto_tab(tab_num):
            return True
        if self._try_xdotool_goto_tab(tab_num):
            return True
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        agent_pid = _tab_pid(tab_id)
        if agent_pid is None:
            raise RuntimeError("invalid Ghostty tab target")
        try:
            ghostty_pid, _ = _find_ghostty(
                agent_pid, time.monotonic() + _LOOKUP_DEADLINE
            )
        except LookupError as error:
            raise RuntimeError(str(error)) from None
        kwin_note = None
        if sys.platform == "linux":
            kwin_note = self._try_kwin_raise(ghostty_pid)
        try:
            window = _x11.managed_window(
                ghostty_pid, "Ghostty", time.monotonic() + _LOOKUP_DEADLINE
            )
            return _x11.activate(window, self._mark_raise_requested)
        except RuntimeError as error:
            if kwin_note:
                raise RuntimeError(f"{error}; KWin: {kwin_note}") from None
            raise

    @staticmethod
    def _try_ydotool_goto_tab(tab_num: int) -> bool:
        keycode = _YDOTOOL_NUM_KEYS.get(tab_num)
        if not keycode:
            return False
        env = os.environ.copy()
        if not env.get("YDOTOOL_SOCKET"):
            for path in (f"/run/user/{os.getuid()}/.ydotool_socket",
                         "/tmp/.ydotool_socket"):
                if os.path.exists(path):
                    env["YDOTOOL_SOCKET"] = path
                    break
        try:
            result = subprocess.run(
                ["ydotool", "key", f"56:1", f"{keycode}:1", f"{keycode}:0", "56:0"],
                capture_output=True, timeout=5, env=env
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _try_xdotool_goto_tab(tab_num: int) -> bool:
        try:
            result = subprocess.run(
                ["xdotool", "key", f"alt+{tab_num}"],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _try_kwin_raise(self, ghostty_pid: int) -> str | None:
        """Ask KWin to activate the single window of ghostty_pid.

        Returns a note for the failure detail; never a success claim.
        """
        executable = resolve_qdbus()
        if not executable:
            return None
        script = _KWIN_ACTIVATE_SCRIPT.replace(
            "__OWNER__", json.dumps(ghostty_pid)
        )
        try:
            run_kwin_script(executable, script, "claude-fleet-ghostty")
        except KWinScriptError as error:
            return str(error)
        except OSError as error:
            return f"KWin script could not be written: {error.strerror or error}"
        self.raise_requested = True
        return "activation requested but unconfirmed"
