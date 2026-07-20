"""Typed data models for fleet sessions."""

from __future__ import annotations

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
