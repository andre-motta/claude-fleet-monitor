"""Windows Terminal API. Tab switching not supported; window raise only."""

import os

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class WindowsTerminalAPI(TerminalAPI):
    name = "windows_terminal"

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("WT_SESSION"))

    @staticmethod
    def capture_env() -> dict:
        return {"WT_SESSION": os.environ.get("WT_SESSION", "")}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return str(pid)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            import pywinctl
        except ImportError:
            return False
        wins = pywinctl.getWindowsWithTitle("Windows Terminal")
        if wins:
            wins[0].activate()
            return True
        return False
