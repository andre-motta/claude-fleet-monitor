"""Generic fallback terminal API. Window raise only, no tab switching."""

import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class GenericAPI(TerminalAPI):
    name = "generic"
    selection_supported = False

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
        try:
            pid = int(tab_id)
        except ValueError:
            return False
        if self._try_xdotool(pid):
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
                activated = subprocess.run(
                    ["xdotool", "windowactivate", wid],
                    capture_output=True, timeout=5
                )
                return activated.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False
