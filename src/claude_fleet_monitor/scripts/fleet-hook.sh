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

truncate_str() {
    local s="$1" max="${2:-80}"
    if [ ${#s} -gt "$max" ]; then
        echo "${s:0:$max}..."
    else
        echo "$s"
    fi
}

case "$EVENT" in
    session-start)
        jq -n \
            --arg sid "$SESSION_ID" \
            --arg cwd "$CWD" \
            --arg repo "$REPO_NAME" \
            --argjson ts "$NOW" \
            '{session_id: $sid, repo: $repo, cwd: $cwd, status: "started", detail: "session started", ts: $ts, started: $ts}' \
            > "$STATUS_FILE"
        ;;
    prompt-submit)
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" \
                '.status = "running" | .detail = "processing prompt" | .ts = $ts' \
                "$STATUS_FILE" > "${STATUS_FILE}.tmp" && mv "${STATUS_FILE}.tmp" "$STATUS_FILE"
        else
            jq -n \
                --arg sid "$SESSION_ID" \
                --arg cwd "$CWD" \
                --arg repo "$REPO_NAME" \
                --argjson ts "$NOW" \
                '{session_id: $sid, repo: $repo, cwd: $cwd, status: "running", detail: "processing prompt", ts: $ts, started: $ts}' \
                > "$STATUS_FILE"
        fi
        ;;
    tool-use)
        DETAIL="using ${TOOL_NAME:-tool}"
        if [ -f "$STATUS_FILE" ]; then
            jq --argjson ts "$NOW" --arg detail "$DETAIL" --arg tool "${TOOL_NAME:-}" \
                '.status = "running" | .detail = $detail | .tool = $tool | .ts = $ts' \
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
