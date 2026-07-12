"""Terminal API auto-detection and dispatch."""

from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.konsole import KonsoleAPI
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI
from claude_fleet_monitor.terminal_apis.gnome import GnomeAPI
from claude_fleet_monitor.terminal_apis.iterm2 import ITerm2API
from claude_fleet_monitor.terminal_apis.macos_terminal import MacOSTerminalAPI
from claude_fleet_monitor.terminal_apis.windows_terminal import WindowsTerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI

TERMINALS: list[type[TerminalAPI]] = [
    TmuxAPI,
    ZellijAPI,
    KonsoleAPI,
    ITerm2API,
    MacOSTerminalAPI,
    GnomeAPI,
    WindowsTerminalAPI,
    GenericAPI,
]


def detect_terminal() -> TerminalAPI:
    for cls in TERMINALS:
        if cls.detect():
            return cls()
    return GenericAPI()


def capture_terminal_info() -> dict:
    terminal = detect_terminal()
    return {"terminal": terminal.name, "terminal_env": terminal.capture_env()}


def get_terminal_api(terminal_type: str) -> TerminalAPI:
    for cls in TERMINALS:
        if cls.name == terminal_type:
            return cls()
    return GenericAPI()
