"""Curses-based TUI for Claude Fleet Monitor."""

import curses
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

FLEET_DIR = Path(os.environ.get("FLEET_DIR", Path.home() / ".claude" / "fleet"))
FOCUS_SCRIPT = Path.home() / ".claude" / "bin" / "fleet-focus.sh"

STATUS_COLORS = {
    "running": 2,
    "idle": 3,
    "started": 6,
    "error": 1,
    "ended": 8,
    "discovered": 5,
}

STATUS_ICONS = {
    "running": "*",
    "idle": "=",
    "started": ">",
    "error": "x",
    "ended": "-",
    "discovered": "+",
}


def format_age(seconds):
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{seconds % 3600 // 60}m"


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
        proc_file = FLEET_DIR / f"proc-{pid}.json"
        if proc_file.exists():
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
        tty = ""
        try:
            link = os.readlink(f"/proc/{pid}/fd/0")
            match = re.search(r"pts/\d+", link)
            if match:
                tty = match.group()
        except OSError:
            pass

        proc_file.write_text(
            json.dumps(
                {
                    "session_id": f"proc-{pid}",
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

    all_sessions.sort(key=lambda s: s.get("repo", ""))
    return all_sessions


def focus_session(session):
    import threading
    import io
    from claude_fleet_monitor.focus import focus

    def _focus_silent(sid):
        import sys as _sys
        old_stdout, old_stderr = _sys.stdout, _sys.stderr
        _sys.stdout = io.StringIO()
        _sys.stderr = io.StringIO()
        try:
            focus(sid)
        finally:
            _sys.stdout = old_stdout
            _sys.stderr = old_stderr

    sid = session.get("session_id", "")
    threading.Thread(target=_focus_silent, args=(sid,), daemon=True).start()


def notify_idle(sessions, notified):
    if not shutil.which("notify-send"):
        return
    for s in sessions:
        sid = s.get("session_id", "")
        if s.get("needs_attention") and sid not in notified:
            notified.add(sid)
            repo = s.get("repo", "?")
            age = format_age(s.get("age_seconds", 0))
            subprocess.Popen(
                [
                    "notify-send",
                    "-u", "normal",
                    "-a", "Claude Fleet",
                    "Session needs input",
                    f"{repo} idle for {age}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif not s.get("needs_attention") and sid in notified:
            notified.discard(sid)


def run_tui(stdscr, refresh_interval):
    curses.curs_set(0)
    curses.use_default_colors()
    for i in range(1, 9):
        curses.init_pair(i, i, -1)
    curses.init_pair(8, 8, -1)
    curses.init_pair(9, 0, 4)
    curses.init_pair(10, 0, 6)

    stdscr.timeout(refresh_interval * 1000)

    selected = 0
    notified = set()
    message = ""
    message_time = 0

    while True:
        sessions = read_sessions()
        notify_idle(sessions, notified)

        if selected >= len(sessions):
            selected = max(0, len(sessions) - 1)

        stdscr.erase()
        h, w = stdscr.getmaxyx()

        active = sum(1 for s in sessions if s["status"] in ("running", "started"))
        idle = sum(1 for s in sessions if s["status"] == "idle")
        attention = sum(1 for s in sessions if s.get("needs_attention"))

        title = f" Claude Fleet Monitor "
        summary = f" {len(sessions)} sessions | {active} active | {idle} idle "
        if attention:
            summary += f"| {attention} need input "

        try:
            stdscr.addstr(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
            stdscr.addstr(0, len(title), summary, curses.A_DIM)
        except curses.error:
            pass

        col_icon = 1
        col_repo = 3
        col_status = 30
        col_detail = 43
        col_age = w - 8

        header_y = 2
        try:
            stdscr.addstr(header_y, col_repo, "REPO", curses.A_DIM)
            stdscr.addstr(header_y, col_status, "STATUS", curses.A_DIM)
            stdscr.addstr(header_y, col_detail, "DETAIL", curses.A_DIM)
            stdscr.addstr(header_y, col_age, "AGE", curses.A_DIM)
            stdscr.addstr(header_y + 1, 1, "-" * (w - 2), curses.A_DIM)
        except curses.error:
            pass

        visible_start = 0
        max_rows = h - 7
        if max_rows < 1:
            max_rows = 1
        if selected >= visible_start + max_rows:
            visible_start = selected - max_rows + 1
        if selected < visible_start:
            visible_start = selected

        for idx in range(visible_start, min(len(sessions), visible_start + max_rows)):
            s = sessions[idx]
            y = 4 + idx - visible_start
            if y >= h - 2:
                break

            status = s.get("status", "?")
            repo = s.get("repo", "?")[:25]
            detail = s.get("detail", "")
            age_str = format_age(s.get("age_seconds", 0))
            icon = STATUS_ICONS.get(status, "?")
            color_pair = STATUS_COLORS.get(status, 8)

            is_selected = idx == selected
            detail_max = max(10, col_age - col_detail - 1)
            if len(detail) > detail_max:
                detail = detail[:detail_max - 3] + "..."

            try:
                if is_selected:
                    stdscr.addstr(y, 0, " " * (w - 1), curses.A_REVERSE)
                    stdscr.addstr(y, col_icon, icon, curses.color_pair(color_pair) | curses.A_REVERSE)
                    stdscr.addstr(y, col_repo, repo, curses.A_BOLD | curses.A_REVERSE)
                    stdscr.addstr(y, col_status, status.upper(), curses.color_pair(color_pair) | curses.A_REVERSE)
                    stdscr.addstr(y, col_detail, detail, curses.A_REVERSE)
                    stdscr.addstr(y, col_age, age_str, curses.A_DIM | curses.A_REVERSE)
                else:
                    stdscr.addstr(y, col_icon, icon, curses.color_pair(color_pair))
                    stdscr.addstr(y, col_repo, repo, curses.A_BOLD)
                    stdscr.addstr(y, col_status, status.upper(), curses.color_pair(color_pair))
                    stdscr.addstr(y, col_detail, detail)
                    stdscr.addstr(y, col_age, age_str, curses.A_DIM)

                if s.get("needs_attention"):
                    stdscr.addstr(y, 0, "!", curses.color_pair(3) | curses.A_BOLD | (curses.A_REVERSE if is_selected else 0))
            except curses.error:
                pass

        footer_y = h - 1
        now = time.time()
        if message and now - message_time < 3:
            footer_text = message
        else:
            message = ""
            footer_text = " [arrows] navigate  [enter] focus  [r] refresh  [q] quit "

        try:
            footer_line = footer_text[:w - 1].ljust(w - 1)
            stdscr.addstr(footer_y, 0, footer_line, curses.A_DIM | curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()
        if key == ord("q") or key == 27:
            break
        elif key == curses.KEY_UP or key == ord("k"):
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN or key == ord("j"):
            selected = min(len(sessions) - 1, selected + 1)
        elif key == curses.KEY_HOME:
            selected = 0
        elif key == curses.KEY_END:
            selected = max(0, len(sessions) - 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if sessions:
                s = sessions[selected]
                focus_session(s)
                repo = s.get("repo", "?")
                message = f" Focused: {repo} "
                message_time = time.time()
        elif key == ord("r"):
            message = " Refreshed "
            message_time = time.time()


def main(refresh=2):
    curses.wrapper(lambda stdscr: run_tui(stdscr, refresh))
