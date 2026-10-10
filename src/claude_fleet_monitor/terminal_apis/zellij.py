"""Zellij terminal API."""

import os

from claude_fleet_monitor.terminal_apis import tmux
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.parent import activate_parent


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
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            pid = int(tab_id)
        except (TypeError, ValueError):
            return False
        parent = tmux._detect_parent_terminal(pid)
        if parent is None:
            raise RuntimeError("no parent terminal emulator found for zellij")
        if not getattr(parent, "activation_supported", True):
            raise RuntimeError(
                f"parent terminal {parent.name} does not support window activation"
            )
        return activate_parent(parent, pid)
