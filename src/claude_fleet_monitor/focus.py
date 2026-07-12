"""Cross-platform window focus for Claude Fleet Monitor."""

import json
import os
import subprocess
import sys
from pathlib import Path

from claude_fleet_monitor.terminal_apis import get_terminal_api

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

    terminal_type = session.get("terminal", "generic")
    terminal_env = session.get("terminal_env", {})
    api = get_terminal_api(terminal_type)

    if api.focus(pid, terminal_env):
        print(f"Focused {repo} via {api.name} (PID {pid})")
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
