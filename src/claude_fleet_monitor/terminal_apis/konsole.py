"""KDE Konsole terminal API via qdbus + KWin."""

import os
import re
import shutil
import subprocess
import tempfile

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

_QDBUS_CANDIDATES = ("qdbus", "qdbus6", "qdbus-qt6")


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
        parts = tab_id.split("|")
        if len(parts) != 3 or not all(parts):
            return False
        executable = _resolve_qdbus()
        if not executable:
            return False
        svc, win_id, sess_id = parts
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
            return False
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
        return current is not None and (current.stdout or "").strip() == sess_id

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        parts = tab_id.split("|")
        if len(parts) != 3 or not all(parts):
            return False
        executable = _resolve_qdbus()
        if not executable:
            return False
        svc, _, sess_id = parts
        result = _run_qdbus(
            executable,
            [
                svc,
                f"/Sessions/{sess_id}",
                "org.kde.konsole.Session.title",
                "1",
            ],
            timeout=2,
            text=True,
        )
        if result is None:
            return False
        title = (result.stdout or "").strip()

        if not title:
            return False

        return self._raise_by_kwin_title(title, executable)

    @staticmethod
    def _raise_by_kwin_title(
        title: str, executable: str | None = None
    ) -> bool:
        if executable is None:
            executable = _resolve_qdbus()
        if not executable:
            return False
        safe = title.replace("'", "\\'")
        script = f"""
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {{
    if (windows[i].caption.indexOf('{safe}') !== -1) {{
        workspace.activeWindow = windows[i];
        break;
    }}
}}
"""
        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write(script)
            f.flush()
            try:
                result = _run_qdbus(
                    executable,
                    [
                        "org.kde.KWin",
                        "/Scripting",
                        "org.kde.kwin.Scripting.loadScript",
                        f.name,
                    ],
                    timeout=5,
                    text=True,
                )
                if result is None:
                    return False
                sid = (result.stdout or "").strip()
                if sid.isdigit():
                    _run_qdbus(
                        executable,
                        [
                            "org.kde.KWin",
                            f"/Scripting/Script{sid}",
                            "org.kde.kwin.Script.run",
                        ],
                        timeout=5,
                        text=False,
                    )
            finally:
                os.unlink(f.name)
        return False
