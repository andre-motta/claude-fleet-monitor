"""Exercise stable tmux targets and client routing in an isolated Linux server."""

import json
import os
from pathlib import Path
import pty
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI


def alive(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


def validate():
    if sys.platform != "linux" or not shutil.which("tmux"):
        raise RuntimeError("This check requires Linux and tmux")
    clients = []
    pane_pids = []
    with tempfile.TemporaryDirectory(prefix="fleet-tmux-validation-") as temporary:
        socket = str(Path(temporary) / "socket,with-comma")
        command = ["tmux", "-S", socket, "-f", "/dev/null"]
        environment = os.environ.copy()
        environment.pop("TMUX", None)
        environment.pop("TMUX_PANE", None)
        environment["TERM"] = "xterm-256color"

        def run(*arguments, check=True):
            return subprocess.run(
                [*command, *arguments], env=environment, capture_output=True,
                text=True, timeout=5, check=check,
            ).stdout.strip()

        def pane(*arguments):
            output = run(
                *arguments, "-P", "-F",
                "#{session_id} #{window_id} #{pane_id} #{pane_pid}",
                sys.executable, "-c", "import time; time.sleep(120)",
            )
            session, window, identity, pid = output.split()
            pane_pids.append(int(pid))
            return session, window, identity, int(pid)

        def attach(session):
            pid, descriptor = pty.fork()
            if pid == 0:
                os.execvpe("tmux", [*command, "attach-session", "-t", session], environment)
            clients.append((pid, descriptor))
            deadline = time.monotonic() + 5
            while str(pid) not in run("list-clients", "-F", "#{client_pid}").splitlines():
                if not alive(pid) or time.monotonic() > deadline:
                    raise RuntimeError("Synthetic tmux client did not attach")
                time.sleep(0.05)
            return pid

        try:
            session, window, identity, pid = pane("new-session", "-d", "-s", "target")
            sibling = pane("split-window", "-d", "-t", identity)[2]
            other_window = pane("new-window", "-d", "-t", session)[1]
            other_session = pane("new-session", "-d", "-s", "unrelated")[0]
            target_client = attach(session)
            attach(other_session)
            env = {"TMUX": f"{socket},{run('display-message', '-p', '#{pid}')},{session[1:]}"}
            api = TmuxAPI()
            target = api.find_tab(pid, env)
            assert target == f"{session}:{window}.{identity}", target
            previous_index = run("display-message", "-p", "-t", identity, "#{pane_index}")
            run("swap-pane", "-d", "-s", identity, "-t", sibling)
            assert run("display-message", "-p", "-t", identity, "#{pane_index}") != previous_index
            run("rename-session", "-t", session, "renamed target")
            run("move-window", "-s", f"{session}:{window}", "-t", f"{session}:9")
            run("select-window", "-t", f"{session}:{other_window}")
            assert api.switch_tab(target, env)
            observed = run("display-message", "-p", "-t", session, "#{window_id} #{pane_id}")
            assert observed == f"{window} {identity}", observed
            assert api.find_tab(pid, env) == target
            run("link-window", "-s", f"{session}:{window}", "-t", f"{other_session}:9")
            assert api.find_tab(pid, env) == target
            assert api.find_tab(pid, {"TMUX": f"{socket},1,999999"}) is None
            assert api.switch_tab(target, env)
            unrelated_before = run(
                "list-clients", "-t", other_session, "-F",
                "#{client_pid} #{session_id} #{window_id} #{pane_id}",
            )
            calls = []

            class Parent:
                selection_supported = True

                def find_tab(self, client_pid, terminal_env):
                    calls.append(("find", client_pid))
                    return str(client_pid)

                def switch_tab(self, tab_id, terminal_env):
                    calls.append(("select", int(tab_id)))
                    return self.selected

                def raise_window(self, tab_id, terminal_env):
                    calls.append(("raise", int(tab_id)))
                    return False

            parent = Parent()
            parent.selected = True
            with patch("claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal", return_value=parent):
                assert not api.raise_window(target, env)
            assert calls == [(operation, target_client) for operation in ("find", "select", "raise")], calls
            successful_routing = list(calls)
            calls.clear()
            parent.selected = False
            with patch("claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal", return_value=parent):
                assert not api.raise_window(target, env)
            assert calls == [(operation, target_client) for operation in ("find", "select")], calls
            tty = run("list-clients", "-t", session, "-F", "#{client_tty}")
            run("detach-client", "-t", tty)
            calls.clear()
            with patch("claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal", return_value=parent):
                assert not api.raise_window(target, env)
            assert not calls, calls
            assert api.switch_tab(target, env)
            assert run(
                "list-clients", "-t", other_session, "-F",
                "#{client_pid} #{session_id} #{window_id} #{pane_id}",
            ) == unrelated_before
            run("move-pane", "-d", "-s", identity, "-t", f"{session}:{other_window}")
            assert not api.switch_tab(target, env)
            relocated = api.find_tab(pid, env)
            assert relocated == f"{session}:{other_window}.{identity}", relocated
            assert api.switch_tab(relocated, env)
            assert run("display-message", "-p", "-t", session, "#{pane_id}") == identity
            run("kill-pane", "-t", identity)
            assert not api.switch_tab(relocated, env)
            assert not api.raise_window(relocated, env)
            evidence = {
                "result": "pass", "tmux_version": run("-V"),
                "stable_target": target, "selected_window_and_pane": observed,
                "rename_and_renumber": "pass", "linked_window_session_identity": "pass",
                "pane_index_swap": "pass", "moved_pane_requires_rediscovery": "pass",
                "socket_path_with_comma": "pass", "stale_target_rejected": True,
                "detached_selection_without_parent_routing": "pass",
                "parent_selection_failure_stops_activation": True,
                "routing_operations": [operation for operation, _ in successful_routing],
                "unrelated_client_unchanged": True,
                "provenance": "real tmux server, panes and PTY clients; instrumented parent terminal",
                "gui_activation": "not exercised or claimed",
            }
        finally:
            run("kill-server", check=False)
            for client_pid, descriptor in clients:
                os.close(descriptor)
                deadline = time.monotonic() + 3
                while alive(client_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if alive(client_pid):
                    os.kill(client_pid, signal.SIGKILL)
                os.waitpid(client_pid, 0)
            deadline = time.monotonic() + 3
            while any(alive(value) for value in pane_pids) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not any(alive(value) for value in pane_pids), "Synthetic pane children survived cleanup"
            assert not Path(socket).exists() or subprocess.run(
                [*command, "list-sessions"], capture_output=True, timeout=5,
            ).returncode != 0
        evidence["cleanup"] = {"clients_exited": len(clients), "pane_children_exited": len(pane_pids)}
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    validate()
