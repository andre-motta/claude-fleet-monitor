"""Generic fallback terminal API.

It identifies no tab and no window, so it never selects or activates
anything. The former window-title-equals-PID match and the xdotool search
on the agent PID could activate an arbitrary window, so both were removed.
"""

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class GenericAPI(TerminalAPI):
    name = "generic"
    selection_supported = False
    activation_supported = False

    @staticmethod
    def detect() -> bool:
        return True

    @staticmethod
    def capture_env() -> dict:
        return {}

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
