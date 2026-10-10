"""macOS Terminal.app API via osascript.

Terminal.app's TERM_SESSION_ID is a UUID used for shell session restoration;
its AppleScript dictionary exposes no session identifier, only each tab's
``tty``. The target is therefore the agent's controlling terminal, read at
focus time with ``ps -o tty= -p <pid>`` (the hook stays env-only), and matched
exactly against ``tty of t``; the same lookup on a tmux client's pid makes
Terminal usable as a tmux parent. An agent without a controlling tty has no
target; the pid is never used as one. The tty reaches osascript as a
run-handler argument, never as script text.

Selection selects the tab without reordering windows and is claimed only when
an independent query reads the target back as the selected tab of Terminal's
front window; for a background window that readback succeeds after
activation. Activation un-minimizes the target's window, brings it to the
front and activates Terminal, and is claimed only when Terminal is frontmost
and its front window, not minimized, holds the target. Unvalidated on macOS
(#55).
"""

from claude_fleet_monitor.terminal_apis import _applescript
from claude_fleet_monitor.terminal_apis._applescript import (
    AppleScriptError,
    AppleScriptTimeout,
)
from claude_fleet_monitor.terminal_apis._env import bounded_env
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

APP = "Terminal"
ENV_KEY = "TERM_SESSION_ID"

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


def _arguments(tab_id) -> tuple[str]:
    if not _applescript.is_tty_path(tab_id):
        raise AppleScriptError("Terminal tty target rejected")
    return (tab_id,)


class MacOSTerminalAPI(TerminalAPI):
    name = "macos_terminal"
    deferred_selection_readback = True

    @staticmethod
    def detect() -> bool:
        return bounded_env(("TERM_PROGRAM",)).get("TERM_PROGRAM") == "Apple_Terminal"

    @staticmethod
    def capture_env() -> dict:
        value = bounded_env((ENV_KEY,)).get(ENV_KEY, "")
        return {ENV_KEY: value if _applescript.is_uuid(value) else ""}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        return _applescript.controlling_tty(pid, APP)

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        arguments = _arguments(tab_id)
        _applescript.expect(APP, SELECT_SCRIPT, arguments, "selected", _DETAILS)
        _applescript.expect(
            APP, SELECTION_READBACK_SCRIPT, arguments, "current", _DETAILS
        )
        return True

    def verify_selection(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            _applescript.expect(
                APP, SELECTION_READBACK_SCRIPT, _arguments(tab_id), "current", _DETAILS
            )
        except AppleScriptError:
            return False
        return True

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        arguments = _arguments(tab_id)
        try:
            _applescript.expect(APP, RAISE_SCRIPT, arguments, "requested", _DETAILS)
        except AppleScriptTimeout:
            self._mark_raise_requested()
            raise
        self._mark_raise_requested()
        _applescript.poll(
            APP, ACTIVATION_READBACK_SCRIPT, arguments, "frontmost", _DETAILS
        )
        return True
