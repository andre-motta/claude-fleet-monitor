"""Typed data models for fleet sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


class SessionStatus(Enum):
    STARTED = "started"
    RUNNING = "running"
    IDLE = "idle"
    WAITING = "waiting"
    ERROR = "error"
    ENDED = "ended"
    DISCOVERED = "discovered"


STATUS_PRIORITY = {
    SessionStatus.WAITING: 0,
    SessionStatus.ERROR: 1,
    SessionStatus.RUNNING: 2,
    SessionStatus.STARTED: 3,
    SessionStatus.IDLE: 4,
    SessionStatus.DISCOVERED: 5,
    SessionStatus.ENDED: 6,
}

SORT_KEYS = ["attention", "status", "age", "repo"]


@dataclass(frozen=True)
class FleetSession:
    session_id: str
    repo: str
    cwd: str
    status: SessionStatus
    detail: str
    ts: int
    started: int | None
    pid: str
    terminal: str
    terminal_env: dict[str, str]
    source: str
    tool: str
    age_seconds: int = 0
    needs_attention: bool = False

    def summary_line(self) -> str:
        return (
            f"{self.repo} | {self.status.value.upper()} | "
            f"{self.detail} | {format_age(self.age_seconds)} | PID {self.pid}"
        )

    def to_json(self) -> str:
        return json.dumps({
            "session_id": self.session_id,
            "repo": self.repo,
            "cwd": self.cwd,
            "status": self.status.value,
            "detail": self.detail,
            "ts": self.ts,
            "started": self.started,
            "pid": self.pid,
            "terminal": self.terminal,
            "tool": self.tool,
            "source": self.source,
            "age_seconds": self.age_seconds,
            "needs_attention": self.needs_attention,
        }, indent=2)


def parse_session(data: dict) -> FleetSession:
    try:
        status = SessionStatus(data.get("status", "discovered"))
    except ValueError:
        status = SessionStatus.DISCOVERED

    return FleetSession(
        session_id=data.get("session_id", ""),
        repo=data.get("repo", ""),
        cwd=data.get("cwd", ""),
        status=status,
        detail=data.get("detail", ""),
        ts=data.get("ts", 0),
        started=data.get("started"),
        pid=str(data.get("pid", "")),
        terminal=data.get("terminal", ""),
        terminal_env=data.get("terminal_env", {}),
        source=data.get("source", "hook"),
        tool=data.get("tool", ""),
        age_seconds=data.get("age_seconds", 0),
        needs_attention=data.get("needs_attention", False),
    )


def format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{seconds % 3600 // 60}m"


def sort_sessions(
    sessions: list[FleetSession], key: str = "repo"
) -> list[FleetSession]:
    if key == "attention":
        return sorted(sessions, key=lambda s: (not s.needs_attention, STATUS_PRIORITY.get(s.status, 9), s.repo.lower()))
    elif key == "status":
        return sorted(sessions, key=lambda s: (STATUS_PRIORITY.get(s.status, 9), s.repo.lower()))
    elif key == "age":
        return sorted(sessions, key=lambda s: -s.age_seconds)
    else:
        return sorted(sessions, key=lambda s: s.repo.lower())
