"""Exact owner-window lookup and confirmed activation through xdotool on X11.

A visible-only search misses minimized windows and windows on other desktops
because both are unmapped, so it can return an unrelated window of the same
process. The lookup therefore lists every window of the process and keeps only
window-manager-managed clients: those carry _NET_WM_DESKTOP, which GTK's
hidden client-leader window never does.
"""

import subprocess
import time

from claude_fleet_monitor.terminal_apis._env import is_decimal_id

XDOTOOL_TIMEOUT = 2.0
MAX_CANDIDATES = 16


def xdotool(args: list[str], timeout: float = XDOTOOL_TIMEOUT):
    try:
        return subprocess.run(
            ["xdotool", *args], capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError:
        raise RuntimeError("xdotool is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xdotool {args[0]} timed out") from None
    except OSError as error:
        raise RuntimeError(f"xdotool {args[0]} failed: {error.strerror}") from None


def _budget(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("X11 window lookup timed out")
    return min(remaining, XDOTOOL_TIMEOUT)


def managed_window(pid: int, owner: str, deadline: float) -> str:
    """Return the only managed top-level window of pid or raise the reason."""
    search = xdotool(["search", "--pid", str(pid)], _budget(deadline))
    if search.returncode not in (0, 1):
        raise RuntimeError(f"xdotool search exited {search.returncode}")
    candidates = list(dict.fromkeys(
        line.strip() for line in search.stdout.splitlines() if line.strip()
    ))
    if not all(is_decimal_id(window) for window in candidates):
        raise RuntimeError("xdotool returned an invalid window id")
    if len(candidates) > MAX_CANDIDATES:
        raise RuntimeError(
            f"{owner} owns {len(candidates)} X11 windows; exact window unknown"
        )
    managed = [
        window
        for window in candidates
        if xdotool(
            ["get_desktop_for_window", window], _budget(deadline)
        ).returncode == 0
    ]
    if not managed:
        raise RuntimeError(f"{owner} owns no managed X11 window")
    if len(managed) > 1:
        raise RuntimeError(
            f"{owner} owns {len(managed)} windows; exact window unknown"
        )
    return managed[0]


def activate(window: str) -> bool:
    """Activate window and succeed only when X11 reads it back as active."""
    if not is_decimal_id(window):
        raise RuntimeError("invalid X11 window id")
    activated = xdotool(["windowactivate", "--sync", window])
    if activated.returncode != 0:
        raise RuntimeError(f"xdotool windowactivate exited {activated.returncode}")
    active = xdotool(["getactivewindow"])
    if active.returncode != 0:
        raise RuntimeError(f"xdotool getactivewindow exited {active.returncode}")
    if active.stdout.strip() != window:
        raise RuntimeError("active window readback did not match the target")
    return True
