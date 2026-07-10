"""Cross-platform window focus for Claude Fleet Monitor."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

FLEET_DIR = Path(os.environ.get("FLEET_DIR", Path.home() / ".claude" / "fleet"))


def find_session(query):
    if not FLEET_DIR.exists():
        return None

    hook_matches = []
    proc_matches = []

    for f in FLEET_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        sid = data.get("session_id", "")
        repo = data.get("repo", "")
        if query in sid or query in repo:
            if f.name.startswith("proc-"):
                proc_matches.append(data)
            else:
                hook_matches.append(data)

    matches = hook_matches if hook_matches else proc_matches

    if not matches:
        print(f"No session matching '{query}'", file=sys.stderr)
        return None
    if len(matches) == 1:
        return matches[0]

    print(f"Multiple sessions match '{query}':", file=sys.stderr)
    for m in matches:
        print(f"  {m.get('repo', '?')} ({m['session_id']})", file=sys.stderr)
    return None


def get_pid(session):
    sid = session.get("session_id", "")
    stored_pid = session.get("pid", "")

    if sid.startswith("proc-"):
        return int(sid[5:])

    if stored_pid:
        try:
            pid = int(stored_pid)
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            pass

    cwd = session.get("cwd", "")
    if not cwd:
        return None

    try:
        result = subprocess.run(
            ["pgrep", "-x", "claude"], capture_output=True, text=True
        )
        for pid_str in result.stdout.strip().split("\n"):
            if not pid_str:
                continue
            pid = int(pid_str)
            try:
                pcwd = os.readlink(f"/proc/{pid}/cwd")
                cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
            except OSError:
                continue
            if any(s in cmdline for s in ("daemon", "bg-pty", "bg-spare")):
                continue
            if pcwd == cwd:
                return pid
    except FileNotFoundError:
        pass

    return None


def _focus_konsole(pid):
    try:
        result = subprocess.run(
            ["qdbus"], capture_output=True, text=True, timeout=5
        )
    except FileNotFoundError:
        return False

    for line in result.stdout.strip().split("\n"):
        svc = line.strip()
        if "org.kde.konsole" not in svc:
            continue

        try:
            sessions_out = subprocess.run(
                ["qdbus", svc], capture_output=True, text=True, timeout=5
            ).stdout
        except subprocess.TimeoutExpired:
            continue

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
                            subprocess.run(
                                ["qdbus", svc, f"/Windows/{win_id}",
                                 "org.kde.konsole.Window.setCurrentSession", sess_id],
                                capture_output=True, timeout=2
                            )

                            title = subprocess.run(
                                ["qdbus", svc, f"/Sessions/{sess_id}",
                                 "org.kde.konsole.Session.title", "1"],
                                capture_output=True, text=True, timeout=2
                            ).stdout.strip()
                            if title:
                                _raise_by_title_kwin(title)

                            print(f"Focused Konsole session {sess_id} (PID {pid})")
                            return True
    return False


def _raise_by_title_kwin(title):
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
    import tempfile
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
        finally:
            os.unlink(f.name)


def _focus_pywinctl(title):
    try:
        import pywinctl
    except ImportError:
        return False

    wins = pywinctl.getWindowsWithTitle(title)
    if wins:
        wins[0].activate()
        return True
    return False


def _focus_osascript(title):
    if sys.platform != "darwin":
        return False
    safe = title.replace('"', '\\"')
    script = f'''
tell application "System Events"
    repeat with proc in (every process whose background only is false)
        repeat with w in (every window of proc)
            if name of w contains "{safe}" then
                set frontmost of proc to true
                perform action "AXRaise" of w
                return
            end if
        end repeat
    end repeat
end tell
'''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def focus(query):
    session = find_session(query)
    if not session:
        return False

    pid = get_pid(session)
    repo = session.get("repo", "?")

    if not pid:
        print(f"Session '{repo}' has no PID", file=sys.stderr)
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        print(f"PID {pid} is no longer running", file=sys.stderr)
        return False

    if _focus_konsole(pid):
        return True

    title = repo
    if _focus_pywinctl(title):
        print(f"Focused window: {title}")
        return True

    if _focus_osascript(title):
        print(f"Focused window: {title}")
        return True

    print(f"Could not find terminal window for PID {pid} ({repo})", file=sys.stderr)
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: claude-fleet focus <session-id-or-repo>", file=sys.stderr)
        sys.exit(1)
    if not focus(sys.argv[1]):
        sys.exit(1)


if __name__ == "__main__":
    main()
