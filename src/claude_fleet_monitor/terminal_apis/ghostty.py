"""Ghostty terminal API.

Activation targets only the single visible window owned by the Ghostty process
hosting the session. KWin is asked first when available, but KWin cannot report
back, so success needs xdotool to read the target as the active X11 window.
Tab selection sends Alt+N and therefore runs only after confirmed activation.
"""

import json
import os
import subprocess
import sys
import time

from claude_fleet_monitor.terminal_apis._env import is_decimal_id
from claude_fleet_monitor.terminal_apis._qdbus import (
    KWinScriptError,
    resolve_qdbus,
    run_kwin_script,
)
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

_XDOTOOL_TIMEOUT = 2.0
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


def _xdotool(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["xdotool", *args],
            capture_output=True,
            text=True,
            timeout=_XDOTOOL_TIMEOUT,
        )
    except FileNotFoundError:
        raise RuntimeError("xdotool is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xdotool {args[0]} timed out") from None
    except OSError as error:
        raise RuntimeError(f"xdotool {args[0]} failed: {error.strerror}") from None


def _tab_pid(tab_id) -> int | None:
    if not isinstance(tab_id, str):
        return None
    pid, separator, _ = tab_id.partition(":")
    if not separator or not is_decimal_id(pid):
        return None
    return int(pid)


def _find_ghostty_pid() -> int | None:
    try:
        result = subprocess.run(
            ["pgrep", "-x", "ghostty"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split("\n")
        return int(pids[0]) if pids and pids[0] else None
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


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


def _find_ancestor_child(pid: int, ghostty_pid: int) -> int | None:
    """Walk up from pid to find which direct child of ghostty it descends from."""
    check = pid
    while check > 1:
        try:
            if sys.platform == "linux":
                stat = open(f"/proc/{check}/stat").read()
                ppid = int(stat.split(") ")[1].split()[1])
            else:
                ppid_str = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(check)],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                ppid = int(ppid_str) if ppid_str else 0
        except (OSError, ValueError, IndexError):
            break
        if ppid == ghostty_pid:
            return check
        if ppid <= 1:
            break
        check = ppid
    return None


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
        ghostty_pid = _find_ghostty_pid()
        if not ghostty_pid:
            return None

        children = _get_ghostty_children(ghostty_pid)
        if not children:
            return None

        ancestor = _find_ancestor_child(pid, ghostty_pid)
        if not ancestor or ancestor not in children:
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
        ghostty_pid = _find_ghostty_pid()
        if not ghostty_pid:
            raise RuntimeError("Ghostty process not found")
        if _find_ancestor_child(agent_pid, ghostty_pid) is None:
            raise RuntimeError("session is not inside the running Ghostty process")
        kwin_note = None
        if sys.platform == "linux":
            kwin_note = self._try_kwin_raise(ghostty_pid)
        try:
            return self._try_xdotool_raise(ghostty_pid)
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

    @staticmethod
    def _try_kwin_raise(ghostty_pid: int) -> str | None:
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
        return "activation requested but unconfirmed"

    @staticmethod
    def _try_xdotool_raise(ghostty_pid: int) -> bool:
        search = _xdotool(
            ["search", "--onlyvisible", "--pid", str(ghostty_pid)]
        )
        if search.returncode not in (0, 1):
            raise RuntimeError(f"xdotool search exited {search.returncode}")
        windows = [
            line.strip() for line in search.stdout.splitlines() if line.strip()
        ]
        if not windows:
            raise RuntimeError("Ghostty owns no visible X11 window")
        if len(windows) > 1:
            raise RuntimeError(
                f"Ghostty owns {len(windows)} visible windows;"
                " exact window unknown"
            )
        window = windows[0]
        if not is_decimal_id(window):
            raise RuntimeError("xdotool returned an invalid window id")
        activated = _xdotool(["windowactivate", "--sync", window])
        if activated.returncode != 0:
            raise RuntimeError(
                f"xdotool windowactivate exited {activated.returncode}"
            )
        active = _xdotool(["getactivewindow"])
        if active.returncode != 0:
            raise RuntimeError(
                f"xdotool getactivewindow exited {active.returncode}"
            )
        if active.stdout.strip() != window:
            raise RuntimeError("active window readback did not match the target")
        return True
