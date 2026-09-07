"""tmux terminal API."""

import os
import re
import subprocess

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis.base import TerminalAPI

TERMINAL_PROCESS_NAMES = {
    "konsole": "konsole",
    "ghostty": "ghostty",
    "gnome-terminal": "gnome",
    "gnome-terminal-server": "gnome",
    "iTerm2": "iterm2",
    "Terminal": "macos_terminal",
    "WindowsTerminal": "windows_terminal",
}

_MAX_ANCESTORS = 128
_TARGET_PATTERN = re.compile(
    r"^(?P<session>\$\d+):(?P<window>@\d+)\.(?P<pane>%\d+)$"
)
_PANE_FORMAT = "#{session_id}\t#{window_id}\t#{pane_id}\t#{pane_pid}"
_CLIENT_FORMAT = (
    "#{client_pid}\t#{session_id}\t#{window_id}\t#{pane_id}"
    "\t#{client_control_mode}"
)


def _tmux_context(terminal_env: dict) -> tuple[list[str], str | None] | None:
    if not isinstance(terminal_env, dict):
        return None
    value = terminal_env.get("TMUX", "")
    if not value:
        return ["tmux"], None
    if not isinstance(value, str):
        return None
    parts = value.rsplit(",", 2)
    if (
        len(parts) != 3
        or not parts[0]
        or not parts[1].isdigit()
        or int(parts[1]) <= 0
        or not parts[2].isdigit()
    ):
        return None
    return ["tmux", "-S", parts[0]], f"${int(parts[2])}"


def _run_tmux(command: list[str]) -> subprocess.CompletedProcess | None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result


def _parse_target(tab_id: str) -> tuple[str, str, str] | None:
    if not isinstance(tab_id, str):
        return None
    match = _TARGET_PATTERN.fullmatch(tab_id)
    if match is None:
        return None
    return match.group("session"), match.group("window"), match.group("pane")


def _process_terminal(process) -> str | None:
    names = [process.executable, process.name]
    if process.argv:
        names.append(process.argv[0])
    for value in names:
        name = os.path.basename(value) if value else ""
        if name in TERMINAL_PROCESS_NAMES:
            return TERMINAL_PROCESS_NAMES[name]
    return None


def _detect_parent_terminal(pid):
    """Walk bounded process ancestry to find the parent terminal emulator."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return None
    try:
        process = discovery.get_process_info(pid)
    except Exception:
        return None
    visited = {pid}
    for _ in range(_MAX_ANCESTORS):
        if process is None or process.ppid is None or process.ppid <= 1:
            return None
        if process.ppid in visited:
            return None
        visited.add(process.ppid)
        try:
            process = discovery.get_process_info(process.ppid)
        except Exception:
            return None
        if process is None:
            return None
        terminal_name = _process_terminal(process)
        if terminal_name:
            from claude_fleet_monitor.terminal_apis import get_terminal_api

            return get_terminal_api(terminal_name)
    return None


class TmuxAPI(TerminalAPI):
    name = "tmux"

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("TMUX"))

    @staticmethod
    def capture_env() -> dict:
        return {"TMUX": os.environ.get("TMUX", "")}

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            return None
        context = _tmux_context(terminal_env)
        if context is None:
            return None
        command, captured_session = context
        result = _run_tmux(command + ["list-panes", "-a", "-F", _PANE_FORMAT])
        if result is None:
            return None

        pane_targets: dict[int, set[str]] = {}
        for line in (result.stdout or "").splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                return None
            session_id, window_id, pane_id, pane_pid = parts
            target = f"{session_id}:{window_id}.{pane_id}"
            if _parse_target(target) is None or not pane_pid.isdigit():
                return None
            parsed_pid = int(pane_pid)
            if parsed_pid <= 1:
                return None
            pane_targets.setdefault(parsed_pid, set()).add(target)

        check_pid = pid
        visited: set[int] = set()
        for _ in range(_MAX_ANCESTORS):
            if check_pid <= 1 or check_pid in visited:
                return None
            visited.add(check_pid)
            targets = pane_targets.get(check_pid)
            if targets:
                if captured_session:
                    matching = sorted(
                        target
                        for target in targets
                        if target.startswith(f"{captured_session}:")
                    )
                    return matching[0] if len(matching) == 1 else None
                return next(iter(targets)) if len(targets) == 1 else None
            try:
                process = discovery.get_process_info(check_pid)
            except Exception:
                return None
            if process is None or process.ppid is None:
                return None
            check_pid = process.ppid
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_target(tab_id)
        context = _tmux_context(terminal_env)
        if target is None or context is None:
            return False
        session_id, window_id, _ = target
        command, captured_session = context
        if captured_session and session_id != captured_session:
            return False

        if _run_tmux(
            command + ["select-window", "-t", f"{session_id}:{window_id}"]
        ) is None:
            return False
        if _run_tmux(command + ["select-pane", "-t", tab_id]) is None:
            return False
        selected = _run_tmux(
            command
            + [
                "display-message",
                "-p",
                "-t",
                session_id,
                "#{session_id}:#{window_id}.#{pane_id}",
            ]
        )
        return selected is not None and (selected.stdout or "").strip() == tab_id

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        target = _parse_target(tab_id)
        context = _tmux_context(terminal_env)
        if target is None or context is None:
            return False
        session_id, window_id, pane_id = target
        command, captured_session = context
        if captured_session and session_id != captured_session:
            return False

        result = _run_tmux(
            command
            + ["list-clients", "-t", session_id, "-F", _CLIENT_FORMAT]
        )
        if result is None:
            return False

        client_pids = []
        for line in (result.stdout or "").splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                return False
            client_pid, client_session, client_window, client_pane, control = parts
            if (
                not client_pid.isdigit()
                or control not in {"0", "1"}
                or _parse_target(
                    f"{client_session}:{client_window}.{client_pane}"
                )
                is None
            ):
                return False
            if (
                control == "0"
                and client_session == session_id
                and client_window == window_id
                and client_pane == pane_id
            ):
                parsed_pid = int(client_pid)
                if parsed_pid > 1:
                    client_pids.append(parsed_pid)

        for client_pid in sorted(set(client_pids)):
            parent_api = _detect_parent_terminal(client_pid)
            if parent_api is None:
                continue
            try:
                parent_tab = parent_api.find_tab(client_pid, {})
                if parent_api.selection_supported:
                    if not parent_tab or not parent_api.switch_tab(parent_tab, {}):
                        continue
                if parent_tab and parent_api.raise_window(parent_tab, {}):
                    return True
            except Exception:
                continue
        return False
