"""Shared macOS helpers: fixed AppleScript with data only in argv, and tty lookup.

osascript hands the arguments that follow ``-e <script>`` to the script's
``on run argv`` handler as a list of strings, so captured identifiers are never
compiled as AppleScript. Every script returns a fixed status token; callers map
tokens to user-facing details. Arguments are validated by the adapters and
checked again here, and never start with "-" so osascript cannot read them as
options.
"""

import re
import subprocess
import sys
import time

TIMEOUT = 5
PS_TIMEOUT = 5
READBACK_ATTEMPTS = 5
READBACK_INTERVAL = 0.1
_DETAIL_LIMIT = 80
_UUID_PATTERN = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_SAFE_ARGUMENT = re.compile(r"[0-9A-Za-z/][0-9A-Za-z/-]{0,63}")
_PS_TTY = re.compile(r"(?:/dev/)?(?:tty)?(?P<name>s[0-9]{1,4})")
_TTY_PATH = re.compile(r"/dev/ttys[0-9]{1,4}")
_AUTOMATION_DENIED = "-1743"


class AppleScriptError(RuntimeError):
    """A failed AppleScript step whose message is the user-facing detail."""


class AppleScriptTimeout(AppleScriptError):
    """osascript did not finish, so the script may have partly run."""


def is_uuid(value) -> bool:
    return isinstance(value, str) and _UUID_PATTERN.fullmatch(value) is not None


def is_tty_path(value) -> bool:
    return isinstance(value, str) and _TTY_PATH.fullmatch(value) is not None


def controlling_tty(pid, app: str) -> str:
    """Return the ``/dev/ttysNNN`` path of the process's controlling tty.

    Read at focus time with ``ps``; the hook stays env-only.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise LookupError("agent process id is not valid")
    if sys.platform != "darwin":
        raise LookupError(f"{app} tabs can only be matched on macOS")
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
        raise LookupError("agent process has no controlling tty")
    return f"/dev/tty{match['name']}"


def _first_line(text) -> str:
    for line in str(text or "").splitlines():
        line = "".join(
            character for character in line if character.isprintable()
        ).strip()
        if line:
            return line[:_DETAIL_LIMIT]
    return ""


def run(app: str, script: str, arguments: tuple[str, ...]) -> str:
    """Run ``script`` with ``arguments`` as its argv list; return stdout."""
    if not isinstance(arguments, tuple) or not arguments or not all(
        isinstance(argument, str) and _SAFE_ARGUMENT.fullmatch(argument)
        for argument in arguments
    ):
        raise AppleScriptError(f"{app} AppleScript argument rejected")
    if sys.platform != "darwin":
        raise AppleScriptError(f"{app} AppleScript is only available on macOS")
    try:
        result = subprocess.run(
            ["osascript", "-e", script, *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise AppleScriptError("osascript not found") from None
    except subprocess.TimeoutExpired:
        raise AppleScriptTimeout(
            f"{app} AppleScript did not complete within {TIMEOUT}s"
        ) from None
    except OSError:
        raise AppleScriptError("osascript could not be started") from None
    if result.returncode != 0:
        message = _first_line(result.stderr)
        if _AUTOMATION_DENIED in message:
            raise AppleScriptError(
                f"macOS Automation permission to control {app} is not granted"
            )
        detail = f"{app} AppleScript exited {result.returncode}"
        raise AppleScriptError(f"{detail}: {message}" if message else detail)
    return result.stdout.strip()


def _mismatch(app: str, token: str, details: dict[str, str]) -> AppleScriptError:
    return AppleScriptError(
        details.get(token, f"{app} AppleScript returned unexpected output")
    )


def expect(
    app: str,
    script: str,
    arguments: tuple[str, ...],
    success: str,
    details: dict[str, str],
) -> None:
    """Raise unless the script reports ``success``."""
    token = run(app, script, arguments)
    if token != success:
        raise _mismatch(app, token, details)


def poll(
    app: str,
    script: str,
    arguments: tuple[str, ...],
    success: str,
    details: dict[str, str],
) -> None:
    """Repeat a readback until it reports ``success``; activation is async.

    Only a reported mismatch is retried; a failed or timed-out osascript run
    ends the readback at once.
    """
    for attempt in range(READBACK_ATTEMPTS):
        token = run(app, script, arguments)
        if token == success:
            return
        if attempt + 1 >= READBACK_ATTEMPTS:
            raise _mismatch(app, token, details)
        time.sleep(READBACK_INTERVAL)
