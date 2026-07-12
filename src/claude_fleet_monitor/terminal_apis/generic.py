"""Generic fallback terminal API. Window raise only, no tab switching."""

import subprocess
import sys

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class GenericAPI(TerminalAPI):
    name = "generic"

    @staticmethod
    def detect() -> bool:
        return True

    @staticmethod
    def capture_env() -> dict:
        return {}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return str(pid)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        if self._try_pywinctl(tab_id):
            return True
        if self._try_xdotool(int(tab_id)):
            return True
        if sys.platform == "darwin" and self._try_osascript():
            return True
        return False

    @staticmethod
    def _try_pywinctl(title: str) -> bool:
        try:
            import pywinctl
            wins = pywinctl.getWindowsWithTitle(title)
            if wins:
                wins[0].activate()
                return True
        except (ImportError, Exception):
            pass
        return False

    @staticmethod
    def _try_xdotool(pid: int) -> bool:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(pid)],
                capture_output=True, text=True, timeout=5
            )
            wid = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
            if wid:
                subprocess.run(
                    ["xdotool", "windowactivate", wid],
                    capture_output=True, timeout=5
                )
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    @staticmethod
    def _try_osascript() -> bool:
        script = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set frontmost of frontApp to true
end tell
'''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
