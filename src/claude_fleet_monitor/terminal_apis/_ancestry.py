"""Hook-time process ancestry: the nearest terminal or multiplexer (Linux only).

Environment markers leak into everything a terminal launches, so the nearest
known ancestor names the innermost terminal more reliably. Only
/proc/<pid>/stat is read (comm and ppid); environ and cmdline never are.
"""

import os
import sys

from claude_fleet_monitor.terminal_apis.tmux import TERMINAL_PROCESS_NAMES

MAX_STEPS = 64
COMM_LENGTH = 15
MULTIPLEXER_PROCESS_NAMES = {
    "zellij": "zellij",
    "screen": "screen",
    "SCREEN": "screen",
}
PROCESS_TERMINALS = {
    **{
        name[:COMM_LENGTH]: terminal
        for name, terminal in TERMINAL_PROCESS_NAMES.items()
    },
    **MULTIPLEXER_PROCESS_NAMES,
}


def _read_stat(pid: int) -> str:
    with open(f"/proc/{pid}/stat", "rb") as handle:
        return handle.read(4096).decode("utf-8", errors="replace")


def _parse_stat(text: str) -> tuple[str, int] | None:
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end < start:
        return None
    fields = text[end + 1:].split()
    if len(fields) < 2 or not fields[1].isascii() or not fields[1].isdigit():
        return None
    return text[start + 1:end], int(fields[1])


def comm_terminal(comm: str) -> str | None:
    if comm == "tmux" or comm.startswith("tmux:"):
        return "tmux"
    return PROCESS_TERMINALS.get(comm)


def nearest_terminal() -> str | None:
    """Return the terminal name of the nearest known ancestor, or None."""
    try:
        if sys.platform != "linux":
            return None
        pid = os.getpid()
        visited = set()
        for step in range(MAX_STEPS):
            if pid <= 0 or pid in visited:
                return None
            visited.add(pid)
            parsed = _parse_stat(_read_stat(pid))
            if parsed is None:
                return None
            comm, ppid = parsed
            if step:
                terminal = comm_terminal(comm)
                if terminal:
                    return terminal
            pid = ppid
    except Exception:
        return None
    return None
