import json
import os
import re
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

FLEET_DIR = Path.home() / ".claude" / "fleet"

mcp = FastMCP("claude-fleet")


def discover_processes():
    try:
        result = subprocess.run(
            ["pgrep", "-x", "claude"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return
    except FileNotFoundError:
        return

    now = int(time.time())
    for pid_str in result.stdout.strip().split("\n"):
        if not pid_str:
            continue
        pid = int(pid_str)
        if (FLEET_DIR / f"proc-{pid}.json").exists():
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
        except OSError:
            continue

        if any(skip in cmdline for skip in ("daemon", "bg-pty", "bg-spare")):
            continue

        repo = os.path.basename(cwd)
        FLEET_DIR.mkdir(parents=True, exist_ok=True)
        status_file = FLEET_DIR / f"proc-{pid}.json"
        status_file.write_text(
            json.dumps(
                {
                    "session_id": f"proc-{pid}",
                    "repo": repo,
                    "cwd": cwd,
                    "status": "discovered",
                    "detail": f"PID {pid}",
                    "ts": now,
                    "started": now,
                    "source": "process",
                }
            )
        )

    if FLEET_DIR.exists():
        for f in FLEET_DIR.glob("proc-*.json"):
            pid_match = re.search(r"proc-(\d+)", f.name)
            if pid_match:
                pid = int(pid_match.group(1))
                try:
                    os.kill(pid, 0)
                except OSError:
                    f.unlink(missing_ok=True)


def read_sessions():
    discover_processes()
    if not FLEET_DIR.exists():
        return []

    hook_cwds = set()
    all_sessions = []
    for f in FLEET_DIR.glob("*.json"):
        if f.name.startswith("proc-"):
            continue
        try:
            data = json.loads(f.read_text())
            hook_cwds.add(data.get("cwd", ""))
            all_sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    for f in FLEET_DIR.glob("proc-*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("cwd", "") not in hook_cwds:
                all_sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    now = int(time.time())
    for s in all_sessions:
        s["age_seconds"] = now - s.get("ts", now)
        s["needs_attention"] = s.get("status") == "idle" and s["age_seconds"] > 120

    all_sessions.sort(key=lambda s: s.get("ts", 0), reverse=True)
    return all_sessions


@mcp.tool()
def fleet_status() -> str:
    """Get status of all Claude Code sessions. Returns repo, status, detail, and whether each session needs attention."""
    sessions = read_sessions()
    if not sessions:
        return json.dumps({"sessions": [], "summary": "No active sessions"})

    active = sum(1 for s in sessions if s["status"] in ("running", "started"))
    idle = sum(1 for s in sessions if s["status"] == "idle")
    attention = sum(1 for s in sessions if s["needs_attention"])

    return json.dumps(
        {
            "sessions": sessions,
            "summary": {
                "total": len(sessions),
                "active": active,
                "idle": idle,
                "needs_attention": attention,
            },
        },
        indent=2,
    )


@mcp.tool()
def fleet_session(session_id: str) -> str:
    """Get detailed status for a specific session by ID (full or prefix match)."""
    sessions = read_sessions()
    matches = [s for s in sessions if s.get("session_id", "").startswith(session_id)]
    if not matches:
        return json.dumps({"error": f"No session matching '{session_id}'"})
    return json.dumps(matches[0], indent=2)


@mcp.tool()
def fleet_sessions_needing_attention() -> str:
    """Get sessions that are idle for over 2 minutes and likely need user input."""
    sessions = read_sessions()
    attention = [s for s in sessions if s["needs_attention"]]
    if not attention:
        return json.dumps({"message": "All sessions healthy", "sessions": []})
    return json.dumps(
        {
            "message": f"{len(attention)} session(s) may need input",
            "sessions": attention,
        },
        indent=2,
    )


@mcp.tool()
def fleet_focus(query: str) -> str:
    """Focus the terminal window/tab running a Claude session. Accepts repo name, session ID, or PID. On Konsole, switches to the exact tab. On other terminals, raises the window."""
    focus_script = Path.home() / ".claude" / "bin" / "fleet-focus.sh"
    if not focus_script.exists():
        return json.dumps({"error": "fleet-focus.sh not found"})
    try:
        result = subprocess.run(
            [str(focus_script), query],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.dumps(
                {"success": True, "message": result.stdout.strip()}
            )
        return json.dumps(
            {"success": False, "error": result.stderr.strip()}
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Focus command timed out"})


@mcp.tool()
def fleet_cleanup() -> str:
    """Remove status files for ended sessions older than 5 minutes."""
    if not FLEET_DIR.exists():
        return json.dumps({"removed": 0})
    now = int(time.time())
    removed = 0
    for f in FLEET_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if data.get("status") == "ended" and (now - data.get("ts", now)) > 300:
                f.unlink()
                removed += 1
        except (json.JSONDecodeError, OSError):
            continue
    return json.dumps({"removed": removed})


def main():
    mcp.run()


if __name__ == "__main__":
    main()
