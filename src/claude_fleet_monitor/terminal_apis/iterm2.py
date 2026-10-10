"""iTerm2 terminal API via osascript.

iTerm2 sets ITERM_SESSION_ID to ``w<N>t<N>p<N>:<guid>`` where the guid is an
NSUUID string, and exposes the same guid as a session's AppleScript
``unique ID`` (PTYSession sessionId and the ``guid`` key in iTerm2.sdef). Only
a captured value of exactly that shape yields a target, and the guid reaches
osascript as a run-handler argument, never as script text.

Selection selects the target's window, tab and session, and is claimed only
when an independent query reads the target back as the current session of
iTerm2's current window. Activation selects that window and activates iTerm2,
and is claimed only when iTerm2 is frontmost and its current window holds the
target. Unvalidated on macOS (#55).
"""

import re

from claude_fleet_monitor.terminal_apis import _applescript
from claude_fleet_monitor.terminal_apis._applescript import (
    AppleScriptError,
    AppleScriptTimeout,
)
from claude_fleet_monitor.terminal_apis._env import bounded_env
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

APP = "iTerm2"
ENV_KEY = "ITERM_SESSION_ID"
_SESSION_ID = re.compile(r"w\d{1,9}t\d{1,9}p\d{1,9}:(?P<guid>[0-9A-Fa-f-]{36})")

SELECT_SCRIPT = """on run argv
set targetId to item 1 of argv
if application "iTerm2" is not running then return "not-running"
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (unique ID of s) is targetId then
                    select w
                    select t
                    select s
                    return "selected"
                end if
            end repeat
        end repeat
    end repeat
end tell
return "not-found"
end run
"""

SELECTION_READBACK_SCRIPT = """on run argv
set targetId to item 1 of argv
if application "iTerm2" is not running then return "not-running"
tell application "iTerm2"
    try
        set w to current window
        if w is missing value then return "no-window"
        set currentId to unique ID of current session of w
    on error
        return "no-window"
    end try
end tell
if currentId is targetId then return "current"
return "other"
end run
"""

RAISE_SCRIPT = """on run argv
set targetId to item 1 of argv
if application "iTerm2" is not running then return "not-running"
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (unique ID of s) is targetId then
                    select w
                    activate
                    return "requested"
                end if
            end repeat
        end repeat
    end repeat
end tell
return "not-found"
end run
"""

ACTIVATION_READBACK_SCRIPT = """on run argv
set targetId to item 1 of argv
if application "iTerm2" is not running then return "not-running"
tell application "iTerm2"
    if not frontmost then return "background"
    try
        set w to current window
        if w is missing value then return "no-window"
        if miniaturized of w then return "minimized"
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (unique ID of s) is targetId then return "frontmost"
            end repeat
        end repeat
    on error
        return "no-window"
    end try
end tell
return "other-window"
end run
"""

_DETAILS = {
    "not-running": "iTerm2 is not running",
    "not-found": "iTerm2 session no longer exists",
    "no-window": "iTerm2 has no current window",
    "other": "iTerm2 current session is a different session",
    "background": "iTerm2 is not the frontmost application",
    "minimized": "iTerm2 window is minimized",
    "other-window": "iTerm2 current window does not hold the session",
}


def session_guid(value) -> str | None:
    """Return the AppleScript unique ID from a well-formed ITERM_SESSION_ID."""
    if not isinstance(value, str):
        return None
    match = _SESSION_ID.fullmatch(value)
    if match is None or not _applescript.is_uuid(match["guid"]):
        return None
    return match["guid"]


def _target(tab_id) -> str:
    if not _applescript.is_uuid(tab_id):
        raise AppleScriptError("iTerm2 session target rejected")
    return tab_id


class ITerm2API(TerminalAPI):
    name = "iterm2"

    @staticmethod
    def detect() -> bool:
        return bool(bounded_env((ENV_KEY,)).get(ENV_KEY))

    @staticmethod
    def capture_env() -> dict:
        value = bounded_env((ENV_KEY,)).get(ENV_KEY, "")
        return {ENV_KEY: value if session_guid(value) else ""}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        value = terminal_env.get(ENV_KEY) if isinstance(terminal_env, dict) else None
        if not value:
            raise LookupError("iTerm2 session id was not captured")
        guid = session_guid(value)
        if guid is None:
            raise LookupError(
                "iTerm2 session id rejected (expected w<N>t<N>p<N>:<UUID>)"
            )
        return guid

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
