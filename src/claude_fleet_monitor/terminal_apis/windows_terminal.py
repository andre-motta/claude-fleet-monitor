"""Windows Terminal API.

Detection only. A window titled "Windows Terminal" can belong to another
session because titles follow the active tab, and all windows usually share
one WindowsTerminal.exe process, so the session's own window cannot be
identified without Win32 owner and top-level window enumeration that has not
been validated on a Windows host. Selection and activation stay unsupported.
"""

import os

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class WindowsTerminalAPI(TerminalAPI):
    name = "windows_terminal"
    selection_supported = False
    activation_supported = False

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("WT_SESSION"))

    @staticmethod
    def capture_env() -> dict:
        return {"WT_SESSION": os.environ.get("WT_SESSION", "")}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return None

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        return False
