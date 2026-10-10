"""iTerm2 terminal API via osascript.

iTerm2 sets ITERM_SESSION_ID to ``w<N>t<N>p<N>:<guid>`` where the guid is an
NSUUID string, and exposes the same guid as a session's AppleScript
``unique ID`` (PTYSession sessionId and the ``guid`` key in iTerm2.sdef).

ITERM_SESSION_ID leaks into anything launched from an iTerm2 shell, so a
session matches only when both its ``unique ID`` and its ``tty`` agree with the
agent: the tty is the agent's controlling terminal, read at focus time. Without
a readable tty there is no target. A record without the variable (a tmux
client's parent lookup) matches by tty alone and requires exactly one session
with that tty. Values reach osascript only as run-handler arguments.

Selection selects the target's tab and session without reordering windows and
is claimed only when an independent query reads the target back as the current
session of iTerm2's current window; for a background window that readback
succeeds after activation. Activation un-minimizes and selects the target's
window and activates iTerm2, and is claimed only when iTerm2 is frontmost and
its current window holds the target. Unvalidated on macOS (#55).
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
_SESSION_ID = re.compile(
    r"w[0-9]{1,9}t[0-9]{1,9}p[0-9]{1,9}:(?P<guid>[0-9A-Fa-f-]{36})"
)
_TARGET_SEPARATOR = "#"

_PROLOGUE = """on run argv
set targetTty to item 1 of argv
set targetId to ""
if (count of argv) > 1 then set targetId to item 2 of argv
if application "iTerm2" is not running then return "not-running"
tell application "iTerm2"
"""

_FIND_UNIQUE_SESSION = """    set matchCount to 0
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (tty of s) is targetTty then
                    if targetId is "" or (unique ID of s) is targetId then
                        set matchCount to matchCount + 1
                        set targetWindow to contents of w
                        set targetTab to contents of t
                        set targetSession to contents of s
                    end if
                end if
            end repeat
        end repeat
    end repeat
    if matchCount is 0 then return "not-found"
    if matchCount > 1 then return "ambiguous"
"""

SELECT_SCRIPT = (
    _PROLOGUE
    + _FIND_UNIQUE_SESSION
    + """    select targetTab
    select targetSession
end tell
return "selected"
end run
"""
)

SELECTION_READBACK_SCRIPT = (
    _PROLOGUE
    + """    try
        set w to current window
        if w is missing value then return "no-window"
        set s to current session of w
        set currentTty to tty of s
        set currentId to unique ID of s
    on error
        return "no-window"
    end try
end tell
if currentTty is targetTty and (targetId is "" or currentId is targetId) then
    return "current"
end if
return "other"
end run
"""
)

RAISE_SCRIPT = (
    _PROLOGUE
    + _FIND_UNIQUE_SESSION
    + """    try
        set miniaturized of targetWindow to false
    end try
    select targetWindow
    activate
end tell
return "requested"
end run
"""
)

ACTIVATION_READBACK_SCRIPT = (
    _PROLOGUE
    + """    if not frontmost then return "background"
    try
        set w to current window
        if w is missing value then return "no-window"
        if miniaturized of w then return "minimized"
        repeat with t in tabs of w
            repeat with s in sessions of t
                if (tty of s) is targetTty then
                    if targetId is "" or (unique ID of s) is targetId then
                        return "frontmost"
                    end if
                end if
            end repeat
        end repeat
    on error
        return "no-window"
    end try
end tell
return "other-window"
end run
"""
)

_DETAILS = {
    "not-running": "iTerm2 is not running",
    "not-found": "no iTerm2 session matches the agent's session id and tty",
    "ambiguous": "more than one iTerm2 session uses the agent's tty",
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


def _arguments(tab_id) -> tuple[str, ...]:
    """Split a ``<tty>`` or ``<tty>#<guid>`` target into validated argv items."""
    if isinstance(tab_id, str):
        tty, separator, guid = tab_id.partition(_TARGET_SEPARATOR)
        if _applescript.is_tty_path(tty):
            if not separator:
                return (tty,)
            if _applescript.is_uuid(guid):
                return (tty, guid)
    raise AppleScriptError("iTerm2 session target rejected")


class ITerm2API(TerminalAPI):
    name = "iterm2"
    deferred_selection_readback = True

    @staticmethod
    def detect() -> bool:
        return bool(bounded_env((ENV_KEY,)).get(ENV_KEY))

    @staticmethod
    def capture_env() -> dict:
        value = bounded_env((ENV_KEY,)).get(ENV_KEY, "")
        return {ENV_KEY: value if session_guid(value) else ""}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if not isinstance(terminal_env, dict):
            terminal_env = {}
        if ENV_KEY not in terminal_env:
            return _applescript.controlling_tty(pid, APP)
        value = terminal_env.get(ENV_KEY)
        if not value:
            raise LookupError("iTerm2 session id was not captured")
        guid = session_guid(value)
        if guid is None:
            raise LookupError(
                "iTerm2 session id rejected (expected w<N>t<N>p<N>:<UUID>)"
            )
        tty = _applescript.controlling_tty(pid, APP)
        return f"{tty}{_TARGET_SEPARATOR}{guid}"

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
                APP, SELECTION_READBACK_SCRIPT, _arguments(tab_id), "current",
                _DETAILS,
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
