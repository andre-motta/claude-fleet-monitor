"""KDE Konsole terminal API via qdbus + KWin."""

import os
import re
import subprocess
import tempfile

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


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

    def _find_service(self) -> str | None:
        try:
            result = subprocess.run(
                ["qdbus"], capture_output=True, text=True, timeout=5
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        for line in result.stdout.strip().split("\n"):
            if "org.kde.konsole" in line:
                return line.strip()
        return None

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        svc = terminal_env.get("KONSOLE_DBUS_SERVICE") or self._find_service()
        if not svc:
            return None

        try:
            sessions_out = subprocess.run(
                ["qdbus", svc], capture_output=True, text=True, timeout=5
            ).stdout
        except subprocess.TimeoutExpired:
            return None

        session_ids = re.findall(r"/Sessions/(\d+)", sessions_out)
        window_ids = re.findall(r"/Windows/(\d+)", sessions_out)

        for sess_id in session_ids:
            for prop in ("foregroundProcessId", "processId"):
                try:
                    p = subprocess.run(
                        ["qdbus", svc, f"/Sessions/{sess_id}",
                         f"org.kde.konsole.Session.{prop}"],
                        capture_output=True, text=True, timeout=2
                    ).stdout.strip()
                except subprocess.TimeoutExpired:
                    continue
                if p == str(pid):
                    for win_id in window_ids:
                        try:
                            win_sessions = subprocess.run(
                                ["qdbus", svc, f"/Windows/{win_id}",
                                 "org.kde.konsole.Window.sessionList"],
                                capture_output=True, text=True, timeout=2
                            ).stdout.strip()
                        except subprocess.TimeoutExpired:
                            continue
                        if sess_id in win_sessions.split("\n"):
                            return f"{svc}|{win_id}|{sess_id}"
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        svc, win_id, sess_id = tab_id.split("|")
        try:
            subprocess.run(
                ["qdbus", svc, f"/Windows/{win_id}",
                 "org.kde.konsole.Window.setCurrentSession", sess_id],
                capture_output=True, timeout=2
            )
            return True
        except subprocess.TimeoutExpired:
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        svc, _, sess_id = tab_id.split("|")
        try:
            title = subprocess.run(
                ["qdbus", svc, f"/Sessions/{sess_id}",
                 "org.kde.konsole.Session.title", "1"],
                capture_output=True, text=True, timeout=2
            ).stdout.strip()
        except subprocess.TimeoutExpired:
            return False

        if not title:
            return False

        return self._raise_by_kwin_title(title)

    @staticmethod
    def _raise_by_kwin_title(title: str) -> bool:
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
                r = subprocess.run(
                    ["qdbus", "org.kde.KWin", "/Scripting",
                     "org.kde.kwin.Scripting.loadScript", f.name],
                    capture_output=True, text=True, timeout=5
                )
                sid = r.stdout.strip()
                if sid.isdigit():
                    subprocess.run(
                        ["qdbus", "org.kde.KWin", f"/Scripting/Script{sid}",
                         "org.kde.kwin.Script.run"],
                        capture_output=True, timeout=5
                    )
                    return True
            finally:
                os.unlink(f.name)
        return False
