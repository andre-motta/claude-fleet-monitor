"""Run fixed AppleScript programs whose data arrives only through argv.

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
READBACK_ATTEMPTS = 5
READBACK_INTERVAL = 0.1
_DETAIL_LIMIT = 80
_UUID_PATTERN = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_SAFE_ARGUMENT = re.compile(r"[0-9A-Za-z/][0-9A-Za-z/-]{0,63}")
_AUTOMATION_DENIED = "-1743"


class AppleScriptError(RuntimeError):
    """A failed AppleScript step whose message is the user-facing detail."""


class AppleScriptTimeout(AppleScriptError):
    """osascript did not finish, so the script may have partly run."""


def is_uuid(value) -> bool:
    return isinstance(value, str) and _UUID_PATTERN.fullmatch(value) is not None


def _first_line(text) -> str:
    for line in str(text or "").splitlines():
        line = "".join(
            character for character in line if character.isprintable()
        ).strip()
        if line:
            return line[:_DETAIL_LIMIT]
    return ""


def run(app: str, script: str, argument: str) -> str:
    """Run ``script`` with ``argument`` as ``item 1 of argv``; return stdout."""
    if not isinstance(argument, str) or _SAFE_ARGUMENT.fullmatch(argument) is None:
        raise AppleScriptError(f"{app} AppleScript argument rejected")
    if sys.platform != "darwin":
        raise AppleScriptError(f"{app} AppleScript is only available on macOS")
    try:
        result = subprocess.run(
            ["osascript", "-e", script, argument],
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
    app: str, script: str, argument: str, success: str, details: dict[str, str]
) -> None:
    """Raise unless the script reports ``success``."""
    token = run(app, script, argument)
    if token != success:
        raise _mismatch(app, token, details)


def poll(
    app: str, script: str, argument: str, success: str, details: dict[str, str]
) -> None:
    """Repeat a readback until it reports ``success``; activation is async.

    Only a reported mismatch is retried; a failed or timed-out osascript run
    ends the readback at once.
    """
    for attempt in range(READBACK_ATTEMPTS):
        token = run(app, script, argument)
        if token == success:
            return
        if attempt + 1 >= READBACK_ATTEMPTS:
            raise _mismatch(app, token, details)
        time.sleep(READBACK_INTERVAL)
