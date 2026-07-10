#!/usr/bin/env bash
set -euo pipefail

FLEET_DIR="${FLEET_DIR:-${HOME}/.claude/fleet}"

usage() {
    echo "Usage: fleet-focus.sh <session-id-or-repo>"
    echo ""
    echo "Focus the terminal window/tab running a Claude session."
    echo "Accepts a session ID (or prefix), repo name, or PID."
    echo ""
    echo "Examples:"
    echo "  fleet-focus.sh autofix"
    echo "  fleet-focus.sh proc-2467709"
    echo "  fleet-focus.sh 2467709"
    exit 1
}

[ $# -lt 1 ] && usage

QUERY="$1"

find_session_file() {
    local query="$1"
    local match=""
    local count=0

    for f in "$FLEET_DIR"/*.json; do
        [ -f "$f" ] || continue
        local sid repo
        sid=$(jq -r '.session_id // ""' "$f" 2>/dev/null)
        repo=$(jq -r '.repo // ""' "$f" 2>/dev/null)

        if [[ "$sid" == *"$query"* ]] || [[ "$repo" == *"$query"* ]]; then
            match="$f"
            count=$((count + 1))
        fi
    done

    if [ "$count" -eq 0 ]; then
        echo "No session matching '$query'" >&2
        exit 1
    elif [ "$count" -gt 1 ]; then
        echo "Multiple sessions match '$query':" >&2
        for f in "$FLEET_DIR"/*.json; do
            [ -f "$f" ] || continue
            local sid repo
            sid=$(jq -r '.session_id // ""' "$f" 2>/dev/null)
            repo=$(jq -r '.repo // ""' "$f" 2>/dev/null)
            if [[ "$sid" == *"$query"* ]] || [[ "$repo" == *"$query"* ]]; then
                echo "  $repo ($sid)" >&2
            fi
        done
        exit 1
    fi

    echo "$match"
}

get_pid_from_session() {
    local session_file="$1"
    local sid
    sid=$(jq -r '.session_id // ""' "$session_file")
    if [[ "$sid" == proc-* ]]; then
        echo "${sid#proc-}"
    else
        echo ""
    fi
}

raise_window_by_pid() {
    local pid="$1"

    if command -v qdbus &>/dev/null && qdbus org.kde.KWin /Scripting 2>/dev/null | grep -q loadScript; then
        local script
        script=$(mktemp --suffix=.js)
        cat > "$script" << JSEOF
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    if (windows[i].pid === $pid) {
        workspace.activeWindow = windows[i];
        break;
    }
}
JSEOF
        local script_id
        script_id=$(qdbus org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$script" 2>/dev/null)
        if [[ "$script_id" =~ ^[0-9]+$ ]]; then
            qdbus org.kde.KWin "/Scripting/Script$script_id" org.kde.kwin.Script.run 2>/dev/null
        fi
        rm -f "$script"
        return 0
    fi

    if command -v xdotool &>/dev/null; then
        local wid
        wid=$(xdotool search --pid "$pid" 2>/dev/null | head -1)
        [ -n "$wid" ] && xdotool windowactivate "$wid" 2>/dev/null && return 0
    fi

    return 1
}

focus_konsole() {
    local target_pid="$1"
    local konsole_service=""

    for svc in $(qdbus 2>/dev/null | grep 'org.kde.konsole'); do
        konsole_service="$svc"
        local sessions
        sessions=$(qdbus "$svc" 2>/dev/null | grep '/Sessions/' | sed 's|/Sessions/||')

        for session_id in $sessions; do
            local fg_pid
            fg_pid=$(qdbus "$svc" "/Sessions/$session_id" org.kde.konsole.Session.foregroundProcessId 2>/dev/null || echo "")
            local shell_pid
            shell_pid=$(qdbus "$svc" "/Sessions/$session_id" org.kde.konsole.Session.processId 2>/dev/null || echo "")

            if [ "$fg_pid" = "$target_pid" ] || [ "$shell_pid" = "$target_pid" ]; then
                local windows
                windows=$(qdbus "$svc" 2>/dev/null | grep '/Windows/' | sed 's|/Windows/||')
                for win_id in $windows; do
                    local win_sessions
                    win_sessions=$(qdbus "$svc" "/Windows/$win_id" org.kde.konsole.Window.sessionList 2>/dev/null || echo "")
                    if echo "$win_sessions" | grep -qw "$session_id"; then
                        qdbus "$svc" "/Windows/$win_id" org.kde.konsole.Window.setCurrentSession "$session_id" 2>/dev/null

                        local konsole_pid
                        konsole_pid=$(echo "$svc" | grep -oP '\d+$')
                        if [ -n "$konsole_pid" ]; then
                            raise_window_by_pid "$konsole_pid"
                        fi

                        echo "Focused Konsole session $session_id (PID $target_pid)"
                        return 0
                    fi
                done
            fi
        done
    done

    return 1
}

focus_generic() {
    local target_pid="$1"

    local ppid
    ppid=$(ps -o ppid= -p "$target_pid" 2>/dev/null | tr -d ' ')
    while [ -n "$ppid" ] && [ "$ppid" != "1" ]; do
        if raise_window_by_pid "$ppid"; then
            echo "Focused window for PID $ppid (parent of $target_pid)"
            return 0
        fi
        ppid=$(ps -o ppid= -p "$ppid" 2>/dev/null | tr -d ' ')
    done

    return 1
}

SESSION_FILE=$(find_session_file "$QUERY")
TARGET_PID=$(get_pid_from_session "$SESSION_FILE")
REPO=$(jq -r '.repo // "?"' "$SESSION_FILE")

if [ -z "$TARGET_PID" ]; then
    echo "Session '$REPO' has no PID (hook-only session, no process discovery)" >&2
    echo "Try interacting with the session so hooks capture the PID" >&2
    exit 1
fi

if ! kill -0 "$TARGET_PID" 2>/dev/null; then
    echo "PID $TARGET_PID is no longer running" >&2
    exit 1
fi

if command -v qdbus &>/dev/null && qdbus 2>/dev/null | grep -q 'org.kde.konsole'; then
    if focus_konsole "$TARGET_PID"; then
        exit 0
    fi
fi

if focus_generic "$TARGET_PID"; then
    exit 0
fi

echo "Could not find terminal window for PID $TARGET_PID ($REPO)" >&2
exit 1
