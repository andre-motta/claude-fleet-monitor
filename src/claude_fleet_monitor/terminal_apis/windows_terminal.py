"""Windows Terminal API. No tab selection; unique window activation only."""

import os

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

WINDOW_TITLE = "Windows Terminal"


def _unique_window():
    try:
        import pywinctl
    except ImportError:
        raise LookupError("pywinctl is not installed") from None
    windows = list(pywinctl.getWindowsWithTitle(WINDOW_TITLE) or ())
    if not windows:
        raise LookupError("no Windows Terminal window found")
    if len(windows) > 1:
        raise LookupError(
            f"{len(windows)} Windows Terminal windows; exact window unknown"
        )
    return windows[0]


class WindowsTerminalAPI(TerminalAPI):
    name = "windows_terminal"
    selection_supported = False

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
        return str(_unique_window().getHandle())

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            window = _unique_window()
        except LookupError as error:
            raise RuntimeError(str(error)) from None
        if str(window.getHandle()) != tab_id:
            raise RuntimeError("Windows Terminal window changed before activation")
        window.activate()
        if not window.isActive:
            raise RuntimeError("Windows Terminal window did not become active")
        return True
