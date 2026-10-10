"""Cross-platform focus service for Fleet sessions."""

import sys

from claude_fleet_monitor.discovery import read_session_records, resolve_session_process
from claude_fleet_monitor.models import FocusOperation, FocusResult
from claude_fleet_monitor.terminal_apis import find_terminal_api

_DETAILS_LIMIT = 120
_GENERIC_DETAILS = frozenset({"tab or pane selection", "window activation"})
_UNSUPPORTED_PREFIX = "backend does not support "


def _public_record(record):
    return {
        key: value for key, value in record.items()
        if not key.startswith("_")
    }


def _matching_sessions(query):
    records = read_session_records()
    fields = ("canonical_id", "session_id", "repo", "pid")
    exact = [
        record for record in records
        if any(query == str(record.get(field, "")) for field in fields)
    ]
    matches = exact or [
        record for record in records
        if any(query in str(record.get(field, "")) for field in fields)
    ]
    hook_matches = [record for record in matches if not record.get("_process")]
    return hook_matches if hook_matches else matches


def find_session(query):
    matches = _matching_sessions(query)
    if not matches:
        print(f"No session matching '{query}'", file=sys.stderr)
        return None
    if len(matches) == 1:
        return _public_record(matches[0])
    print(f"Multiple sessions match '{query}':", file=sys.stderr)
    for match in matches:
        harness = match.get("harness_id", match.get("agent", "claude"))
        identity = match.get("canonical_id") or match["session_id"]
        print(
            f"  {harness}: {match.get('repo', '?')} "
            f"({match['session_id']}) [{identity}]",
            file=sys.stderr,
        )
    return None


def get_pid(session):
    process = resolve_session_process(session)
    return process.pid if process else None


def _collapsed(text) -> str:
    return " ".join(str(text).replace("\0", "").split())


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _operation_detail(operation: FocusOperation) -> str:
    if operation.succeeded:
        return "ok"
    detail = _collapsed(operation.detail)
    if not operation.attempted and detail.startswith(_UNSUPPORTED_PREFIX):
        return "unsupported"
    if operation.attempted and (not detail or detail in _GENERIC_DETAILS):
        return "failed"
    return detail or "unavailable"


def _step_details(result: FocusResult) -> tuple[str, str]:
    selection = _operation_detail(result.selection)
    activation = _operation_detail(result.activation)
    if result.selection.succeeded or result.activation.succeeded:
        return (
            _bounded(selection, _DETAILS_LIMIT),
            _bounded(activation, _DETAILS_LIMIT),
        )
    # Share one budget so a long selection detail never hides activation.
    half = _DETAILS_LIMIT // 2
    return (
        _bounded(selection, max(half, _DETAILS_LIMIT - len(activation))),
        _bounded(activation, max(half, _DETAILS_LIMIT - len(selection))),
    )


def _details_suffix(result: FocusResult) -> str:
    selection, activation = _step_details(result)
    return f" (selection: {selection}; activation: {activation})"


def focus_notification(result: FocusResult, repo: str) -> tuple[str, str]:
    if result.complete:
        return f"Focused: {repo}", "information"
    if result.successful:
        message, severity = f"Partially focused: {repo}", "warning"
    else:
        label = result.state.replace("-", " ").capitalize()
        message, severity = f"Focus {label}: {repo}: {result.reason}", "error"
    if result.successful or result.state == "failed":
        message += _details_suffix(result)
    return message, severity


def focus_session(query) -> FocusResult:
    matches = _matching_sessions(query)
    if not matches:
        return FocusResult(state="not-found", reason=f"no session matching '{query}'")
    if len(matches) > 1:
        identities = ", ".join(
            match.get("canonical_id") or match["session_id"]
            for match in matches
        )
        return FocusResult(
            state="ambiguous",
            reason=f"multiple sessions match '{query}': {identities}",
        )
    session = _public_record(matches[0])
    process = resolve_session_process(session)
    if process is None:
        return FocusResult(
            state="unavailable",
            reason="stored process identity is unavailable or stale",
        )

    target = session.get("focus_target", {})
    if not isinstance(target, dict):
        target = {}
    target_kind = target.get("kind")
    terminal_type = target.get("terminal", session.get("terminal", ""))
    terminal_env = target.get("terminal_env", session.get("terminal_env", {}))
    if target_kind == "desktop":
        return FocusResult(
            state="unavailable",
            reason="desktop focus target has no configured backend",
            pid=process.pid,
        )
    if target_kind == "unavailable":
        return FocusResult(
            state="unavailable",
            reason="session focus target is unavailable",
            pid=process.pid,
        )
    if not terminal_type:
        return FocusResult(
            state="unavailable",
            reason="session has no captured terminal metadata",
            pid=process.pid,
        )
    api = find_terminal_api(terminal_type)
    if api is None:
        return FocusResult(
            state="unavailable",
            reason=f"captured terminal backend '{terminal_type}' is unavailable",
            backend=terminal_type,
            pid=process.pid,
        )
    return api.focus_result(process.pid, terminal_env)


def focus(query):
    result = focus_session(query)
    if result.complete:
        print(f"Focused session via {result.backend} (PID {result.pid})")
        return True
    if result.successful:
        print(
            f"Partially focused session via {result.backend} (PID {result.pid})"
            + _details_suffix(result)
        )
        return True
    message = result.reason
    if result.state == "failed":
        message += _details_suffix(result)
    print(message, file=sys.stderr)
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: claude-fleet focus <session-id-or-repo>", file=sys.stderr)
        sys.exit(1)
    if not focus(sys.argv[1]):
        sys.exit(1)


if __name__ == "__main__":
    main()
