"""macOS Terminal.app API via osascript."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class MacOSTerminalAPI(TerminalAPI):
    name = "macos_terminal"

    @staticmethod
    def detect() -> bool:
        return os.environ.get("TERM_PROGRAM") == "Apple_Terminal"

    @staticmethod
    def capture_env() -> dict:
        return {"TERM_SESSION_ID": os.environ.get("TERM_SESSION_ID", "")}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return terminal_env.get("TERM_SESSION_ID") or str(pid)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        script = f'''
tell application "Terminal"
    repeat with w in windows
        repeat with t in tabs of w
            if tty of t contains "{tab_id}" then
                set selected tab of w to t
                set index of w to 1
                return
            end if
        end repeat
    end repeat
end tell
'''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        script = '''
tell application "Terminal"
    activate
end tell
'''
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
