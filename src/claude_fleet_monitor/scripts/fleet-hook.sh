#!/usr/bin/env bash
set -euo pipefail

FLEET_DIR="${FLEET_DIR:-${HOME}/.claude/fleet}"
mkdir -p "$FLEET_DIR"

EVENT="${1:-unknown}"
INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
CWD=$(echo "$INPUT" | jq -r '.cwd // "unknown"')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // empty')

REPO_NAME=$(basename "$CWD")
STATUS_FILE="${FLEET_DIR}/${SESSION_ID}.json"
NOW=$(date +%s)

get_cmd_for_pid() {
    local pid="$1"
    if [ -f "/proc/$pid/cmdline" ]; then
        cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' | head -c 200
    else
        ps -o args= -p "$pid" 2>/dev/null | head -c 200
    fi
}

CLAUDE_PID=""
p=$$
while [ "$p" != "1" ] && [ -n "$p" ]; do
    cmd=$(get_cmd_for_pid "$p")
    if [[ "$cmd" == *"claude"* ]] && [[ "$cmd" != *"fleet-hook"* ]] && [[ "$cmd" != *"daemon"* ]] && [[ "$cmd" != *"bg-pty"* ]]; then
        CLAUDE_PID="$p"
        break
    fi
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
done

truncate_str() {
    local s="$1" max="${2:-80}"
    if [ ${#s} -gt "$max" ]; then
        echo "${s:0:$max}..."
    else
        echo "$s"
    fi
}

cleanup_stale_proc() {
    for f in "$FLEET_DIR"/proc-*.json; do
        [ -f "$f" ] || continue
        local pid_num
        pid_num=$(basename "$f" .json | sed 's/proc-//')
        if ! kill -0 "$pid_num" 2>/dev/null; then
            rm -f "$f"
        fi
    done
}

case "$EVENT" in
    session-start)
        cleanup_stale_proc
        jq -n \
            --arg sid "$SESSION_ID" \
            --arg cwd "$CWD" \
            --arg repo "$REPO_NAME" \
            --arg pid "$CLAUDE_PID" \
            --argjson ts "$NOW" \
            '{session_id: $sid, repo: $repo, cwd: $cwd, pid: $pid, status: "started", detail: "session started", ts: $ts, started: $ts}' \
            > "$STATUS_FILE"
        ;;
    prompt-submit)
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" --arg pid "$CLAUDE_PID" \
                '.status = "running" | .detail = "processing prompt" | .ts = $ts | if .pid == "" or .pid == null then .pid = $pid else . end' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        else
            jq -n \
                --arg sid "$SESSION_ID" \
                --arg cwd "$CWD" \
                --arg repo "$REPO_NAME" \
                --arg pid "$CLAUDE_PID" \
                --argjson ts "$NOW" \
                '{session_id: $sid, repo: $repo, cwd: $cwd, pid: $pid, status: "running", detail: "processing prompt", ts: $ts, started: $ts}' \
                > "$STATUS_FILE"
        fi
        ;;
    tool-use)
        DETAIL="using ${TOOL_NAME:-tool}"
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" --arg detail "$DETAIL" --arg tool "${TOOL_NAME:-}" --arg pid "$CLAUDE_PID" \
                '.status = "running" | .detail = $detail | .tool = $tool | .ts = $ts | if (.pid == "" or .pid == null) and $pid != "" then .pid = $pid else . end' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        fi
        ;;
    stop)
        SUMMARY=$(truncate_str "${LAST_MSG:-finished}" 120)
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" --arg detail "$SUMMARY" \
                '.status = "idle" | .detail = $detail | .tool = "" | .ts = $ts' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        fi
        ;;
    stop-failure)
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" \
                '.status = "error" | .detail = "turn failed (API error)" | .tool = "" | .ts = $ts' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        fi
        ;;
    session-end)
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" \
                '.status = "ended" | .detail = "session closed" | .tool = "" | .ts = $ts' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        fi
        ;;
esac
