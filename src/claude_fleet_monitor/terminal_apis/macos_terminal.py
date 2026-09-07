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
                return "focused"
            end if
        end repeat
    end repeat
end tell
return "not-found"
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0 and result.stdout.strip() == "focused"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        script = '''
tell application "Terminal"
    activate
end tell
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
