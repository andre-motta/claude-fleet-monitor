"""KDE Konsole terminal API via qdbus + KWin."""

import json
import os
import re
import time

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis._qdbus import (
    KWinScriptError,
    bus_owner_pid,
    is_number,
    qdbus_text,
    resolve_qdbus,
    run_kwin_script,
    run_qdbus,
)
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

_SERVICE_PREFIX = "org.kde.konsole"
_MAX_ANCESTORS = 64
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


def _nearest_owner_ancestor(pid: int, owners: set[int]) -> int | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return None
    visited = set()
    current = pid
    for _ in range(_MAX_ANCESTORS):
        if current in owners:
            return current
        if current <= 1 or current in visited:
            return None
        visited.add(current)
        try:
            process = discovery.get_process_info(current)
        except Exception:
            return None
        if process is None or process.ppid is None:
            return None
        current = process.ppid
    return None


class KonsoleFocusError(RuntimeError):
    """A failed Konsole focus step; the message is the user-facing detail."""


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

    def _find_service(
        self, pid: int, executable: str | None = None
    ) -> str | None:
        """Return the Konsole service owned by the nearest ancestor of pid.

        Each Konsole process owns its own org.kde.konsole-<pid> name, so the
        first listed name is only correct when a single Konsole runs.
        """
        if executable is None:
            executable = resolve_qdbus()
        result = run_qdbus(executable, [], timeout=5, text=True)
        if result is None:
            return None
        owners: dict[int, set[str]] = {}
        for line in (result.stdout or "").splitlines():
            name = line.strip()
            if not name.startswith(_SERVICE_PREFIX):
                continue
            owner = bus_owner_pid(executable, name)
            if owner is not None:
                owners.setdefault(owner, set()).add(name)
        if not owners:
            return None
        ancestor = _nearest_owner_ancestor(pid, set(owners))
        if ancestor is None or len(owners[ancestor]) != 1:
            return None
        return next(iter(owners[ancestor]))

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        executable = resolve_qdbus()
        if not executable:
            return None
        svc = terminal_env.get("KONSOLE_DBUS_SERVICE") or self._find_service(
            pid, executable
        )
        if not svc:
            return None

        sessions_result = run_qdbus(
            executable, [svc], timeout=5, text=True
        )
        if sessions_result is None:
            return None
        sessions_out = sessions_result.stdout or ""

        session_ids = re.findall(r"/Sessions/(\d+)", sessions_out)
        window_ids = re.findall(r"/Windows/(\d+)", sessions_out)

        for sess_id in session_ids:
            for prop in ("foregroundProcessId", "processId"):
                result = run_qdbus(
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
                        result = run_qdbus(
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
        selected = run_qdbus(
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
        current = run_qdbus(
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
        if current_id != sess_id and is_number(current_id):
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
        owner = bus_owner_pid(executable, svc)
        if owner is None:
            raise KonsoleFocusError(
                "Konsole D-Bus owner process could not be read"
            )
        _activate_by_kwin_caption(titles, owner, executable)
        self.raise_requested = True
        if _wait_for_active_target(
            executable, svc, win_id, sess_id, target_title
        ):
            return True
        raise KonsoleFocusError(
            _activation_failure(executable, svc, win_id, sess_id, target_title)
        )

    def verify_selection(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_tab_id(tab_id)
        executable = resolve_qdbus()
        if target is None or not executable:
            return False
        svc, win_id, sess_id = target
        return _current_session(executable, svc, win_id) == sess_id


def _require_qdbus() -> str:
    executable = resolve_qdbus()
    if not executable:
        raise KonsoleFocusError("qdbus is not available")
    return executable


def _current_tab_detail(current: str | None, expected: str) -> str:
    if not is_number(current):
        return f"Konsole did not report tab {expected} as current"
    return f"Konsole reports tab {current} current, not {expected}"


def _parse_tab_id(tab_id: str) -> tuple[str, str, str] | None:
    if not isinstance(tab_id, str):
        return None
    parts = tab_id.split("|")
    if len(parts) != 3 or not all(parts):
        return None
    if not is_number(parts[1]) or not is_number(parts[2]):
        return None
    return parts[0], parts[1], parts[2]


def _current_session(executable: str, svc: str, win_id: str) -> str | None:
    value = qdbus_text(
        executable,
        [svc, f"/Windows/{win_id}", "org.kde.konsole.Window.currentSession"],
    )
    return value if is_number(value) else None


def _session_title(executable: str, svc: str, sess_id: str) -> str | None:
    return qdbus_text(
        executable,
        [svc, f"/Sessions/{sess_id}", "org.kde.konsole.Session.title", "1"],
    ) or None


def _titled_windows(executable: str, svc: str, title: str) -> list[str]:
    listing = qdbus_text(executable, [svc])
    if not listing:
        return []
    return [
        path
        for path in re.findall(r"^/konsole/MainWindow_\d+$", listing, re.MULTILINE)
        if qdbus_text(
            executable, [svc, path, "org.qtproject.Qt.QWidget.windowTitle"]
        ) == title
    ]


def _window_is_active(executable: str, svc: str, path: str) -> bool:
    return qdbus_text(
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
    try:
        run_kwin_script(executable, script, "claude-fleet-focus")
    except KWinScriptError as error:
        raise KonsoleFocusError(str(error)) from None
    return True
