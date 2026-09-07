"""Abstract base class for terminal APIs."""

from abc import ABC, abstractmethod

from claude_fleet_monitor.models import FocusOperation, FocusResult


class TerminalAPI(ABC):
    name: str = "unknown"
    selection_supported: bool = True
    activation_supported: bool = True
    activation_before_selection: bool = False

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

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        """Return a window activation target independently of tab selection."""
        return tab_id

    def prepare_selection_after_activation(self) -> None:
        """Wait for an activated window when a backend requires settling."""

    def focus(self, pid: int, terminal_env: dict) -> bool:
        """Preserve the legacy true-on-any-success focus contract."""
        return bool(self.focus_result(pid, terminal_env))

    def focus_result(self, pid: int, terminal_env: dict) -> FocusResult:
        """Find a target and report selection and activation independently."""
        try:
            tab_id = self.find_tab(pid, terminal_env)
        except Exception as error:
            tab_id = None
            lookup_detail = str(error)
        else:
            lookup_detail = "exact tab or pane target was not found"
        try:
            activation_target = self.find_activation_target(
                pid, terminal_env, tab_id
            )
        except Exception as error:
            activation_target = None
            activation_lookup_detail = str(error)
        else:
            activation_lookup_detail = "window activation target was not found"

        def select_target():
            if not self.selection_supported:
                return FocusOperation.unavailable(
                    "backend does not support exact tab or pane selection"
                )
            if not tab_id:
                return FocusOperation.unavailable(lookup_detail)
            try:
                selected = self.switch_tab(tab_id, terminal_env)
            except Exception as error:
                return FocusOperation(True, False, str(error))
            return FocusOperation(True, bool(selected), "tab or pane selection")

        def activate_target():
            if not self.activation_supported:
                return FocusOperation.unavailable(
                    "backend does not support window activation"
                )
            if not activation_target:
                return FocusOperation.unavailable(activation_lookup_detail)
            try:
                activated = self.raise_window(activation_target, terminal_env)
            except Exception as error:
                return FocusOperation(True, False, str(error))
            return FocusOperation(True, bool(activated), "window activation")

        if self.activation_before_selection:
            activation = activate_target()
            if activation.succeeded:
                try:
                    self.prepare_selection_after_activation()
                except Exception as error:
                    selection = FocusOperation.unavailable(str(error))
                else:
                    selection = select_target()
            else:
                selection = FocusOperation.unavailable(
                    "selection skipped because window activation did not succeed"
                )
        else:
            selection = select_target()
            activation = activate_target()
        successful = selection.succeeded or activation.succeeded
        complete = selection.succeeded and activation.succeeded
        target_found = bool(tab_id or activation_target)
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
            target_found=target_found,
            selection=selection,
            activation=activation,
        )
