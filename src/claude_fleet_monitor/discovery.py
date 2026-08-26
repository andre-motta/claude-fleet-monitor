"""Cross-platform process discovery and fleet session reading."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

FLEET_DIR = Path(os.environ.get("FLEET_DIR", Path.home() / ".claude" / "fleet"))


def _get_process_info(pid):
    """Get cwd and cmdline for a process, cross-platform."""
    cwd = None
    cmdline = ""

    if sys.platform == "linux":
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
        except OSError:
            return None, None
    elif sys.platform == "darwin":
        try:
            cwd = subprocess.run(
                ["lsof", "-p", str(pid), "-Fn", "-a", "-d", "cwd"],
                capture_output=True, text=True, timeout=5
            ).stdout
            for line in cwd.strip().split("\n"):
                if line.startswith("n"):
                    cwd = line[1:]
                    break
            else:
                cwd = None
            cmdline = subprocess.run(
                ["ps", "-o", "args=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None, None
    else:
        try:
            cmdline = subprocess.run(
                ["ps", "-o", "args=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None, None

    return cwd, cmdline


def _get_tty(pid):
    """Get the tty for a process, Linux-only."""
    if sys.platform != "linux":
        return ""
    try:
        link = os.readlink(f"/proc/{pid}/fd/0")
        match = re.search(r"pts/\d+", link)
        return match.group() if match else ""
    except OSError:
        return ""


def _find_agent_processes():
    """Find running Claude Code and Codex processes, cross-platform."""
    try:
        if sys.platform == "win32":
            processes = []
            for agent in ("claude", "codex"):
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {agent}.exe", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split("\n"):
                    parts = line.strip().strip('"').split('","')
                    if len(parts) >= 2 and parts[0].lower() == f"{agent}.exe":
                        processes.append((agent, int(parts[1])))
            return processes
        else:
            processes = []
            for agent in ("claude", "codex"):
                result = subprocess.run(
                    ["pgrep", "-x", agent], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    processes.extend(
                        (agent, int(pid))
                        for pid in result.stdout.strip().split("\n") if pid
                    )
            return processes
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def discover_processes():
    """Create status files for agent processes not yet reported by hooks."""
    processes = _find_agent_processes()
    if not processes:
        return

    now = int(time.time())
    FLEET_DIR.mkdir(parents=True, exist_ok=True)

    for agent, pid in processes:
        proc_file = FLEET_DIR / f"proc-{pid}.json"
        if proc_file.exists():
            continue

        cwd, cmdline = _get_process_info(pid)
        if not cwd or not cmdline:
            continue

        if any(skip in cmdline for skip in ("daemon", "bg-pty", "bg-spare")):
            continue

        repo = os.path.basename(cwd)
        tty = _get_tty(pid)

        proc_file.write_text(
            json.dumps(
                {
                    "session_id": f"proc-{pid}",
                    "agent": agent,
                    "repo": repo,
                    "cwd": cwd,
                    "status": "discovered",
                    "detail": f"PID {pid} {tty}".strip(),
                    "ts": now,
                    "started": now,
                    "source": "process",
                }
            )
        )

    # Clean dead proc files
    for f in FLEET_DIR.glob("proc-*.json"):
        pid_match = re.search(r"proc-(\d+)", f.name)
        if pid_match:
            pid = int(pid_match.group(1))
            try:
                os.kill(pid, 0)
            except OSError:
                f.unlink(missing_ok=True)


def _is_pid_alive(pid_str):
    if not pid_str:
        return False
    try:
        os.kill(int(pid_str), 0)
        return True
    except (OSError, ValueError):
        return False


def _cleanup_stale_sessions():
    """Remove session files with dead or missing PIDs."""
    if not FLEET_DIR.exists():
        return
    now = int(time.time())
    for f in FLEET_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        pid = data.get("pid", "")
        status = data.get("status", "")
        ts = data.get("ts", now)
        age = now - ts

        if status == "ended" and age > 300:
            f.unlink(missing_ok=True)
        elif pid and not _is_pid_alive(pid):
            f.unlink(missing_ok=True)
        elif not pid and age > 600:
            f.unlink(missing_ok=True)


def read_sessions():
    """Read all fleet session files, deduplicating proc-discovered vs hook-based."""
    discover_processes()
    _cleanup_stale_sessions()
    if not FLEET_DIR.exists():
        return []

    hook_sessions = set()
    all_sessions = []
    for f in FLEET_DIR.glob("*.json"):
        if f.name.startswith("proc-"):
            continue
        try:
            data = json.loads(f.read_text())
            hook_sessions.add((data.get("agent", "claude"), data.get("cwd", "")))
            all_sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    for f in FLEET_DIR.glob("proc-*.json"):
        try:
            data = json.loads(f.read_text())
            identity = (data.get("agent", "claude"), data.get("cwd", ""))
            if identity not in hook_sessions:
                all_sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    # Deduplicate: if multiple hook sessions share a PID, keep newest
    seen_pids = {}
    deduped = []
    for s in all_sessions:
        pid = s.get("pid", "")
        if pid:
            if pid in seen_pids:
                prev = seen_pids[pid]
                if s.get("ts", 0) > prev.get("ts", 0):
                    deduped.remove(prev)
                    seen_pids[pid] = s
                    deduped.append(s)
            else:
                seen_pids[pid] = s
                deduped.append(s)
        else:
            deduped.append(s)
    all_sessions = deduped

    now = int(time.time())
    for s in all_sessions:
        s["age_seconds"] = now - s.get("ts", now)
        status = s.get("status", "")
        s["needs_attention"] = status == "waiting" or (status == "idle" and s["age_seconds"] > 120)

    all_sessions.sort(key=lambda s: s.get("repo", ""))
    return all_sessions
