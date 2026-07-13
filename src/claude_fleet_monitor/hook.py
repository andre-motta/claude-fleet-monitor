"""Claude Code hook handler - writes session status to fleet directory."""

import json
import os
import sys
import time
from pathlib import Path

FLEET_DIR = Path(os.environ.get("FLEET_DIR", Path.home() / ".claude" / "fleet"))


def _find_claude_pid():
    """Walk up the process tree to find the parent claude process."""
    pid = os.getpid()
    while pid > 1:
        try:
            if sys.platform == "linux":
                cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
            else:
                import subprocess
                cmdline = subprocess.run(
                    ["ps", "-o", "args=", "-p", str(pid)],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
        except (OSError, Exception):
            break

        if "claude" in cmdline and "fleet-hook" not in cmdline and "hook.py" not in cmdline:
            if "daemon" not in cmdline and "bg-pty" not in cmdline:
                return str(pid)

        try:
            if sys.platform == "linux":
                stat = Path(f"/proc/{pid}/stat").read_text()
                pid = int(stat.split(") ")[1].split()[1])
            else:
                import subprocess
                ppid = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(pid)],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                pid = int(ppid) if ppid else 0
        except (OSError, ValueError, Exception):
            break

    return ""


def _read_status(path):
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_status(path, data):
    path.write_text(json.dumps(data))


def _cleanup_stale_proc():
    for f in FLEET_DIR.glob("proc-*.json"):
        try:
            pid = int(f.stem.replace("proc-", ""))
            os.kill(pid, 0)
        except (ValueError, OSError):
            f.unlink(missing_ok=True)


def handle(event):
    FLEET_DIR.mkdir(parents=True, exist_ok=True)

    stdin_data = json.loads(sys.stdin.read())
    session_id = stdin_data.get("session_id", "unknown")
    cwd = stdin_data.get("cwd", "unknown")
    tool_name = stdin_data.get("tool_name", "")
    last_msg = stdin_data.get("last_assistant_message", "")

    repo = os.path.basename(cwd)
    status_file = FLEET_DIR / f"{session_id}.json"
    now = int(time.time())
    claude_pid = _find_claude_pid()

    if event == "session-start":
        _cleanup_stale_proc()
        from claude_fleet_monitor.terminal_apis import capture_terminal_info
        term_info = capture_terminal_info()
        _write_status(status_file, {
            "session_id": session_id, "repo": repo, "cwd": cwd,
            "pid": claude_pid, "status": "started",
            "detail": "session started", "ts": now, "started": now,
            "terminal": term_info["terminal"],
            "terminal_env": term_info["terminal_env"],
        })

    elif event == "prompt-submit":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "running"
            existing["detail"] = "processing prompt"
            existing["ts"] = now
            if not existing.get("pid"):
                existing["pid"] = claude_pid
            _write_status(status_file, existing)
        else:
            from claude_fleet_monitor.terminal_apis import capture_terminal_info
            term_info = capture_terminal_info()
            _write_status(status_file, {
                "session_id": session_id, "repo": repo, "cwd": cwd,
                "pid": claude_pid, "status": "running",
                "detail": "processing prompt", "ts": now, "started": now,
                "terminal": term_info["terminal"],
                "terminal_env": term_info["terminal_env"],
            })

    elif event == "tool-use":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "running"
            existing["detail"] = f"using {tool_name or 'tool'}"
            existing["tool"] = tool_name
            existing["ts"] = now
            if not existing.get("pid"):
                existing["pid"] = claude_pid
            _write_status(status_file, existing)

    elif event == "stop":
        existing = _read_status(status_file)
        if existing:
            summary = (last_msg or "finished").replace("\n", " ").replace("\r", "")[:120]
            if len(last_msg or "") > 120:
                summary += "..."
            existing["status"] = "idle"
            existing["detail"] = summary
            existing["tool"] = ""
            existing["ts"] = now
            _write_status(status_file, existing)

    elif event == "stop-failure":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "error"
            existing["detail"] = "turn failed (API error)"
            existing["tool"] = ""
            existing["ts"] = now
            _write_status(status_file, existing)

    elif event == "permission-request":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "waiting"
            existing["detail"] = f"permission needed: {tool_name or 'tool'}"
            existing["tool"] = tool_name
            existing["ts"] = now
            _write_status(status_file, existing)

    elif event == "elicitation":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "waiting"
            existing["detail"] = "waiting for user input"
            existing["tool"] = ""
            existing["ts"] = now
            _write_status(status_file, existing)

    elif event == "session-end":
        existing = _read_status(status_file)
        if existing:
            existing["status"] = "ended"
            existing["detail"] = "session closed"
            existing["tool"] = ""
            existing["ts"] = now
            _write_status(status_file, existing)


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    handle(sys.argv[1])


if __name__ == "__main__":
    main()
