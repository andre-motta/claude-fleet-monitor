"""iTerm2 terminal API via osascript."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


class ITerm2API(TerminalAPI):
    name = "iterm2"

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("ITERM_SESSION_ID"))

    @staticmethod
    def capture_env() -> dict:
        return {"ITERM_SESSION_ID": os.environ.get("ITERM_SESSION_ID", "")}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        session_id = terminal_env.get("ITERM_SESSION_ID", "")
        return session_id if session_id else None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        script = f'''
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if unique ID of s is "{tab_id}" then
                    select t
                    select s
                    return "focused"
                end if
            end repeat
        end repeat
    end repeat
end tell
return "not-found"
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5
            )
            return result.returncode == 0 and result.stdout.strip() == "focused"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        script = '''
tell application "iTerm2"
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
