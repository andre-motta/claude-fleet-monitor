#!/usr/bin/env bash
set -euo pipefail

FLEET_DIR="${FLEET_DIR:-${HOME}/.claude/fleet}"
REFRESH="${1:-2}"

C_RESET="\033[0m"
C_DIM="\033[90m"
C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_CYAN="\033[1;36m"
C_MAGENTA="\033[1;35m"
C_WHITE="\033[1;37m"

status_icon() {
    case "$1" in
        running)    printf "${C_GREEN}*${C_RESET}" ;;
        idle)       printf "${C_YELLOW}=${C_RESET}" ;;
        started)    printf "${C_CYAN}>${C_RESET}" ;;
        error)      printf "${C_RED}x${C_RESET}" ;;
        ended)      printf "${C_DIM}-${C_RESET}" ;;
        discovered) printf "${C_MAGENTA}+${C_RESET}" ;;
        *)          printf "${C_DIM}?${C_RESET}" ;;
    esac
}

format_age() {
    local age=$1
    if [ "$age" -lt 60 ]; then
        echo "${age}s"
    elif [ "$age" -lt 3600 ]; then
        echo "$((age / 60))m"
    else
        echo "$((age / 3600))h$((age % 3600 / 60))m"
    fi
}

repeat_char() {
    printf '%*s' "$1" '' | tr ' ' "$2"
}

print_row() {
    local w=$1 content=$2
    local visible_len=${#content}
    local pad=$((w - 4 - visible_len))
    [ "$pad" -lt 0 ] && pad=0
    printf "${C_WHITE}|${C_RESET} %s%*s ${C_WHITE}|${C_RESET}\n" "$content" "$pad" ""
}

render() {
    local now cols w
    now=$(date +%s)
    cols=$(tput cols 2>/dev/null || echo 100)
    w=$cols
    local needs_attention=0
    local total=0
    local active=0

    local col_repo=26 col_status=12 col_age=7
    local col_detail=$((w - 4 - 2 - col_repo - 1 - col_status - 1 - col_age - 1))
    [ "$col_detail" -lt 10 ] && col_detail=10

    clear

    printf "${C_WHITE}+-- Claude Fleet Monitor "
    repeat_char $((w - 26)) "-"
    printf "+${C_RESET}\n"

    if [ ! -d "$FLEET_DIR" ] || [ -z "$(ls -A "$FLEET_DIR" 2>/dev/null)" ]; then
        print_row "$w" "No sessions detected. Start Claude Code with hooks enabled."
    else
        local header
        header=$(printf "  %-*s %-*s %-*s %*s" "$col_repo" "REPO" "$col_status" "STATUS" "$col_detail" "DETAIL" "$col_age" "AGE")
        local hpad=$((w - 4 - ${#header}))
        [ "$hpad" -lt 0 ] && hpad=0
        printf "${C_WHITE}|${C_RESET} ${C_DIM}%s${C_RESET}%*s ${C_WHITE}|${C_RESET}\n" "$header" "$hpad" ""

        printf "${C_WHITE}|${C_RESET} "
        repeat_char $((w - 4)) "-"
        printf " ${C_WHITE}|${C_RESET}\n"

        for f in "$FLEET_DIR"/*.json; do
            [ -f "$f" ] || continue
            total=$((total + 1))

            local repo status detail ts
            repo=$(jq -r '.repo // "?"' "$f" 2>/dev/null)
            status=$(jq -r '.status // "?"' "$f" 2>/dev/null)
            detail=$(jq -r '.detail // ""' "$f" 2>/dev/null)
            ts=$(jq -r '.ts // 0' "$f" 2>/dev/null)

            local age age_str
            age=$((now - ts))
            age_str=$(format_age "$age")

            [ "$status" = "running" ] || [ "$status" = "started" ] && active=$((active + 1))
            [ "$status" = "idle" ] && [ "$age" -gt 120 ] && needs_attention=$((needs_attention + 1))

            local short_repo="${repo:0:$col_repo}"
            local short_detail="${detail:0:$col_detail}"
            local status_upper
            status_upper=$(echo "$status" | tr '[:lower:]' '[:upper:]')

            local row_text
            row_text=$(printf "%-*s %-*s %-*s %*s" "$col_repo" "$short_repo" "$col_status" "$status_upper" "$col_detail" "$short_detail" "$col_age" "$age_str")
            local rpad=$((w - 4 - 2 - ${#row_text}))
            [ "$rpad" -lt 0 ] && rpad=0
            printf "${C_WHITE}|${C_RESET} "
            status_icon "$status"
            printf " %s%*s ${C_WHITE}|${C_RESET}\n" "$row_text" "$rpad" ""
        done
    fi

    printf "${C_WHITE}|${C_RESET}%*s${C_WHITE}|${C_RESET}\n" "$((w - 2))" ""

    if [ "$needs_attention" -gt 0 ]; then
        local msg
        msg=$(printf "! %d session(s) idle >2m -- may need input" "$needs_attention")
        local mpad=$((w - 4 - ${#msg}))
        [ "$mpad" -lt 0 ] && mpad=0
        printf "${C_WHITE}|${C_RESET} ${C_YELLOW}%s${C_RESET}%*s ${C_WHITE}|${C_RESET}\n" "$msg" "$mpad" ""
    fi

    local footer
    footer=$(printf "Total: %d  Active: %d  Refresh: %ds  [Ctrl+C to exit]" "$total" "$active" "$REFRESH")
    local fpad=$((w - 4 - ${#footer}))
    [ "$fpad" -lt 0 ] && fpad=0
    printf "${C_WHITE}|${C_RESET} ${C_DIM}%s${C_RESET}%*s ${C_WHITE}|${C_RESET}\n" "$footer" "$fpad" ""

    printf "${C_WHITE}+"
    repeat_char $((w - 2)) "-"
    printf "+${C_RESET}\n"
}

cleanup_ended() {
    local now
    now=$(date +%s)
    for f in "$FLEET_DIR"/*.json; do
        [ -f "$f" ] || continue
        local status ts
        status=$(jq -r '.status // ""' "$f" 2>/dev/null)
        ts=$(jq -r '.ts // 0' "$f" 2>/dev/null)
        if [ "$status" = "ended" ] && [ $((now - ts)) -gt 300 ]; then
            rm -f "$f"
        fi
    done
}

discover_processes() {
    local now
    now=$(date +%s)

    for pid in $(pgrep -x claude 2>/dev/null); do
        local cwd cmdline tty
        cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null) || continue
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null) || continue
        tty=$(ls -la "/proc/$pid/fd/0" 2>/dev/null | grep -oP 'pts/\d+' || echo "")

        [[ "$cmdline" == *"daemon"* || "$cmdline" == *"bg-pty"* || "$cmdline" == *"bg-spare"* ]] && continue
        [ -f "${FLEET_DIR}/proc-${pid}.json" ] && continue

        local repo
        repo=$(basename "$cwd")
        jq -n \
            --arg sid "proc-${pid}" \
            --arg cwd "$cwd" \
            --arg repo "$repo" \
            --arg tty "$tty" \
            --argjson ts "$now" \
            '{session_id: $sid, repo: $repo, cwd: $cwd, status: "discovered", detail: ("PID " + $sid[5:] + " " + $tty), ts: $ts, started: $ts, source: "process"}' \
            > "${FLEET_DIR}/proc-${pid}.json"
    done

    for f in "$FLEET_DIR"/proc-*.json; do
        [ -f "$f" ] || continue
        local pid_num
        pid_num=$(jq -r '.session_id // ""' "$f" | sed 's/proc-//')
        if [ -n "$pid_num" ] && ! kill -0 "$pid_num" 2>/dev/null; then
            rm -f "$f"
        fi
    done
}

NOTIFIED_FILE=$(mktemp)
trap 'rm -f "$NOTIFIED_FILE"' EXIT

check_notifications() {
    local now
    now=$(date +%s)
    for f in "$FLEET_DIR"/*.json; do
        [ -f "$f" ] || continue
        local sid status ts repo
        sid=$(jq -r '.session_id // ""' "$f" 2>/dev/null)
        status=$(jq -r '.status // ""' "$f" 2>/dev/null)
        ts=$(jq -r '.ts // 0' "$f" 2>/dev/null)
        repo=$(jq -r '.repo // ""' "$f" 2>/dev/null)
        local age=$((now - ts))

        if [ "$status" = "idle" ] && [ "$age" -gt 120 ]; then
            if ! grep -qF "$sid" "$NOTIFIED_FILE" 2>/dev/null; then
                echo "$sid" >> "$NOTIFIED_FILE"
                if command -v notify-send &>/dev/null; then
                    notify-send -u normal -a "Claude Fleet" \
                        "Session needs input" \
                        "$repo idle for $(format_age "$age") -- may need input" \
                        2>/dev/null || true
                fi
            fi
        else
            sed -i "/$sid/d" "$NOTIFIED_FILE" 2>/dev/null || true
        fi
    done
}

while true; do
    discover_processes
    cleanup_ended
    check_notifications
    render
    sleep "$REFRESH"
done
