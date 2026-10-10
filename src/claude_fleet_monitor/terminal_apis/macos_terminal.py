"""macOS Terminal.app API via osascript.

Terminal.app's TERM_SESSION_ID is a UUID used for shell session restoration;
its AppleScript dictionary exposes no session identifier, only each tab's
``tty``. The target is therefore the agent's controlling terminal, read at
focus time with ``ps -o tty= -p <pid>`` (the hook stays env-only), and matched
exactly against ``tty of t``. An agent without a controlling tty has no target;
the pid is never used as one. The tty reaches osascript as a run-handler
argument, never as script text.

Selection is claimed only when an independent query reads the target back as
the selected tab of Terminal's front window. Activation is claimed only when
Terminal is frontmost and its front window, not minimized, holds the target.
Unvalidated on macOS (#55).
"""

import re
import subprocess
import sys

from claude_fleet_monitor.terminal_apis import _applescript
from claude_fleet_monitor.terminal_apis._applescript import (
    AppleScriptError,
    AppleScriptTimeout,
)
from claude_fleet_monitor.terminal_apis._env import bounded_env
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

APP = "Terminal"
ENV_KEY = "TERM_SESSION_ID"
PS_TIMEOUT = 5
_PS_TTY = re.compile(r"(?:/dev/)?(?:tty)?(?P<name>s\d{1,4})")
_TARGET_TTY = re.compile(r"/dev/ttys\d{1,4}")

SELECT_SCRIPT = """on run argv
set targetTty to item 1 of argv
if application "Terminal" is not running then return "not-running"
tell application "Terminal"
    repeat with w in windows
        set windowTabs to {}
        try
            set windowTabs to tabs of w
        end try
        repeat with t in windowTabs
            if (tty of t) is targetTty then
                set selected tab of w to t
                set index of w to 1
                return "selected"
            end if
        end repeat
    end repeat
end tell
return "not-found"
end run
"""

SELECTION_READBACK_SCRIPT = """on run argv
set targetTty to item 1 of argv
if application "Terminal" is not running then return "not-running"
tell application "Terminal"
    try
        set currentTty to tty of selected tab of front window
    on error
        return "no-window"
    end try
end tell
if currentTty is targetTty then return "current"
return "other"
end run
"""

RAISE_SCRIPT = """on run argv
set targetTty to item 1 of argv
if application "Terminal" is not running then return "not-running"
tell application "Terminal"
    repeat with w in windows
        set windowTabs to {}
        try
            set windowTabs to tabs of w
        end try
        repeat with t in windowTabs
            if (tty of t) is targetTty then
                try
                    if miniaturized of w then set miniaturized of w to false
                end try
                set index of w to 1
                activate
                return "requested"
            end if
        end repeat
    end repeat
end tell
return "not-found"
end run
"""

ACTIVATION_READBACK_SCRIPT = """on run argv
set targetTty to item 1 of argv
if application "Terminal" is not running then return "not-running"
tell application "Terminal"
    if not frontmost then return "background"
    try
        set w to front window
        if miniaturized of w then return "minimized"
        repeat with t in tabs of w
            if (tty of t) is targetTty then return "frontmost"
        end repeat
    on error
        return "no-window"
    end try
end tell
return "other-window"
end run
"""

_DETAILS = {
    "not-running": "Terminal is not running",
    "not-found": "no Terminal tab uses the agent's tty",
    "no-window": "Terminal has no front terminal window",
    "other": "Terminal front window shows a different tab",
    "background": "Terminal is not the frontmost application",
    "minimized": "Terminal window is minimized",
    "other-window": "Terminal front window does not hold the agent's tab",
}


def controlling_tty(pid) -> str:
    """Return the ``/dev/ttysNNN`` path of the process's controlling tty."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise LookupError("agent process id is not valid")
    if sys.platform != "darwin":
        raise LookupError("Terminal tabs can only be matched on macOS")
    try:
        result = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(pid)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=PS_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise LookupError("agent controlling tty could not be read") from None
    if result.returncode != 0:
        raise LookupError("agent process is not running")
    match = _PS_TTY.fullmatch(result.stdout.strip())
    if match is None:
        raise LookupError("agent process has no controlling Terminal tty")
    return f"/dev/tty{match['name']}"


def _target(tab_id) -> str:
    if not isinstance(tab_id, str) or _TARGET_TTY.fullmatch(tab_id) is None:
        raise AppleScriptError("Terminal tty target rejected")
    return tab_id


class MacOSTerminalAPI(TerminalAPI):
    name = "macos_terminal"

    @staticmethod
    def detect() -> bool:
        return bounded_env(("TERM_PROGRAM",)).get("TERM_PROGRAM") == "Apple_Terminal"

    @staticmethod
    def capture_env() -> dict:
        value = bounded_env((ENV_KEY,)).get(ENV_KEY, "")
        return {ENV_KEY: value if _applescript.is_uuid(value) else ""}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return controlling_tty(pid)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        target = _target(tab_id)
        _applescript.expect(APP, SELECT_SCRIPT, target, "selected", _DETAILS)
        _applescript.expect(
            APP, SELECTION_READBACK_SCRIPT, target, "current", _DETAILS
        )
        return True

    def verify_selection(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            _applescript.expect(
                APP, SELECTION_READBACK_SCRIPT, _target(tab_id), "current", _DETAILS
            )
        except AppleScriptError:
            return False
        return True

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        target = _target(tab_id)
        try:
            _applescript.expect(APP, RAISE_SCRIPT, target, "requested", _DETAILS)
        except AppleScriptTimeout:
            self._mark_raise_requested()
            raise
        self._mark_raise_requested()
        _applescript.poll(
            APP, ACTIVATION_READBACK_SCRIPT, target, "frontmost", _DETAILS
        )
        return True
