"""KDE Konsole terminal API via qdbus + KWin."""

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

_QDBUS_CANDIDATES = ("qdbus", "qdbus6", "qdbus-qt6")
_ACTIVATION_SETTLE_SECONDS = 1.0
_ACTIVATION_POLL_SECONDS = 0.05
_KWIN_ACTIVATE_SCRIPT = """
var titles = __TITLES__;
var owner = __OWNER__;
var matches = [];
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    var candidate = windows[i];
    if (candidate.pid !== owner) {
        continue;
    }
    for (var j = 0; j < titles.length; j++) {
        var rest = candidate.caption.slice(titles[j].length);
        var suffix = /^( \\u2014 [^\\u2014]+)?( <\\d+>)?$/;
        if (candidate.caption.indexOf(titles[j]) === 0 && suffix.test(rest)) {
            matches.push(candidate);
            break;
        }
    }
}
if (matches.length === 1) {
    matches[0].minimized = false;
    workspace.activeWindow = matches[0];
}
"""


class KonsoleFocusError(RuntimeError):
    """A failed Konsole focus step; the message is the user-facing detail."""


def _resolve_qdbus() -> str | None:
    for candidate in _QDBUS_CANDIDATES:
        try:
            executable = shutil.which(candidate)
        except OSError:
            continue
        if executable:
            return executable
    return None


def _run_qdbus(
    executable: str | None,
    arguments: list[str],
    *,
    timeout: float,
    text: bool,
) -> subprocess.CompletedProcess | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result


class KonsoleAPI(TerminalAPI):
    name = "konsole"
    deferred_selection_readback = True

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("KONSOLE_VERSION"))

    @staticmethod
    def capture_env() -> dict:
        return {
            "KONSOLE_DBUS_SERVICE": os.environ.get("KONSOLE_DBUS_SERVICE", ""),
            "KONSOLE_DBUS_SESSION": os.environ.get("KONSOLE_DBUS_SESSION", ""),
            "KONSOLE_VERSION": os.environ.get("KONSOLE_VERSION", ""),
        }

    def _find_service(self, executable: str | None = None) -> str | None:
        if executable is None:
            executable = _resolve_qdbus()
        result = _run_qdbus(executable, [], timeout=5, text=True)
        if result is None:
            return None
        for line in (result.stdout or "").strip().split("\n"):
            if "org.kde.konsole" in line:
                return line.strip()
        return None

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        executable = _resolve_qdbus()
        if not executable:
            return None
        svc = terminal_env.get("KONSOLE_DBUS_SERVICE") or self._find_service(
            executable
        )
        if not svc:
            return None

        sessions_result = _run_qdbus(
            executable, [svc], timeout=5, text=True
        )
        if sessions_result is None:
            return None
        sessions_out = sessions_result.stdout or ""

        session_ids = re.findall(r"/Sessions/(\d+)", sessions_out)
        window_ids = re.findall(r"/Windows/(\d+)", sessions_out)

        for sess_id in session_ids:
            for prop in ("foregroundProcessId", "processId"):
                result = _run_qdbus(
                    executable,
                    [
                        svc,
                        f"/Sessions/{sess_id}",
                        f"org.kde.konsole.Session.{prop}",
                    ],
                    timeout=2,
                    text=True,
                )
                if result is None:
                    continue
                p = (result.stdout or "").strip()
                if p == str(pid):
                    for win_id in window_ids:
                        result = _run_qdbus(
                            executable,
                            [
                                svc,
                                f"/Windows/{win_id}",
                                "org.kde.konsole.Window.sessionList",
                            ],
                            timeout=2,
                            text=True,
                        )
                        if result is None:
                            continue
                        win_sessions = (result.stdout or "").strip()
                        if sess_id in win_sessions.split("\n"):
                            return f"{svc}|{win_id}|{sess_id}"
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_tab_id(tab_id)
        if target is None:
            return False
        executable = _require_qdbus()
        svc, win_id, sess_id = target
        selected = _run_qdbus(
            executable,
            [
                svc,
                f"/Windows/{win_id}",
                "org.kde.konsole.Window.setCurrentSession",
                sess_id,
            ],
            timeout=2,
            text=False,
        )
        if selected is None:
            raise KonsoleFocusError(f"Konsole could not select tab {sess_id}")
        current = _run_qdbus(
            executable,
            [
                svc,
                f"/Windows/{win_id}",
                "org.kde.konsole.Window.currentSession",
            ],
            timeout=2,
            text=True,
        )
        if current is None:
            raise KonsoleFocusError("Konsole current tab could not be read")
        current_id = (current.stdout or "").strip()
        if current_id != sess_id and _is_number(current_id):
            raise KonsoleFocusError(
                f"tab {sess_id} selection not confirmed (Konsole reports tab"
                f" {current_id}; readback may be stale until activation)"
            )
        if current_id != sess_id:
            raise KonsoleFocusError(_current_tab_detail(current_id, sess_id))
        return True

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_tab_id(tab_id)
        if target is None:
            return False
        executable = _require_qdbus()
        svc, win_id, sess_id = target
        target_title = _session_title(executable, svc, sess_id)
        if not target_title:
            raise KonsoleFocusError(
                f"Konsole tab {sess_id} title could not be read"
            )
        # The window caption follows the last keyboard-focused session, which
        # stays stale while the window is inactive, so match either title.
        titles = [target_title]
        focused = _current_session(executable, svc, win_id)
        if focused and focused != sess_id:
            focused_title = _session_title(executable, svc, focused)
            if focused_title and focused_title not in titles:
                titles.append(focused_title)
        owner = _qdbus_text(
            executable,
            [
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus.GetConnectionUnixProcessID",
                svc,
            ],
        )
        if not _is_number(owner):
            raise KonsoleFocusError(
                "Konsole D-Bus owner process could not be read"
            )
        _activate_by_kwin_caption(titles, int(owner), executable)
        if _wait_for_active_target(
            executable, svc, win_id, sess_id, target_title
        ):
            return True
        raise KonsoleFocusError(
            _activation_failure(executable, svc, win_id, sess_id, target_title)
        )

    def verify_selection(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_tab_id(tab_id)
        executable = _resolve_qdbus()
        if target is None or not executable:
            return False
        svc, win_id, sess_id = target
        return _current_session(executable, svc, win_id) == sess_id


def _require_qdbus() -> str:
    executable = _resolve_qdbus()
    if not executable:
        raise KonsoleFocusError("qdbus is not available")
    return executable


def _current_tab_detail(current: str | None, expected: str) -> str:
    if not _is_number(current):
        return f"Konsole did not report tab {expected} as current"
    return f"Konsole reports tab {current} current, not {expected}"


def _parse_tab_id(tab_id: str) -> tuple[str, str, str] | None:
    if not isinstance(tab_id, str):
        return None
    parts = tab_id.split("|")
    if len(parts) != 3 or not all(parts):
        return None
    if not _is_number(parts[1]) or not _is_number(parts[2]):
        return None
    return parts[0], parts[1], parts[2]


def _is_number(value: str | None) -> bool:
    return bool(value) and value.isascii() and value.isdigit()


def _qdbus_text(executable: str, arguments: list[str]) -> str | None:
    result = _run_qdbus(executable, arguments, timeout=2, text=True)
    if result is None:
        return None
    return (result.stdout or "").strip()


def _current_session(executable: str, svc: str, win_id: str) -> str | None:
    value = _qdbus_text(
        executable,
        [svc, f"/Windows/{win_id}", "org.kde.konsole.Window.currentSession"],
    )
    return value if _is_number(value) else None


def _session_title(executable: str, svc: str, sess_id: str) -> str | None:
    return _qdbus_text(
        executable,
        [svc, f"/Sessions/{sess_id}", "org.kde.konsole.Session.title", "1"],
    ) or None


def _titled_windows(executable: str, svc: str, title: str) -> list[str]:
    listing = _qdbus_text(executable, [svc])
    if not listing:
        return []
    return [
        path
        for path in re.findall(r"^/konsole/MainWindow_\d+$", listing, re.MULTILINE)
        if _qdbus_text(
            executable, [svc, path, "org.qtproject.Qt.QWidget.windowTitle"]
        ) == title
    ]


def _window_is_active(executable: str, svc: str, path: str) -> bool:
    return _qdbus_text(
        executable, [svc, path, "org.qtproject.Qt.QWidget.isActiveWindow"]
    ) == "true"


def _titled_window_is_active(executable: str, svc: str, title: str) -> bool:
    """Require exactly one window of svc titled title, and that it is active.

    Konsole exposes no mapping from /Windows/N to its MainWindow object, so a
    second window with the same title makes activation unverifiable.
    """
    titled = _titled_windows(executable, svc, title)
    return len(titled) == 1 and _window_is_active(executable, svc, titled[0])


def _wait_for_active_target(
    executable: str, svc: str, win_id: str, sess_id: str, title: str
) -> bool:
    deadline = time.monotonic() + _ACTIVATION_SETTLE_SECONDS
    while True:
        if (
            _current_session(executable, svc, win_id) == sess_id
            and _titled_window_is_active(executable, svc, title)
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(_ACTIVATION_POLL_SECONDS)


def _activation_failure(
    executable: str, svc: str, win_id: str, sess_id: str, title: str
) -> str:
    settle = f"{_ACTIVATION_SETTLE_SECONDS:g}s"
    titled = _titled_windows(executable, svc, title)
    if len(titled) != 1:
        return (
            "no unique Konsole window matched the tab title "
            f"({len(titled)} found)"
        )
    if not _window_is_active(executable, svc, titled[0]):
        return f"window did not become active within {settle}"
    current = _current_session(executable, svc, win_id)
    if current != sess_id:
        return _current_tab_detail(current, sess_id)
    return f"window activation was not confirmed within {settle}"


def _kwin_activation_script(titles: list[str], owner_pid: int) -> str:
    return _KWIN_ACTIVATE_SCRIPT.replace(
        "__TITLES__", json.dumps(titles)
    ).replace("__OWNER__", json.dumps(owner_pid))


def _activate_by_kwin_caption(
    titles: list[str], owner_pid: int, executable: str
) -> bool:
    """Activate the single Konsole window of owner_pid showing one of titles."""
    script = _kwin_activation_script(titles, owner_pid)
    plugin = f"claude-fleet-focus-{uuid.uuid4().hex}"
    descriptor, path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(descriptor, "w") as script_file:
            script_file.write(script)
        loaded = _qdbus_text(
            executable,
            [
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                path,
                plugin,
            ],
        )
        if not _is_number(loaded):
            raise KonsoleFocusError("KWin script could not be loaded")
        ran = _run_qdbus(
            executable,
            [
                "org.kde.KWin",
                f"/Scripting/Script{loaded}",
                "org.kde.kwin.Script.run",
            ],
            timeout=5,
            text=False,
        )
        if ran is None:
            raise KonsoleFocusError("KWin script could not be run")
        return True
    finally:
        _run_qdbus(
            executable,
            [
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.unloadScript",
                plugin,
            ],
            timeout=5,
            text=False,
        )
        with contextlib.suppress(OSError):
            os.unlink(path)
