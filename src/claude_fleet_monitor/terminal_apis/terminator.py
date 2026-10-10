"""Terminator detection-only API.

Terminator's D-Bus interface cannot select a terminal or raise a window, so
this backend records the session label and claims no focus (#47).
"""

from claude_fleet_monitor.terminal_apis._env import bounded_env
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

ENV_KEYS = ("TERMINATOR_UUID", "TERMINATOR_DBUS_NAME", "TERMINATOR_DBUS_PATH")


class TerminatorAPI(TerminalAPI):
    name = "terminator"
    selection_supported = False
    activation_supported = False

    @staticmethod
    def detect() -> bool:
        return bool(bounded_env(("TERMINATOR_UUID",)).get("TERMINATOR_UUID"))

    @staticmethod
    def capture_env() -> dict:
        captured = bounded_env(ENV_KEYS)
        return {key: captured.get(key, "") for key in ENV_KEYS}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        return False
