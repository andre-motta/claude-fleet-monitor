"""Typed data models for fleet sessions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from dataclasses import field
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

SCHEMA_VERSION = 1
UNRESOLVED_INSTANCE_ID = "unresolved"


class FocusTargetKind(Enum):
    TERMINAL = "terminal"
    DESKTOP = "desktop"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FocusTarget:
    kind: FocusTargetKind
    terminal: str = ""
    terminal_env: dict[str, str] = field(default_factory=dict)
    desktop_target: str = ""


@dataclass(frozen=True)
class FocusOperation:
    attempted: bool
    succeeded: bool
    detail: str = ""

    @classmethod
    def unavailable(cls, detail: str) -> "FocusOperation":
        return cls(attempted=False, succeeded=False, detail=detail)


@dataclass(frozen=True)
class FocusResult:
    state: str
    reason: str
    backend: str = ""
    pid: int | None = None
    target_found: bool = False
    selection: FocusOperation = field(
        default_factory=lambda: FocusOperation.unavailable("not attempted")
    )
    activation: FocusOperation = field(
        default_factory=lambda: FocusOperation.unavailable("not attempted")
    )

    @property
    def successful(self) -> bool:
        return self.selection.succeeded or self.activation.succeeded

    @property
    def complete(self) -> bool:
        return (
            self.target_found
            and self.selection.succeeded
            and self.activation.succeeded
        )

    def __bool__(self) -> bool:
        return self.successful

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "backend": self.backend,
            "pid": self.pid,
            "target_found": self.target_found,
            "selection": {
                "attempted": self.selection.attempted,
                "succeeded": self.selection.succeeded,
                "detail": self.selection.detail,
            },
            "activation": {
                "attempted": self.activation.attempted,
                "succeeded": self.activation.succeeded,
                "detail": self.activation.detail,
            },
            "successful": self.successful,
            "complete": self.complete,
        }


def canonical_session_id(
    harness_id: str, session_id: str, instance_id: str
) -> str:
    identity = json.dumps(
        [harness_id, session_id, instance_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return f"fleet:v{SCHEMA_VERSION}:{harness_id}:{digest}"


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
    agent: str = "claude"
    canonical_id: str = ""
    instance_id: str = ""
    schema_version: int = 0
    sequence: int | None = None
    process_start: str = ""
    process_identity: str = ""
    focus_target: FocusTarget = field(
        default_factory=lambda: FocusTarget(FocusTargetKind.UNAVAILABLE)
    )

    def summary_line(self) -> str:
        return (
            f"{self.agent} | {self.repo} | {self.status.value.upper()} | "
            f"{self.detail} | {format_age(self.age_seconds)} | PID {self.pid}"
        )

    @property
    def identity(self) -> str:
        return self.canonical_id or self.session_id

    def to_json(self) -> str:
        return json.dumps({
            "session_id": self.session_id,
            "canonical_id": self.canonical_id,
            "instance_id": self.instance_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "harness_id": self.agent,
            "agent": self.agent,
            "repo": self.repo,
            "cwd": self.cwd,
            "status": self.status.value,
            "detail": self.detail,
            "ts": self.ts,
            "started": self.started,
            "pid": self.pid,
            "terminal": self.terminal,
            "terminal_env": self.terminal_env,
            "tool": self.tool,
            "source": self.source,
            "age_seconds": self.age_seconds,
            "needs_attention": self.needs_attention,
            "process_start": self.process_start,
            "process_identity": self.process_identity,
            "focus_target": {
                "kind": self.focus_target.kind.value,
                "terminal": self.focus_target.terminal,
                "terminal_env": self.focus_target.terminal_env,
                "desktop_target": self.focus_target.desktop_target,
            },
        }, indent=2)


def parse_session(data: dict) -> FleetSession:
    try:
        status = SessionStatus(data.get("status", "discovered"))
    except ValueError:
        status = SessionStatus.DISCOVERED

    agent = data.get("harness_id", data.get("agent", "claude"))
    terminal = data.get("terminal", "")
    target_data = data.get("focus_target", {})
    if not isinstance(target_data, dict):
        target_data = {}
    kind_value = target_data.get("kind")
    if not kind_value:
        kind_value = "terminal" if terminal else "unavailable"
    try:
        target_kind = FocusTargetKind(kind_value)
    except ValueError:
        target_kind = FocusTargetKind.UNAVAILABLE
    target = FocusTarget(
        kind=target_kind,
        terminal=target_data.get("terminal", terminal),
        terminal_env=target_data.get(
            "terminal_env", data.get("terminal_env", {})
        ),
        desktop_target=target_data.get("desktop_target", ""),
    )
    session_id = data.get("session_id", "")
    instance_id = data.get("instance_id", "")
    canonical_id = data.get("canonical_id", "")
    if not canonical_id and instance_id:
        canonical_id = canonical_session_id(agent, session_id, instance_id)

    return FleetSession(
        session_id=session_id,
        agent=agent,
        repo=data.get("repo", ""),
        cwd=data.get("cwd", ""),
        status=status,
        detail=data.get("detail", ""),
        ts=data.get("ts", 0),
        started=data.get("started"),
        pid=str(data.get("pid", "")),
        terminal=terminal,
        terminal_env=data.get("terminal_env", {}),
        source=data.get("source", "hook"),
        tool=data.get("tool", ""),
        age_seconds=data.get("age_seconds", 0),
        needs_attention=data.get("needs_attention", False),
        canonical_id=canonical_id,
        instance_id=instance_id,
        schema_version=data.get("schema_version", 0),
        sequence=data.get("sequence"),
        process_start=data.get("process_start", ""),
        process_identity=data.get("process_identity", ""),
        focus_target=target,
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
        return sorted(
            sessions,
            key=lambda s: (
                not s.needs_attention,
                STATUS_PRIORITY.get(s.status, 9),
                s.repo.lower(),
            ),
        )
    elif key == "status":
        return sorted(sessions, key=lambda s: (STATUS_PRIORITY.get(s.status, 9), s.repo.lower()))
    elif key == "age":
        return sorted(sessions, key=lambda s: -s.age_seconds)
    else:
        return sorted(sessions, key=lambda s: s.repo.lower())
