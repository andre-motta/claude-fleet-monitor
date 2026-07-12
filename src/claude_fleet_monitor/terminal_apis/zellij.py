"""Zellij terminal API."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class ZellijAPI(TerminalAPI):
    name = "zellij"

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
        # Zellij doesn't expose per-pane PID mapping via CLI.
        # Best effort: return PID as identifier.
        return str(pid)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        session = terminal_env.get("ZELLIJ_SESSION_NAME", "")
        if not session:
            return False
        try:
            subprocess.run(
                ["zellij", "--session", session, "action", "focus-tab"],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        # Zellij runs inside another terminal. Detect parent and raise it.
        try:
            result = subprocess.run(
                ["pgrep", "-x", "zellij"], capture_output=True, text=True, timeout=5
            )
            for pid_str in result.stdout.strip().split("\n"):
                if pid_str:
                    from claude_fleet_monitor.terminal_apis.tmux import _detect_parent_terminal
                    parent = _detect_parent_terminal(int(pid_str))
                    if parent:
                        parent_tab = parent.find_tab(int(pid_str), {})
                        if parent_tab:
                            parent.switch_tab(parent_tab, {})
                            parent.raise_window(parent_tab, {})
                            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        from claude_fleet_monitor.terminal_apis.generic import GenericAPI
        return GenericAPI().raise_window(tab_id, {})
