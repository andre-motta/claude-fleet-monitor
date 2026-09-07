"""Agent hook handler that writes normalized fleet events."""

import json
import os
import sys
import time
import uuid

from claude_fleet_monitor.discovery import (
    MAX_DETAIL_LENGTH,
    MAX_EVENT_BYTES,
    MAX_ID_LENGTH,
    MAX_PATH_LENGTH,
    MAX_TOOL_LENGTH,
    read_session_record,
    read_stored_sessions,
    resolve_process_identity,
    write_session_record,
)
from claude_fleet_monitor.harnesses import ProcessIdentity, get_harness
from claude_fleet_monitor.models import (
    SCHEMA_VERSION,
    SessionStatus,
    canonical_session_id,
)


def _find_agent_pid(agent):
    process = resolve_process_identity(agent)
    return str(process.pid) if process else ""


def _read_payload():
    try:
        raw = sys.stdin.read(MAX_EVENT_BYTES + 1)
    except (OSError, UnicodeError):
        return None
    if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _text(payload, key, limit, *, required=False):
    value = payload.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"invalid {key}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"invalid {key}") from error
    if "\0" in value or len(encoded) > limit or (required and not value):
        raise ValueError(f"invalid {key}")
    return value


def _integer(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid {key}")
    return value


def _existing_record(harness_id, session_id, instance_id, pid=""):
    if instance_id:
        current = read_session_record(harness_id, session_id, instance_id)
        if current is not None:
            return current
    candidates = []
    for record in read_stored_sessions():
        if record["harness_id"] != harness_id or record["session_id"] != session_id:
            continue
        if not instance_id and pid and record.get("pid") == pid:
            candidates.append(record)
        if record.get("schema_version", 0) == 0:
            candidates.append(record)
    return max(candidates, key=lambda item: item.get("ts", 0), default=None)


def _capture_terminal_info():
    from claude_fleet_monitor.terminal_apis import capture_terminal_info
    return capture_terminal_info()


def _event_update(event, payload):
    tool_name = _text(payload, "tool_name", MAX_TOOL_LENGTH)
    if event == "session-start":
        return "started", "session started", ""
    if event == "prompt-submit":
        return "running", "processing prompt", ""
    if event == "tool-use":
        return "running", f"using {tool_name or 'tool'}", tool_name
    if event == "stop":
        message = _text(payload, "last_assistant_message", MAX_DETAIL_LENGTH * 4)
        summary = (message or "finished").replace("\n", " ").replace("\r", "")
        if len(summary) > 120:
            summary = summary[:120] + "..."
        return "idle", summary, ""
    if event == "stop-failure":
        return "error", "turn failed (API error)", ""
    if event == "permission-request":
        return "waiting", f"permission needed: {tool_name or 'tool'}", tool_name
    if event == "elicitation":
        return "waiting", "waiting for user input", ""
    return "ended", "session closed", ""


def _normalized_update(agent, payload):
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    event_id = _text(payload, "event_id", MAX_ID_LENGTH, required=True)
    namespace = f"{agent}."
    if not event_id.startswith(namespace) or len(event_id) == len(namespace):
        raise ValueError("event_id must use the harness namespace")
    status = _text(payload, "status", 32, required=True)
    lifecycle_statuses = {
        member.value
        for member in SessionStatus
        if member is not SessionStatus.DISCOVERED
    }
    if status not in lifecycle_statuses:
        raise ValueError("invalid status")
    detail = _text(payload, "detail", MAX_DETAIL_LENGTH)
    tool = _text(payload, "tool", MAX_TOOL_LENGTH)
    return status, detail, tool, event_id


def handle(event, agent="claude"):
    harness = get_harness(agent)
    if harness is None:
        raise ValueError(f"unsupported agent: {agent}")
    if not harness.supports_event(event):
        return False

    payload = _read_payload()
    if payload is None:
        return False
    try:
        session_id = _text(payload, "session_id", MAX_ID_LENGTH, required=True)
        cwd = _text(payload, "cwd", MAX_PATH_LENGTH, required=True)
        supplied_pid = _integer(payload, "pid")
        sequence = _integer(payload, "sequence")
        timestamp = _integer(payload, "ts")
        if event == "fleet-event":
            status, detail, tool, event_id = _normalized_update(agent, payload)
            supplied_instance = _text(
                payload, "instance_id", MAX_ID_LENGTH, required=True
            )
        else:
            status, detail, tool = _event_update(event, payload)
            event_id = f"{agent}.{event}"
            supplied_instance = ""
    except ValueError:
        return False

    if harness.process_identity is ProcessIdentity.EMITTER and supplied_pid is None:
        return False
    if harness.process_identity is ProcessIdentity.EMITTER and sequence is None:
        return False
    process = resolve_process_identity(agent, supplied_pid)
    if process is None:
        return False
    if supplied_instance:
        instance_id = supplied_instance
        existing = _existing_record(agent, session_id, instance_id)
    elif process.start_token:
        instance_id = f"{process.pid}:{process.start_token}"
        existing = _existing_record(agent, session_id, instance_id)
    else:
        existing = _existing_record(agent, session_id, "", str(process.pid))
        instance_id = (
            existing.get("instance_id", "") if existing else ""
        )
        if not instance_id:
            instance_id = f"{process.pid}:{uuid.uuid4().hex}"
    if event not in {"session-start", "prompt-submit", "fleet-event"} and existing is None:
        return False

    now = int(time.time()) if timestamp is None else timestamp
    terminal_info = None
    if existing is None or event == "session-start":
        terminal_info = _capture_terminal_info()
    terminal = (
        terminal_info["terminal"] if terminal_info is not None
        else existing.get("terminal", "")
    )
    terminal_env = (
        terminal_info["terminal_env"] if terminal_info is not None
        else existing.get("terminal_env", {})
    )
    started = now if existing is None or event == "session-start" else existing.get("started", now)
    canonical_id = canonical_session_id(agent, session_id, instance_id)
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": "session",
        "canonical_id": canonical_id,
        "session_id": session_id,
        "instance_id": instance_id,
        "harness_id": agent,
        "agent": agent,
        "repo": os.path.basename(os.path.normpath(cwd)),
        "cwd": cwd,
        "pid": str(process.pid),
        "process_start": process.start_token,
        "status": status,
        "detail": detail,
        "tool": tool,
        "ts": now,
        "started": started,
        "source": "hook",
        "last_event": event_id,
        "terminal": terminal,
        "terminal_env": terminal_env,
        "focus_target": {
            "kind": "terminal" if terminal else "unavailable",
            "terminal": terminal,
            "terminal_env": terminal_env,
        },
    }
    if sequence is not None:
        record["sequence"] = sequence
    return write_session_record(record)


def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    agent = "claude"
    if "--agent" in sys.argv:
        index = sys.argv.index("--agent")
        if index + 1 >= len(sys.argv):
            sys.exit(1)
        agent = sys.argv[index + 1]
    try:
        handle(sys.argv[1], agent)
    except ValueError:
        sys.exit(1)


if __name__ == "__main__":
    main()
