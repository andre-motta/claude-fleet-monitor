"""Abstract base class for terminal APIs."""

from abc import ABC, abstractmethod

from claude_fleet_monitor.models import FocusOperation, FocusResult


class TerminalAPI(ABC):
    name: str = "unknown"
    selection_supported: bool = True
    activation_supported: bool = True

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
        """Find the terminal tab or pane ID for an agent process PID."""

    @abstractmethod
    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        """Switch to the tab/pane."""

    @abstractmethod
    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        """Bring the window containing the tab to front."""

    def focus(self, pid: int, terminal_env: dict) -> bool:
        """Preserve the legacy true-on-any-success focus contract."""
        return bool(self.focus_result(pid, terminal_env))

    def focus_result(self, pid: int, terminal_env: dict) -> FocusResult:
        """Find a target and report selection and activation independently."""
        tab_id = self.find_tab(pid, terminal_env)
        if not tab_id:
            return FocusResult(
                state="failed",
                reason="terminal target was not found",
                backend=self.name,
                pid=pid,
            )
        if not self.selection_supported:
            selection = FocusOperation.unavailable(
                "backend does not support exact tab or pane selection"
            )
        else:
            try:
                selected = self.switch_tab(tab_id, terminal_env)
            except Exception as error:
                selection = FocusOperation(True, False, str(error))
            else:
                selection = FocusOperation(True, bool(selected), "tab or pane selection")
        if not self.activation_supported:
            activation = FocusOperation.unavailable(
                "backend does not support window activation"
            )
        else:
            try:
                activated = self.raise_window(tab_id, terminal_env)
            except Exception as error:
                activation = FocusOperation(True, False, str(error))
            else:
                activation = FocusOperation(True, bool(activated), "window activation")
        successful = selection.succeeded or activation.succeeded
        complete = selection.succeeded and activation.succeeded
        return FocusResult(
            state="complete" if complete else "partial" if successful else "failed",
            reason=(
                "target selected and window activated"
                if complete
                else "only some terminal focus operations succeeded"
                if successful
                else "terminal focus operations failed"
            ),
            backend=self.name,
            pid=pid,
            target_found=True,
            selection=selection,
            activation=activation,
        )
