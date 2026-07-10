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
    local hook_matches=()
    local proc_matches=()

    for f in "$FLEET_DIR"/*.json; do
        [ -f "$f" ] || continue
        local sid repo
        sid=$(jq -r '.session_id // ""' "$f" 2>/dev/null)
        repo=$(jq -r '.repo // ""' "$f" 2>/dev/null)

        if [[ "$sid" == *"$query"* ]] || [[ "$repo" == *"$query"* ]]; then
            if [[ "$(basename "$f")" == proc-* ]]; then
                proc_matches+=("$f")
            else
                hook_matches+=("$f")
            fi
        fi
    done

    local all_matches=()
    if [ ${#hook_matches[@]} -gt 0 ]; then
        all_matches=("${hook_matches[@]}")
    else
        all_matches=("${proc_matches[@]}")
    fi

    if [ ${#all_matches[@]} -eq 0 ]; then
        echo "No session matching '$query'" >&2
        exit 1
    elif [ ${#all_matches[@]} -eq 1 ]; then
        echo "${all_matches[0]}"
    else
        echo "Multiple sessions match '$query':" >&2
        for f in "${all_matches[@]}"; do
            local sid repo
            sid=$(jq -r '.session_id // ""' "$f" 2>/dev/null)
            repo=$(jq -r '.repo // ""' "$f" 2>/dev/null)
            echo "  $repo ($sid)" >&2
        done
        exit 1
    fi
}

get_pid_from_session() {
    local session_file="$1"
    local sid stored_pid cwd
    sid=$(jq -r '.session_id // ""' "$session_file")
    stored_pid=$(jq -r '.pid // ""' "$session_file")
    cwd=$(jq -r '.cwd // ""' "$session_file")

    if [[ "$sid" == proc-* ]]; then
        echo "${sid#proc-}"
        return
    fi

    if [ -n "$stored_pid" ] && kill -0 "$stored_pid" 2>/dev/null; then
        echo "$stored_pid"
        return
    fi

    for pid in $(pgrep -x claude 2>/dev/null); do
        local pcwd cmdline
        pcwd=$(readlink "/proc/$pid/cwd" 2>/dev/null) || continue
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
        [[ "$cmdline" == *"daemon"* || "$cmdline" == *"bg-pty"* || "$cmdline" == *"bg-spare"* ]] && continue
        if [ "$pcwd" = "$cwd" ]; then
            echo "$pid"
            return
        fi
    done

    echo ""
}

raise_by_kwin_title() {
    local title="$1"
    local safe_title
    safe_title=$(echo "$title" | sed "s/'/\\\\'/g")

    local script
    script=$(mktemp --suffix=.js)
    cat > "$script" << JSEOF
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    if (windows[i].caption.indexOf('$safe_title') !== -1) {
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
}

raise_by_xdotool() {
    local title="$1"
    local wid
    wid=$(xdotool search --name "$title" 2>/dev/null | head -1)
    [ -n "$wid" ] && xdotool windowactivate "$wid" 2>/dev/null
}

raise_by_osascript() {
    local title="$1"
    osascript -e "
        tell application \"System Events\"
            set frontmost of (first process whose name contains \"Terminal\" or name contains \"iTerm\") to true
        end tell
        tell application \"Terminal\"
            set index of (first window whose name contains \"$title\") to 1
        end tell
    " 2>/dev/null || true
}

raise_window() {
    local title="$1"

    if command -v qdbus &>/dev/null && qdbus org.kde.KWin /Scripting 2>/dev/null | grep -q loadScript; then
        raise_by_kwin_title "$title"
        return 0
    fi

    if command -v xdotool &>/dev/null; then
        raise_by_xdotool "$title"
        return 0
    fi

    if command -v osascript &>/dev/null; then
        raise_by_osascript "$title"
        return 0
    fi

    return 1
}

focus_konsole() {
    local target_pid="$1"

    for svc in $(qdbus 2>/dev/null | grep 'org.kde.konsole'); do
        local sessions
        sessions=$(qdbus "$svc" 2>/dev/null | grep '/Sessions/' | sed 's|/Sessions/||')

        for session_id in $sessions; do
            local fg_pid shell_pid
            fg_pid=$(qdbus "$svc" "/Sessions/$session_id" org.kde.konsole.Session.foregroundProcessId 2>/dev/null || echo "")
            shell_pid=$(qdbus "$svc" "/Sessions/$session_id" org.kde.konsole.Session.processId 2>/dev/null || echo "")

            if [ "$fg_pid" = "$target_pid" ] || [ "$shell_pid" = "$target_pid" ]; then
                local windows
                windows=$(qdbus "$svc" 2>/dev/null | grep '/Windows/' | sed 's|/Windows/||')
                for win_id in $windows; do
                    local win_sessions
                    win_sessions=$(qdbus "$svc" "/Windows/$win_id" org.kde.konsole.Window.sessionList 2>/dev/null || echo "")
                    if echo "$win_sessions" | grep -qw "$session_id"; then
                        qdbus "$svc" "/Windows/$win_id" org.kde.konsole.Window.setCurrentSession "$session_id" 2>/dev/null

                        local session_title
                        session_title=$(qdbus "$svc" "/Sessions/$session_id" org.kde.konsole.Session.title 1 2>/dev/null || echo "")
                        if [ -n "$session_title" ]; then
                            raise_window "$session_title"
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
    local repo="$2"

    raise_window "$repo" && echo "Focused window matching '$repo'" && return 0

    local ppid
    ppid=$(ps -o ppid= -p "$target_pid" 2>/dev/null | tr -d ' ')
    while [ -n "$ppid" ] && [ "$ppid" != "1" ]; do
        if command -v xdotool &>/dev/null; then
            local wid
            wid=$(xdotool search --pid "$ppid" 2>/dev/null | head -1)
            if [ -n "$wid" ]; then
                xdotool windowactivate "$wid" 2>/dev/null
                echo "Focused window for PID $ppid (parent of $target_pid)"
                return 0
            fi
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

if focus_generic "$TARGET_PID" "$REPO"; then
    exit 0
fi

echo "Could not find terminal window for PID $TARGET_PID ($REPO)" >&2
exit 1
