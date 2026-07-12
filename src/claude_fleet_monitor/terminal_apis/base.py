"""Abstract base class for terminal APIs."""

from abc import ABC, abstractmethod


class TerminalAPI(ABC):
    name: str = "unknown"

    @staticmethod
    @abstractmethod
    def detect() -> bool:
        """Return True if this terminal is the current session's terminal."""

    @staticmethod
    @abstractmethod
    def capture_env() -> dict:
        """Capture terminal-specific env vars for later use by focus."""

    @abstractmethod
    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        """Find the terminal tab/pane ID for a claude process PID."""

    @abstractmethod
    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        """Switch to the tab/pane."""

    @abstractmethod
    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        """Bring the window containing the tab to front."""

    def focus(self, pid: int, terminal_env: dict) -> bool:
        """Find, switch, and raise."""
        tab_id = self.find_tab(pid, terminal_env)
        if not tab_id:
            return False
        self.switch_tab(tab_id, terminal_env)
        self.raise_window(tab_id, terminal_env)
        return True
