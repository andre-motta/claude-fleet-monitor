"""GNOME Terminal API via gdbus."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class GnomeAPI(TerminalAPI):
    name = "gnome"

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("VTE_VERSION") or os.environ.get("GNOME_TERMINAL_SERVICE"))

    @staticmethod
    def capture_env() -> dict:
        return {
            "VTE_VERSION": os.environ.get("VTE_VERSION", ""),
            "GNOME_TERMINAL_SERVICE": os.environ.get("GNOME_TERMINAL_SERVICE", ""),
            "GNOME_TERMINAL_SCREEN": os.environ.get("GNOME_TERMINAL_SCREEN", ""),
        }

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        # GNOME Terminal doesn't expose per-tab process mapping via DBus.
        # Use xdotool to find the window by PID ancestry.
        try:
            import sys
            if sys.platform != "linux":
                return None
            check_pid = pid
            while check_pid > 1:
                try:
                    result = subprocess.run(
                        ["xdotool", "search", "--pid", str(check_pid)],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.stdout.strip():
                        return result.stdout.strip().split("\n")[0]
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    return None
                try:
                    stat = open(f"/proc/{check_pid}/stat").read()
                    check_pid = int(stat.split(") ")[1].split()[1])
                except (OSError, ValueError, IndexError):
                    break
        except Exception:
            pass
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        # GNOME Terminal has no public tab switching API.
        return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            subprocess.run(
                ["xdotool", "windowactivate", tab_id],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
