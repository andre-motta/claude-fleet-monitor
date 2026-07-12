"""tmux terminal API."""

import os
import subprocess

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

TERMINAL_PROCESS_NAMES = {
    "konsole": "konsole",
    "gnome-terminal": "gnome",
    "gnome-terminal-server": "gnome",
    "iTerm2": "iterm2",
    "Terminal": "macos_terminal",
    "WindowsTerminal": "windows_terminal",
}


def _detect_parent_terminal(pid):
    """Walk up from a PID to find the parent terminal emulator process."""
    from claude_fleet_monitor.terminal_apis import get_terminal_api

    check_pid = pid
    while check_pid > 1:
        try:
            stat = open(f"/proc/{check_pid}/stat").read()
            ppid = int(stat.split(") ")[1].split()[1])
        except (OSError, ValueError, IndexError):
            try:
                ppid_str = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(check_pid)],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                ppid = int(ppid_str) if ppid_str else 0
            except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
                break

        if ppid <= 1:
            break

        try:
            try:
                cmdline = open(f"/proc/{ppid}/cmdline").read().replace("\0", " ")
            except OSError:
                cmdline = subprocess.run(
                    ["ps", "-o", "args=", "-p", str(ppid)],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()

            proc_name = os.path.basename(cmdline.split()[0]) if cmdline.strip() else ""
            if proc_name in TERMINAL_PROCESS_NAMES:
                return get_terminal_api(TERMINAL_PROCESS_NAMES[proc_name])
        except (OSError, IndexError, subprocess.TimeoutExpired):
            pass

        check_pid = ppid

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
        socket = terminal_env.get("TMUX", "").split(",")[0] if terminal_env.get("TMUX") else None
        cmd = ["tmux"]
        if socket:
            cmd.extend(["-S", socket])
        cmd.extend(["list-panes", "-a", "-F",
                     "#{pane_pid} #{session_name}:#{window_index}.#{pane_index}"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[0] == str(pid):
                return parts[1]

        # PID might be a child of the pane's shell; walk up
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            pane_pids = {}
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    pane_pids[int(parts[0])] = parts[1]

            check_pid = pid
            while check_pid > 1:
                if check_pid in pane_pids:
                    return pane_pids[check_pid]
                try:
                    stat = open(f"/proc/{check_pid}/stat").read()
                    check_pid = int(stat.split(") ")[1].split()[1])
                except (OSError, ValueError, IndexError):
                    break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        # tab_id format: "session_name:window_index.pane_index"
        socket = terminal_env.get("TMUX", "").split(",")[0] if terminal_env.get("TMUX") else None
        session_window = tab_id.rsplit(".", 1)[0]
        cmd = ["tmux"]
        if socket:
            cmd.extend(["-S", socket])

        try:
            subprocess.run(
                cmd + ["select-window", "-t", session_window],
                capture_output=True, timeout=5
            )
            subprocess.run(
                cmd + ["select-pane", "-t", tab_id],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        socket = terminal_env.get("TMUX", "").split(",")[0] if terminal_env.get("TMUX") else None
        cmd = ["tmux"]
        if socket:
            cmd.extend(["-S", socket])
        cmd.extend(["list-clients", "-F", "#{client_pid}"])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return True

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                client_pid = int(line.strip())
            except ValueError:
                continue

            parent_api = _detect_parent_terminal(client_pid)
            if parent_api:
                parent_tab = parent_api.find_tab(client_pid, {})
                if parent_tab:
                    parent_api.switch_tab(parent_tab, {})
                    parent_api.raise_window(parent_tab, {})
                    return True

        from claude_fleet_monitor.terminal_apis.generic import GenericAPI
        return GenericAPI().raise_window(tab_id, {})
