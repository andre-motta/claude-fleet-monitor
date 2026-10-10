"""Zellij terminal API.

Selection runs `zellij --session <S> action focus-pane-id terminal_<id>` and
is confirmed only when `action list-clients` shows an attached client on that
pane. focus-pane-id moves only the client that most recently sent input and
exits 0 even with no client attached, so its exit status alone proves nothing.
Live behavior was validated with zellij 0.45.1; no older version was probed,
so unrecognized output is treated as unsupported rather than gated by version.
"""

import os
import subprocess
import time

from claude_fleet_monitor.terminal_apis import tmux
from claude_fleet_monitor.terminal_apis._env import bounded_env, is_decimal_id
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.parent import activate_parent

ENV_KEYS = ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID")
VALIDATED_VERSION = "0.45.1"
MAX_SESSION_BYTES = 256
COMMAND_TIMEOUT = 5
READBACK_ATTEMPTS = 5
READBACK_INTERVAL = 0.1
LIST_CLIENTS_COLUMNS = ("CLIENT_ID", "ZELLIJ_PANE_ID")


def _run(argv: list[str]) -> subprocess.CompletedProcess | None:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result


def _safe_session(value) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("-")
        or "\0" in value
        or len(value.encode("utf-8", "surrogatepass")) > MAX_SESSION_BYTES
    ):
        return None
    return value


def _target(tab_id, terminal_env) -> tuple[str, str] | None:
    if not isinstance(terminal_env, dict) or not is_decimal_id(tab_id):
        return None
    session = _safe_session(terminal_env.get("ZELLIJ_SESSION_NAME"))
    if session is None:
        return None
    return session, tab_id


def _focused_panes(output: str) -> list[str]:
    lines = output.splitlines()
    if not lines or tuple(lines[0].split()[:2]) != LIST_CLIENTS_COLUMNS:
        raise RuntimeError(
            "unrecognized zellij list-clients output "
            f"(validated with zellij {VALIDATED_VERSION})"
        )
    rows = (line.split() for line in lines[1:])
    return [parts[1] for parts in rows if len(parts) >= 2]


class ZellijAPI(TerminalAPI):
    name = "zellij"
    selection_supported = True

    @staticmethod
    def detect() -> bool:
        return bool(os.environ.get("ZELLIJ"))

    @staticmethod
    def capture_env() -> dict:
        captured = bounded_env(ENV_KEYS)
        env = {
            "ZELLIJ": captured.get("ZELLIJ", ""),
            "ZELLIJ_SESSION_NAME": captured.get("ZELLIJ_SESSION_NAME", ""),
        }
        if is_decimal_id(captured.get("ZELLIJ_PANE_ID")):
            env["ZELLIJ_PANE_ID"] = captured["ZELLIJ_PANE_ID"]
        return env

    def find_tab(self, pid: int, terminal_env: dict) -> str | None:
        if not isinstance(terminal_env, dict) or not terminal_env:
            return None
        if "ZELLIJ_PANE_ID" not in terminal_env:
            raise LookupError("record predates pane capture")
        target = _target(terminal_env["ZELLIJ_PANE_ID"], terminal_env)
        return target[1] if target else None

    def find_activation_target(
        self, pid: int, terminal_env: dict, tab_id: str | None
    ) -> str | None:
        if terminal_env.get("ZELLIJ") or terminal_env.get("ZELLIJ_SESSION_NAME"):
            return str(pid)
        return None

    def switch_tab(self, tab_id: str, terminal_env: dict) -> bool:
        target = _target(tab_id, terminal_env)
        if target is None:
            return False
        session, pane = target
        command = ["zellij", "--session", session, "action"]
        expected = f"terminal_{pane}"
        if _run([*command, "focus-pane-id", expected]) is None:
            raise RuntimeError(
                f"zellij could not focus pane {pane}: CLI missing, timed out, "
                "unknown pane or unsupported version"
            )
        for attempt in range(READBACK_ATTEMPTS):
            listed = _run([*command, "list-clients"])
            if listed is None:
                raise RuntimeError("zellij list-clients readback failed")
            panes = _focused_panes(listed.stdout)
            if not panes:
                raise RuntimeError("no attached zellij client")
            if expected in panes:
                return True
            if attempt + 1 < READBACK_ATTEMPTS:
                time.sleep(READBACK_INTERVAL)
        raise RuntimeError(f"no zellij client shows pane {pane} after selection")

    def raise_window(self, tab_id: str, terminal_env: dict) -> bool:
        try:
            pid = int(tab_id)
        except (TypeError, ValueError):
            return False
        parent = tmux._detect_parent_terminal(pid)
        if parent is None:
            raise RuntimeError("no parent terminal emulator found for zellij")
        if not getattr(parent, "activation_supported", True):
            raise RuntimeError(
                f"parent terminal {parent.name} does not support window activation"
            )
        return activate_parent(parent, pid)
