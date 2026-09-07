"""Ghostty terminal API via GTK DBus interface."""

import os
import subprocess
import sys

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

# ydotool evdev keycodes for number keys 1-9
_YDOTOOL_NUM_KEYS = {
    1: "2", 2: "3", 3: "4", 4: "5", 5: "6",
    6: "7", 7: "8", 8: "9", 9: "10",
}


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
        if sys.platform == "linux" and self._try_kwin_raise():
            return True
        return self._try_xdotool_raise()

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
    def _try_kwin_raise() -> bool:
        import tempfile
        script = """
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    if (windows[i].resourceClass === 'com.mitchellh.ghostty') {
        workspace.activeWindow = windows[i];
        break;
    }
}
"""
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(script)
            f.flush()
            try:
                r = subprocess.run(
                    ["qdbus", "org.kde.KWin", "/Scripting",
                     "org.kde.kwin.Scripting.loadScript", f.name],
                    capture_output=True, text=True, timeout=5
                )
                sid = r.stdout.strip()
                if sid.isdigit():
                    subprocess.run(
                        ["qdbus", "org.kde.KWin", f"/Scripting/Script{sid}",
                         "org.kde.kwin.Script.run"],
                        capture_output=True, timeout=5
                    )
                    return False
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            finally:
                os.unlink(f.name)
        return False

    @staticmethod
    def _try_xdotool_raise() -> bool:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--class", "com.mitchellh.ghostty"],
                capture_output=True, text=True, timeout=5
            )
            wid = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
            if wid:
                activated = subprocess.run(
                    ["xdotool", "windowactivate", wid],
                    capture_output=True, timeout=5
                )
                return activated.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False
