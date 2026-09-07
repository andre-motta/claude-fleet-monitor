"""Zellij terminal API."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class ZellijAPI(TerminalAPI):
    name = "zellij"
    selection_supported = False

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("ZELLIJ"))

    @staticmethod
    def capture_env() -> dict:
        return {
            "ZELLIJ": os.environ.get("ZELLIJ", ""),
            "ZELLIJ_SESSION_NAME": os.environ.get("ZELLIJ_SESSION_NAME", ""),
        }

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return None

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        if terminal_env.get("ZELLIJ") or terminal_env.get("ZELLIJ_SESSION_NAME"):
            return str(pid)
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        session = terminal_env.get("ZELLIJ_SESSION_NAME", "")
        if not session:
            return False
        try:
            result = subprocess.run(
                ["zellij", "--session", session, "action", "focus-tab"],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            pid = int(tab_id)
        except ValueError:
            return False

        from claude_fleet_monitor.terminal_apis.tmux import _detect_parent_terminal
        parent = _detect_parent_terminal(pid)
        if parent and parent.focus_result(pid, {}).activation.succeeded:
            return True

        from claude_fleet_monitor.terminal_apis.generic import GenericAPI
        return GenericAPI().raise_window(str(pid), {})
