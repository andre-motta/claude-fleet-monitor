"""Probe terminal selection capabilities with disposable, isolated instances.

Local-only Linux helper; it is never run in CI. It launches zellij and GNU
screen in private PTYs with temporary socket directories, one minimized and
one headless kitty instance with a temporary remote-control socket, and a
hidden Terminator on a private D-Bus session bus. It never edits user config,
never calls KWin, qdbus or xdotool, and only signals processes it started,
identified by PID plus kernel start time. The JSON it writes contains value
shapes and placeholders only, never home paths, user names or host names.
"""

import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import secrets
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time

TERMINALS = ("zellij", "wezterm", "kitty", "screen", "terminator")
RECOMMENDATIONS = ("adapter", "assessment-only", "none")
EVIDENCE_KINDS = ("live", "instrumented", "mocked", "inspected", "unverified")
ACTIVATION_STATES = ("verified", "blocked", "unverified")
REQUIRED_FIELDS = {
    "installed": bool,
    "version": (str, type(None)),
    "install_source": (str, type(None)),
    "env_markers": dict,
    "process_comm": dict,
    "ancestry_reaches_gui": (bool, type(None)),
    "select_argv": (list, type(None)),
    "readback_argv": (list, type(None)),
    "readback_proven": bool,
    "multi_client_behavior": str,
    "pid_only_find_tab": dict,
    "activation_readback": dict,
    "version_floor": str,
    "recommendation": str,
    "evidence_kind": str,
}
MARKER_NAMES = (
    "TMUX", "TMUX_PANE", "STY", "WINDOW", "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
    "VTE_VERSION", "GNOME_TERMINAL_SERVICE", "GNOME_TERMINAL_SCREEN",
    "ITERM_SESSION_ID", "WT_SESSION", "WINDOWID",
)
MARKER_PREFIXES = ("ZELLIJ", "KONSOLE_", "GHOSTTY_", "TERMINATOR_", "KITTY_", "WEZTERM_")
OPAQUE_MARKERS = ("KITTY_PUBLIC_KEY", "KONSOLE_DBUS_ACTIVATION_COOKIE")
NO_KWIN = "not exercised: the probe makes no KWin, qdbus or xdotool calls (CTO decision)"
COMMAND_TIMEOUT = 5
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX_RE = re.compile(r"[0-9a-f]{16,}")
DIGITS_RE = re.compile(r"\d+")


class Redactor:
    """Replace private strings with stable placeholders, longest first."""

    def __init__(self, replacements):
        self.pairs = sorted(
            ((value, label) for value, label in replacements.items() if value),
            key=lambda pair: len(pair[0]), reverse=True,
        )

    @classmethod
    def for_host(cls, extra=None):
        replacements = dict(extra or {})
        replacements[f"/run/user/{os.getuid()}"] = "<runtime_dir>"
        replacements[str(Path.home())] = "<home>"
        try:
            replacements[getpass.getuser()] = "<user>"
        except (KeyError, OSError):
            pass
        replacements[socket.gethostname()] = "<host>"
        return cls(replacements)

    def __call__(self, text):
        if text is None:
            return None
        text = str(text)
        for value, label in self.pairs:
            text = text.replace(value, label)
        return text

    def leaks(self, text):
        return [label for value, label in self.pairs if value in text]


def value_shape(value, redact):
    """Describe a marker value without its private or volatile content."""
    shape = UUID_RE.sub("<uuid>", redact(value))
    shape = HEX_RE.sub("<hex>", shape)
    return DIGITS_RE.sub("<digits>", shape)


def is_marker(name):
    return name in MARKER_NAMES or name.startswith(MARKER_PREFIXES)


def describe_markers(child_env, own, launcher_env, redact, probe_set=()):
    own_markers = {}
    for name in own:
        if name not in child_env:
            continue
        if name in OPAQUE_MARKERS:
            shape = "<opaque>"
        else:
            shape = value_shape(child_env[name], redact)
        own_markers[name] = {"shape": shape, "length": len(child_env[name])}
    foreign = sorted(
        name for name in child_env
        if is_marker(name) and name not in own and name not in probe_set
    )
    return {
        "own": own_markers,
        "probe_set": sorted(name for name in probe_set if name in child_env),
        "foreign_markers_in_child": foreign,
        "leaked_from_launcher": [
            name for name in foreign if launcher_env.get(name) == child_env[name]
        ],
        "launcher_terminal": "konsole" if launcher_env.get("KONSOLE_VERSION") else "other",
    }


def validate_record(record):
    """Return schema errors for a probe record; empty means valid."""
    errors = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for terminal in TERMINALS:
        entry = record.get(terminal)
        if not isinstance(entry, dict):
            errors.append(f"{terminal}: missing")
            continue
        for field, kind in REQUIRED_FIELDS.items():
            if field not in entry:
                errors.append(f"{terminal}.{field}: missing")
            elif not isinstance(entry[field], kind):
                errors.append(f"{terminal}.{field}: wrong type")
        if entry.get("recommendation") not in RECOMMENDATIONS:
            errors.append(f"{terminal}.recommendation: invalid")
        if entry.get("evidence_kind") not in EVIDENCE_KINDS:
            errors.append(f"{terminal}.evidence_kind: invalid")
        activation = entry.get("activation_readback")
        if not isinstance(activation, dict) or activation.get("status") not in ACTIVATION_STATES \
                or not isinstance(activation.get("method"), str):
            errors.append(f"{terminal}.activation_readback: invalid")
        pid_only = entry.get("pid_only_find_tab")
        if not isinstance(pid_only, dict) or not isinstance(pid_only.get("viable"), bool) \
                or not isinstance(pid_only.get("method"), str):
            errors.append(f"{terminal}.pid_only_find_tab: invalid")
        for field in ("select_argv", "readback_argv"):
            value = entry.get(field)
            if isinstance(value, list) and not all(isinstance(item, str) for item in value):
                errors.append(f"{terminal}.{field}: non-string item")
        if entry.get("installed") is False and entry.get("readback_proven"):
            errors.append(f"{terminal}: readback proven while not installed")
        if entry.get("readback_proven") is False and entry.get("recommendation") == "adapter":
            errors.append(f"{terminal}: adapter recommended without proven readback")
    return errors


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    except (OSError, IndexError):
        return None
    return None if fields[0] == "Z" else fields[19]


def process_facts(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
    except (OSError, IndexError):
        return None
    try:
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        exe = None
    return {"comm": comm, "exe": exe, "ppid": int(fields[1]), "sid": int(fields[4])}


def process_cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", "replace")
    except OSError:
        return ""


def process_cwd(pid):
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def ancestry(pid, stop_pid, limit=8):
    chain = []
    current = pid
    for _ in range(limit):
        facts = process_facts(current)
        if facts is None:
            break
        chain.append({"pid": current, "comm": facts["comm"], "exe": facts["exe"]})
        if facts["ppid"] in (0, 1, stop_pid):
            break
        current = facts["ppid"]
    return chain


def public_chain(chain, roles):
    return [{"comm": item["comm"], "exe": item["exe"], "role": roles.get(item["pid"], "other")}
            for item in chain]


def run(argv, env=None, cwd=None, timeout=COMMAND_TIMEOUT):
    """Run a command; never raise. Returns (returncode or None, stdout, stderr)."""
    try:
        result = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, "", type(error).__name__
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def wait_until(predicate, timeout, step=0.1):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(step)


def read_env_file(path):
    env = {}
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return env
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            env[name] = value
    return env


def read_pid(path):
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def install_info(binary):
    path = shutil.which(binary)
    if not path:
        return None, None
    code, out, _ = run(["rpm", "-qf", path])
    if code == 0 and out and "not owned" not in out:
        return path, f"rpm {out.splitlines()[0]}"
    return path, f"unpackaged binary at {path}"


class Tracker:
    """Owned process registry keyed by PID and kernel start time."""

    def __init__(self, markers):
        self.markers = [marker for marker in markers if marker]
        self.owned = {}
        self.direct = []
        self.fds = []

    def add(self, pid, label):
        if pid and pid not in self.owned:
            birth = process_identity(pid)
            if birth is not None:
                self.owned[pid] = (birth, label)

    def alive(self):
        return [pid for pid, (birth, _) in self.owned.items() if process_identity(pid) == birth]

    def label(self, pid):
        return self.owned.get(pid, (None, "other"))[1]

    def sweep(self):
        """Adopt descendants of owned processes and anything naming a probe marker."""
        me = os.getpid()
        changed = True
        while changed:
            changed = False
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                if pid == me or pid in self.owned:
                    continue
                facts = process_facts(pid)
                if facts is None:
                    continue
                if facts["ppid"] in self.owned or any(
                        marker in process_cmdline(pid) for marker in self.markers):
                    self.add(pid, "adopted")
                    changed = pid in self.owned or changed

    def stray(self):
        me = os.getpid()
        found = []
        for entry in os.listdir("/proc"):
            if entry.isdigit() and int(entry) != me and process_identity(int(entry)) is not None:
                command = process_cmdline(int(entry))
                if any(marker in command for marker in self.markers):
                    found.append(int(entry))
        return found

    def terminate(self):
        self.sweep()
        for action in (signal.SIGTERM, signal.SIGKILL):
            for pid in self.alive():
                try:
                    os.kill(pid, action)
                except OSError:
                    pass
            wait_until(lambda: not self.alive(), 3, 0.05)
        for descriptor in self.fds:
            try:
                os.close(descriptor)
            except OSError:
                pass
        unreaped = []
        for pid in self.direct:
            def reaped(pid=pid):
                try:
                    done, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    return True
                return bool(done)
            if not wait_until(reaped, 3, 0.05):
                unreaped.append(pid)
        return {
            "tracked": len(self.owned),
            "survivors": len(self.alive()) + len(unreaped),
            "marker_strays": len(self.stray()),
        }


class PtyClient:
    """A terminal client in a private PTY whose output is continuously drained."""

    def __init__(self, argv, env, cwd, tracker, label):
        pid, descriptor = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd)
                os.execvpe(argv[0], argv, env)
            finally:
                os._exit(127)
        self.pid = pid
        self.fd = descriptor
        fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        tracker.add(pid, label)
        tracker.direct.append(pid)
        tracker.fds.append(descriptor)
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            try:
                if not os.read(self.fd, 65536):
                    return
            except OSError:
                return

    def type_line(self, text):
        os.write(self.fd, (text + "\r").encode())


def input_script(directory, id_variable):
    script = Path(directory) / f"target-{id_variable.lower()}.sh"
    script.write_text(
        f'd="{directory}"; i="${{{id_variable}}}"\n'
        'env > "$d/env-$i.tmp" && mv "$d/env-$i.tmp" "$d/env-$i"\n'
        'echo $$ > "$d/pid-$i.tmp" && mv "$d/pid-$i.tmp" "$d/pid-$i"\n'
        'while IFS= read -r line; do printf "%s\\n" "$line" >> "$d/in-$i"; done\n'
    )
    return str(script)


def receivers(directory, word):
    found = []
    for path in sorted(Path(directory).glob("in-*")):
        try:
            if word in path.read_text().split():
                found.append(path.name[3:])
        except OSError:
            pass
    return found


def typed_target(client, directory, word):
    client.type_line(word)
    return wait_until(lambda: receivers(directory, word), 3) or []


class Context:
    def __init__(self, root, token, redact):
        self.root = root
        self.token = token
        self.redact = redact
        self.launcher_env = dict(os.environ)

    def base_env(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("ZELLIJ", "TMUX", "KITTY_", "WEZTERM_", "TERMINATOR_"))
               and key not in ("STY", "WINDOW")}
        env["TERM"] = "xterm-256color"
        return env


def not_installed_record(reason, candidate=None):
    return {
        "installed": False, "version": None, "install_source": None, "env_markers": {},
        "process_comm": {}, "ancestry_reaches_gui": None, "select_argv": None,
        "readback_argv": None, "readback_proven": False,
        "multi_client_behavior": "not probed", "pid_only_find_tab": {
            "viable": False, "method": "not probed"},
        "activation_readback": {"status": "unverified", "method": "not probed"},
        "version_floor": "not probed", "recommendation": "none",
        "evidence_kind": "unverified", "reason": reason, "candidate_commands": candidate,
    }


def probe_zellij(ctx):
    path, source = install_info("zellij")
    if not path:
        return not_installed_record("zellij not found on PATH")
    work = ctx.root / "zellij"
    for name in ("sock", "cfg", "cache", "data", "cwd", "io"):
        (work / name).mkdir(parents=True, mode=0o700)
    session = f"{ctx.token}-zellij"
    sockets = work / "sock"
    tracker = Tracker([str(work), session])
    env = ctx.base_env()
    env.update({
        "ZELLIJ_SOCKET_DIR": str(sockets), "ZELLIJ_CONFIG_DIR": str(work / "cfg"),
        "XDG_CACHE_HOME": str(work / "cache"), "XDG_DATA_HOME": str(work / "data"),
    })
    (work / "cfg" / "config.kdl").write_text(
        "show_startup_tips false\nshow_release_notes false\nsession_serialization false\n")
    script = input_script(work / "io", "ZELLIJ_PANE_ID")
    cwd = str(work / "cwd")
    pane = f'pane name="dup" cwd="{cwd}" command="sh" {{ args "{script}"; }}'
    layout = work / "layout.kdl"
    layout.write_text(
        f'layout {{\n tab name="dup" {{\n  {pane}\n  {pane}\n }}\n'
        f' tab name="dup" {{\n  {pane}\n }}\n}}\n')
    version = run(["zellij", "--version"])[1]
    record = {
        "installed": True, "version": version or None, "install_source": source,
        "select_argv": ["zellij", "--session", "<session>", "action", "focus-pane-id",
                        "terminal_<ZELLIJ_PANE_ID>"],
        "readback_argv": ["zellij", "--session", "<session>", "action", "list-clients"],
        "version_floor": (
            "not established: 0.45.1 is the only version probed; it provides "
            "action focus-pane-id, list-clients with a ZELLIJ_PANE_ID column, list-panes "
            "and dump-layout. Treat a nonzero exit or unknown subcommand as unavailable."),
    }
    observations = {}

    def action(*arguments):
        return run(["zellij", "--session", session, "action", *arguments], env=env)

    def clients():
        code, out, _ = action("list-clients")
        if code != 0:
            return None
        lines = out.splitlines()
        rows = {}
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2:
                rows[parts[0]] = parts[1]
        return {"header": lines[0].split() if lines else [], "rows": rows}

    try:
        first = PtyClient(["zellij", "--config-dir", str(work / "cfg"), "--session", session,
                           "--new-session-with-layout", str(layout)],
                          env, cwd, tracker, "client")
        ready = wait_until(lambda: all((work / "io" / f"pid-{i}").exists() for i in "012")
                           and clients(), 20)
        if not ready:
            raise RuntimeError("zellij session did not become ready")
        tracker.sweep()
        server = next((pid for pid in tracker.owned
                       if "--server" in process_cmdline(pid)), None)
        panes = {i: read_pid(work / "io" / f"pid-{i}") for i in "012"}
        roles = {first.pid: "client", server: "server"}
        for index, pid in panes.items():
            tracker.add(pid, "pane")
            roles[pid] = "pane shell"
        child_env = read_env_file(work / "io" / "env-0")
        record["env_markers"] = describe_markers(
            child_env, ("ZELLIJ", "ZELLIJ_PANE_ID", "ZELLIJ_SESSION_NAME"),
            ctx.launcher_env, Redactor({**dict(ctx.redact.pairs), session: "<session>"}),
            probe_set=("ZELLIJ_SOCKET_DIR", "ZELLIJ_CONFIG_DIR"))
        chain = ancestry(panes["0"], os.getpid())
        server_facts = process_facts(server) if server else None
        client_facts = process_facts(first.pid)
        parent_of_server = process_facts(server_facts["ppid"]) if server_facts else None
        record["process_comm"] = {
            "gui": None,
            "server": {"comm": server_facts["comm"], "exe": server_facts["exe"]}
            if server_facts else None,
            "client": {"comm": client_facts["comm"], "exe": client_facts["exe"]}
            if client_facts else None,
        }
        record["ancestry"] = public_chain(chain, roles)
        record["ancestry_reaches_gui"] = any(item["pid"] == first.pid for item in chain)
        observations["server_daemonized"] = bool(
            server_facts and client_facts and server_facts["ppid"] != first.pid
            and server_facts["sid"] != client_facts["sid"])
        observations["server_parent_comm"] = parent_of_server["comm"] if parent_of_server else None
        code, out, _ = action("list-panes", "-a", "-j")
        listed = json.loads(out) if code == 0 and out else []
        terminal_panes = [item for item in listed if not item.get("is_plugin")]
        observations["duplicate_targets"] = {
            "titles": sorted({item.get("title") for item in terminal_panes}),
            "terminal_panes": len(terminal_panes),
            "same_cwd": len({process_cwd(pid) for pid in panes.values()}) == 1,
            "list_panes_has_pid_field": any("pid" in key for item in listed for key in item),
        }
        observations["pane_id_env_is_decimal"] = all(
            read_env_file(work / "io" / f"env-{i}").get("ZELLIJ_PANE_ID") == i for i in "012")
        header = clients()["header"]
        observations["list_clients_columns"] = header

        steps = []

        def select(target, typed_clients, bare=False):
            code, _, err = action("focus-pane-id", target if bare else f"terminal_{target}")
            time.sleep(0.5)
            listed_clients = clients() or {"rows": {}}
            routed = {name: typed_target(client, work / "io", f"{name}-{target}-{len(steps)}")
                      for name, client in typed_clients}
            step = {"target": target, "exit": code, "list_clients": listed_clients["rows"],
                    "keystrokes_routed_to": routed}
            steps.append(step)
            return step

        no_input = select("1", [])
        observations["one_client_before_any_input"] = {
            "exit": no_input["exit"], "client_pane": no_input["list_clients"],
            "moved": no_input["list_clients"].get("1") == "terminal_1",
        }
        routed = typed_target(first, work / "io", "warmup")
        observations["one_client_before_any_input"]["keystroke_pane_after"] = routed
        one_client = []
        for target, bare in (("1", False), ("2", False), ("0", True), ("1", False)):
            step = select(target, [("c1", first)], bare)
            one_client.append({
                "target": target, "argument": target if bare else f"terminal_{target}",
                "exit": step["exit"],
                "list_clients_matches": step["list_clients"].get("1") == f"terminal_{target}",
                "keystroke_matches": step["keystrokes_routed_to"]["c1"] == [target],
            })
        observations["one_client"] = one_client
        record["readback_proven"] = all(
            item["exit"] == 0 and item["list_clients_matches"] and item["keystroke_matches"]
            for item in one_client)
        code, _, err = action("focus-pane-id", "terminal_99")
        observations["error_unknown_pane"] = {"exit": code, "stderr": ctx.redact(err)[:160]}
        code, _, err = action("focus-pane-id", "x1")
        observations["error_malformed_pane"] = {"exit": code, "stderr": ctx.redact(err)[:200]}

        second = PtyClient(["zellij", "--config-dir", str(work / "cfg"), "attach", session],
                           env, cwd, tracker, "client")
        wait_until(lambda: len((clients() or {"rows": {}})["rows"]) == 2, 10)
        two_client = []
        for order, target in (((second, first), "2"), ((first, second), "0")):
            for client in order:
                typed_target(client, work / "io", f"prime-{target}-{client.pid}")
            last = "c1" if order[-1] is first else "c2"
            step = select(target, [("c1", first), ("c2", second)])
            moved = sorted(name for name in ("c1", "c2")
                           if step["keystrokes_routed_to"][name] == [target])
            two_client.append({
                "target": target, "last_input_client": last, "exit": step["exit"],
                "list_clients": step["list_clients"], "clients_moved": moved,
            })
        observations["two_clients"] = two_client
        last_input_rule = all(item["clients_moved"] == [item["last_input_client"]]
                              for item in two_client)
        for client in (first, second):
            try:
                os.kill(client.pid, signal.SIGTERM)
            except OSError:
                pass
        wait_until(lambda: not (clients() or {"rows": {1: 1}})["rows"], 5)
        code, _, _ = action("focus-pane-id", "terminal_2")
        zero = clients()
        observations["zero_clients"] = {
            "focus_exit": code, "list_clients_rows": zero["rows"] if zero else None,
            "session_survives": session in run(["zellij", "list-sessions", "-n"], env=env)[1],
        }
        no_input_note = (
            "before any client sends input the action moved no attached client"
            if not observations["one_client_before_any_input"]["moved"]
            else "before any client input the action moved the attached client")
        record["multi_client_behavior"] = (
            ("focus-pane-id applies only to the most recently active client (the last one "
             "that sent input); other clients keep their own focused pane; "
             if last_input_rule else "inconsistent client targeting, see observations; ")
            + no_input_note
            + "; with zero clients the action exits "
            + str(observations["zero_clients"]["focus_exit"])
            + " and list-clients has no rows, so selection cannot be read back")
        record["pid_only_find_tab"] = {
            "viable": False,
            "method": ("not viable through the CLI: list-panes and list-clients expose no "
                       "PIDs. The session name is recoverable on Linux from the server argv "
                       "(--server <socket dir>/<contract>/<session>) reached by ancestry, but "
                       "the pane ID needs ZELLIJ_PANE_ID from the captured env (or "
                       "/proc/<pid>/environ, Linux only)"),
        }
        observations["client_pid_discoverable"] = (
            "no: list-clients reports CLIENT_ID only; the pane ancestry reaches the "
            "daemonized server, never the client; an argv scan finds clients only when "
            "the session name is on their command line")
        record["activation_readback"] = {
            "status": "blocked",
            "method": ("no GUI window: zellij ran in a private PTY and the pane ancestry ends "
                       "at the daemonized server, so the emulator hosting a client is not "
                       "reachable from the agent PID; " + NO_KWIN),
        }
    except Exception as error:
        observations["error"] = ctx.redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        run(["zellij", "kill-session", session], env=env)
        record["cleanup"] = tracker.terminate()
    record["observations"] = observations
    record.setdefault("readback_proven", False)
    record.setdefault("env_markers", {})
    record.setdefault("process_comm", {})
    record.setdefault("ancestry_reaches_gui", None)
    record.setdefault("multi_client_behavior", "not established, see observations.error")
    record.setdefault("pid_only_find_tab", {"viable": False, "method": "not established"})
    record.setdefault("activation_readback", {"status": "unverified", "method": NO_KWIN})
    record["recommendation"] = "adapter" if record["readback_proven"] else "assessment-only"
    record["evidence_kind"] = "live" if "error" not in observations else "unverified"
    record["provenance"] = ("live: real zellij server and two PTY clients with an isolated "
                            "socket dir; readback by list-clients plus keystroke routing")
    return record


def probe_screen(ctx):
    path, source = install_info("screen")
    if not path:
        return not_installed_record("screen not found on PATH")
    work = ctx.root / "screen"
    for name in ("sockets", "cwd", "io"):
        (work / name).mkdir(parents=True, mode=0o700)
    session = f"{ctx.token}-screen"
    tracker = Tracker([str(work), session])
    rc = work / "screenrc"
    rc.write_text("startup_message off\n")
    env = ctx.base_env()
    env["SCREENDIR"] = str(work / "sockets")
    script = input_script(work / "io", "WINDOW")
    cwd = str(work / "cwd")
    version = run(["screen", "--version"])[1].split("(")[0].strip()
    record = {
        "installed": True, "version": version or None, "install_source": source,
        "select_argv": ["screen", "-S", "<STY>", "-X", "select", "<WINDOW>"],
        "readback_argv": ["screen", "-S", "<STY>", "-Q", "number"],
        "version_floor": ("not established: 5.0.1 is the only version probed; the -Q query "
                          "option is required for readback"),
    }
    observations = {}

    def screen(*arguments):
        return run(["screen", "-c", str(rc), "-S", session, *arguments], env=env, cwd=cwd)

    def number():
        code, out, _ = screen("-Q", "number")
        token = out.split()[0] if code == 0 and out else ""
        return token if token.isdigit() else None

    try:
        code, _, _ = run(["screen", "-c", str(rc), "-dmS", session, "-t", "dup", "sh", script],
                         env=env, cwd=cwd)
        if code != 0:
            raise RuntimeError("screen -dmS failed")
        wait_until(lambda: (work / "io" / "pid-0").exists(), 10)
        for _ in range(2):
            screen("-X", "screen", "-t", "dup", "sh", script)
        if not wait_until(lambda: all((work / "io" / f"pid-{i}").exists() for i in "012"), 10):
            raise RuntimeError("screen windows did not start")
        tracker.sweep()
        windows = {i: read_pid(work / "io" / f"pid-{i}") for i in "012"}
        server = process_facts(windows["0"])["ppid"]
        tracker.add(server, "server")
        roles = {server: "server"}
        for pid in windows.values():
            tracker.add(pid, "window")
            roles[pid] = "window shell"
        child_env = read_env_file(work / "io" / "env-0")
        redact = Redactor({**dict(ctx.redact.pairs), session: "<session>"})
        record["env_markers"] = describe_markers(
            child_env, ("STY", "WINDOW"), ctx.launcher_env, redact)
        record["env_markers"]["term_in_child"] = child_env.get("TERM")
        chain = ancestry(windows["0"], os.getpid())
        server_facts = process_facts(server)
        record["ancestry"] = public_chain(chain, roles)
        observations["server_argv0"] = process_cmdline(server).split(" ", 1)[0]
        observations["binary_setgid"] = bool(os.stat(path).st_mode & stat.S_ISGID)
        observations["exe_link_readable"] = server_facts["exe"] is not None
        observations["server_daemonized"] = server_facts["ppid"] != os.getpid()
        observations["server_parent_comm"] = (process_facts(server_facts["ppid"]) or {}).get("comm")
        sty = child_env.get("STY", "")
        observations["sty_matches_adapter_pattern"] = bool(re.fullmatch(r"\d+\.[^\s/]+", sty))
        observations["sty_pid_is_server"] = sty.split(".", 1)[0] == str(server)
        observations["duplicate_targets"] = {
            "same_cwd": len({process_cwd(pid) for pid in windows.values()}) == 1}

        zero_before = number()
        code, _, _ = screen("-X", "select", "0")
        zero_after = number()
        observations["zero_displays"] = {
            "select_exit": code, "number_before": zero_before, "number_after": zero_after,
            "selection_took_effect": zero_after == "0",
            "windows_query": screen("-Q", "windows")[1] or "",
        }
        first = PtyClient(["screen", "-c", str(rc), "-x", session], env, cwd, tracker, "display")
        wait_until(lambda: screen("-Q", "windows")[1], 10)
        titles = re.findall(r"\d+\S*\s+(\S+)", screen("-Q", "windows")[1])
        observations["duplicate_targets"]["titles"] = sorted(set(titles))
        observations["duplicate_targets"]["windows"] = len(titles)
        one_display = []
        for target in ("1", "0", "2"):
            code, _, _ = screen("-X", "select", target)
            time.sleep(0.2)
            read = number()
            routed = typed_target(first, work / "io", f"d1-{target}")
            one_display.append({"target": target, "exit": code, "number": read,
                                "keystroke_window": routed,
                                "matches": read == target and routed == [target]})
        observations["one_display"] = one_display
        record["readback_proven"] = all(item["exit"] == 0 and item["matches"]
                                        for item in one_display)
        code, _, err = screen("-X", "select", "9")
        observations["error_unknown_window"] = {
            "exit": code, "stderr": ctx.redact(err)[:160], "number_after": number(),
        }
        second = PtyClient(["screen", "-c", str(rc), "-x", session], env, cwd, tracker,
                           "display")
        time.sleep(1.0)
        two_display = []
        for order, target in (((second, first), "1"), ((first, second), "0")):
            for display in order:
                typed_target(display, work / "io", f"prime-{target}-{display.pid}")
            last = "d1" if order[-1] is first else "d2"
            code, _, _ = screen("-X", "select", target)
            time.sleep(0.2)
            read = number()
            routed = {name: typed_target(display, work / "io", f"{name}-two-{target}")
                      for name, display in (("d1", first), ("d2", second))}
            two_display.append({
                "target": target, "last_input_display": last, "exit": code, "number": read,
                "displays_moved": sorted(name for name, got in routed.items() if got == [target]),
            })
        observations["two_displays"] = two_display
        newest_rule = all(item["displays_moved"] == ["d2"] for item in two_display)
        last_input_rule = all(item["displays_moved"] == [item["last_input_display"]]
                              for item in two_display)
        readback_agrees = all(item["number"] == item["target"] for item in two_display)
        if newest_rule:
            rule = ("-X select and -Q number both act on the most recently attached display "
                    "only, whichever display last received input")
        elif last_input_rule:
            rule = ("-X select and -Q number act on the display that last received input")
        else:
            rule = "display targeting inconsistent, see observations.two_displays"
        record["multi_client_behavior"] = (
            f"{rule}; -Q number {'agrees' if readback_agrees else 'disagrees'} with the "
            "selected window of that display, so equality cannot prove what another "
            "display shows; with zero displays select exits "
            f"{observations['zero_displays']['select_exit']} and changes nothing, and "
            "-Q number still answers with the stale window")
        record["process_comm"] = {
            "gui": None,
            "server": {"comm": server_facts["comm"], "exe": server_facts["exe"]},
            "client": {"comm": (process_facts(first.pid) or {}).get("comm"),
                       "exe": (process_facts(first.pid) or {}).get("exe")},
        }
        record["ancestry_reaches_gui"] = any(item["pid"] in (first.pid, second.pid)
                                             for item in chain)
        record["pid_only_find_tab"] = {
            "viable": False,
            "method": ("partly: on Linux the ancestry from the agent reaches the SCREEN "
                       "server, whose PID prefixes STY in screen -ls, so the session is "
                       "recoverable; the window number has no CLI mapping from a PID and "
                       "needs WINDOW from the captured env (or /proc/<pid>/environ)"),
        }
        record["activation_readback"] = {
            "status": "blocked",
            "method": ("no GUI window: screen ran in private PTYs and window shells descend "
                       "from the daemonized SCREEN server, not from a display client; "
                       + NO_KWIN),
        }
    except Exception as error:
        observations["error"] = ctx.redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        screen("-X", "quit")
        record["cleanup"] = tracker.terminate()
    record["observations"] = observations
    record.setdefault("readback_proven", False)
    record.setdefault("env_markers", {})
    record.setdefault("process_comm", {})
    record.setdefault("ancestry_reaches_gui", None)
    record.setdefault("multi_client_behavior", "not established, see observations.error")
    record.setdefault("pid_only_find_tab", {"viable": False, "method": "not established"})
    record.setdefault("activation_readback", {"status": "unverified", "method": NO_KWIN})
    record["recommendation"] = "adapter" if record["readback_proven"] else "assessment-only"
    record["evidence_kind"] = "live" if "error" not in observations else "unverified"
    record["provenance"] = ("live: real SCREEN server and PTY displays with an isolated "
                            "SCREENDIR; readback by -Q number plus keystroke routing")
    return record


def kitty_tree(listing):
    found = {}
    for os_window in listing:
        for tab in os_window.get("tabs", []):
            for window in tab.get("windows", []):
                found[window["id"]] = (os_window, tab, window)
    return found


def probe_kitty(ctx):
    path, source = install_info("kitty")
    if not path or not shutil.which("kitten"):
        return not_installed_record("kitty or kitten not found on PATH")
    work = ctx.root / "kitty"
    for name in ("cfg", "cache", "cwd", "io", "headless"):
        (work / name).mkdir(parents=True, mode=0o700)
    tracker = Tracker([str(work)])
    address = f"unix:{work}/rc.sock"
    env = ctx.base_env()
    env.update({"KITTY_CONFIG_DIRECTORY": str(work / "cfg"),
                "KITTY_CACHE_DIRECTORY": str(work / "cache")})
    io = work / "io"
    script = Path(io) / "target.sh"
    script.write_text(
        f'd="{io}"; i="$KITTY_WINDOW_ID"\n'
        'env > "$d/env-$i.tmp" && mv "$d/env-$i.tmp" "$d/env-$i"\n'
        'echo $$ > "$d/pid-$i.tmp" && mv "$d/pid-$i.tmp" "$d/pid-$i"\n'
        'if [ "$i" = 1 ]; then env -u KITTY_LISTEN_ON timeout -k 1 3 kitten @ ls '
        '> "$d/tty.out" 2>&1; echo "exit=$?" >> "$d/tty.out"; fi\n'
        'exec sleep 300\n')
    cwd = str(work / "cwd")
    version = run(["kitty", "--version"])[1]
    version = " ".join(version.split()[:2]) if version else None
    record = {
        "installed": True, "version": version, "install_source": source,
        "select_argv": ["kitten", "@", "--to", "<KITTY_LISTEN_ON>", "focus-window",
                        "--match", "id:<KITTY_WINDOW_ID>"],
        "readback_argv": ["kitten", "@", "--to", "<KITTY_LISTEN_ON>", "ls"],
        "multi_client_behavior": (
            "single GUI process per instance and no attached-client concept; remote control "
            "clients are stateless; selection changes the active tab and window of the one "
            "instance named by KITTY_LISTEN_ON"),
        "version_floor": ("not established: 0.47.1 is the only version probed; needs remote "
                          "control enabled (allow_remote_control socket-only or yes) and "
                          "listen_on"),
    }
    observations = {}

    def kitten(*arguments, to=address):
        return run(["kitten", "@", "--to", to, *arguments], env=env)

    def listing(to=address):
        code, out, _ = kitten("ls", to=to)
        try:
            return json.loads(out) if code == 0 else None
        except ValueError:
            return None

    try:
        process = subprocess.Popen(
            ["kitty", "--config", "NONE", "-o", "allow_remote_control=socket-only",
             "-o", "confirm_os_window_close=0", "--listen-on", address,
             "--class", f"{ctx.token}-kitty", "--start-as=minimized", "--directory", cwd,
             "sh", str(script)],
            env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        tracker.add(process.pid, "gui")
        tracker.direct.append(process.pid)
        if not wait_until(lambda: listing() and (io / "pid-1").exists(), 20):
            raise RuntimeError("kitty remote control did not become ready")
        code, out, _ = kitten("launch", "--type=tab", "--title", "dup", "--cwd", cwd,
                              "sh", str(script))
        second_id = int(out) if code == 0 and out.isdigit() else None
        kitten("set-window-title", "--match", "id:1", "dup")
        kitten("set-tab-title", "--match", "id:1", "dup")
        if not second_id or not wait_until(lambda: (io / f"pid-{second_id}").exists(), 10):
            raise RuntimeError("second kitty window did not start")
        targets = {"1": 1, str(second_id): second_id}
        shells = {key: read_pid(io / f"pid-{key}") for key in targets}
        roles = {process.pid: "gui"}
        for pid in shells.values():
            tracker.add(pid, "window shell")
            roles[pid] = "window shell"
        child_env = read_env_file(io / "env-1")
        redact = Redactor({**dict(ctx.redact.pairs), address[5:]: "<socket>"})
        record["env_markers"] = describe_markers(
            child_env, ("KITTY_WINDOW_ID", "KITTY_PID", "KITTY_LISTEN_ON", "KITTY_PUBLIC_KEY",
                        "KITTY_INSTALLATION_DIR"), ctx.launcher_env, ctx.redact,
            probe_set=("KITTY_CONFIG_DIRECTORY", "KITTY_CACHE_DIRECTORY"))
        record["env_markers"]["term_in_child"] = child_env.get("TERM")
        listen = child_env.get("KITTY_LISTEN_ON", "")
        observations["listen_on_equals_given_address"] = listen == address
        observations["listen_on_shape"] = redact(listen)
        observations["listen_on_length"] = len(listen)
        observations["kitty_pid_env_is_gui"] = child_env.get("KITTY_PID") == str(process.pid)
        chain = ancestry(shells["1"], os.getpid())
        record["ancestry"] = public_chain(chain, roles)
        record["ancestry_reaches_gui"] = any(item["pid"] == process.pid for item in chain)
        gui = process_facts(process.pid)
        record["process_comm"] = {"gui": {"comm": gui["comm"], "exe": gui["exe"]},
                                  "server": None, "client": None}
        tree = kitty_tree(listing())
        observations["duplicate_targets"] = {
            "titles": sorted({tree[i][2]["title"] for i in targets.values()}),
            "same_cwd": len({tree[i][2]["cwd"] for i in targets.values()}) == 1,
            "separate_tabs": tree[1][1]["id"] != tree[second_id][1]["id"],
        }
        selections = []
        for key in ("1", str(second_id), "1"):
            code, _, _ = kitten("focus-window", "--match", f"id:{targets[key]}")
            time.sleep(0.3)
            tree = kitty_tree(listing() or [])
            os_window, tab, window = tree[targets[key]]
            others = [entry for wid, entry in tree.items() if wid != targets[key]]
            selections.append({
                "target": key, "exit": code,
                "target_tab_active": tab["is_active"], "target_window_active": window["is_active"],
                "other_tabs_active": [entry[1]["is_active"] for entry in others],
                "os_window_is_focused": os_window.get("is_focused"),
                "target_window_is_focused": window.get("is_focused"),
            })
        observations["selections"] = selections
        record["readback_proven"] = all(
            item["exit"] == 0 and item["target_tab_active"] and item["target_window_active"]
            and not any(item["other_tabs_active"]) for item in selections)
        observations["inactive_readback"] = (
            "tab and window is_active followed every selection; the OS window started "
            "minimized reported is_focused "
            + str(sorted({item["os_window_is_focused"] for item in selections}, key=str))
            + ", which the probe cannot attribute to KWin without a KWin call; selection "
            "readback should use is_active and never treat is_focused as activation proof")
        code, out, _ = kitten("ls", "--match", f"pid:{shells['1']}")
        matched = kitty_tree(json.loads(out)) if code == 0 and out else {}
        observations["ls_match_pid"] = {"exit": code, "window_ids": sorted(matched)}
        record["pid_only_find_tab"] = {
            "viable": False,
            "method": ("not viable with an empty env: the socket address comes only from "
                       "KITTY_LISTEN_ON. With the address, ls --match pid:<shell pid> "
                       "returned window ids " + str(sorted(matched))
                       + ", and ls lists each window's pid and foreground_processes"),
        }
        code, _, err = kitten("focus-window", "--match", "id:99999")
        observations["error_unknown_window"] = {"exit": code, "stderr": redact(err)[:160]}
        missing = f"unix:{work}/missing.sock"
        code, _, err = kitten("ls", to=missing)
        observations["error_missing_socket"] = {
            "exit": code,
            "stderr": Redactor({**dict(ctx.redact.pairs), missing[5:]: "<socket>"})(err)[:200]}
        wait_until(lambda: "exit=" in (io / "tty.out").read_text()
                   if (io / "tty.out").exists() else False, 8)
        tty_text = (io / "tty.out").read_text() if (io / "tty.out").exists() else ""
        tty_exit = re.search(r"exit=(\d+)", tty_text)
        observations["error_tty_route_with_socket_only"] = {
            "exit": int(tty_exit.group(1)) if tty_exit else None,
            "output": redact(tty_text.replace(tty_exit.group(0), "") if tty_exit
                             else tty_text).strip()[-240:],
            "meaning": ("kitten @ without --to inside a socket-only window; exit 124 or 137 "
                        "means it hung until timeout killed it, with no error text"),
        }
        observations["error_remote_control_off"] = (
            "inferred, not run: kitty ignores listen_on unless allow_remote_control is "
            "socket, socket-only or yes, so --to then fails with the missing-socket shape")
        record["activation_readback"] = {
            "status": "unverified",
            "method": ("kitty activation reported unverified by CTO decision; focus-window "
                       "did not change os_window is_focused on the minimized probe window; "
                       + NO_KWIN),
        }
        kitten("close-window", "--match", "all")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        headless_address = f"unix:{work}/headless/rc.sock"
        headless = subprocess.Popen(
            ["kitty", "--config", "NONE", "-o", "allow_remote_control=socket-only",
             "-o", "confirm_os_window_close=0", "--listen-on", headless_address,
             "--class", f"{ctx.token}-kitty", "--start-as=hidden", "--directory", cwd,
             "sleep", "300"],
            env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        tracker.add(headless.pid, "gui")
        tracker.direct.append(headless.pid)
        hidden = wait_until(lambda: listing(headless_address), 20)
        if hidden:
            os_window = hidden[0]
            observations["headless_is_focused"] = {
                "os_window_is_focused": os_window.get("is_focused"),
                "window_is_focused": os_window["tabs"][0]["windows"][0].get("is_focused"),
                "note": ("with --start-as=hidden no window is visible yet is_focused can be "
                         "true, so is_focused is not evidence of OS activation"),
            }
        kitten("close-window", "--match", "all", to=headless_address)
        try:
            headless.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    except Exception as error:
        observations["error"] = ctx.redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        record["cleanup"] = tracker.terminate()
    record["observations"] = observations
    record.setdefault("readback_proven", False)
    record.setdefault("env_markers", {})
    record.setdefault("process_comm", {})
    record.setdefault("ancestry_reaches_gui", None)
    record.setdefault("pid_only_find_tab", {"viable": False, "method": "not established"})
    record.setdefault("activation_readback", {"status": "unverified", "method": NO_KWIN})
    record["recommendation"] = "adapter" if record["readback_proven"] else "assessment-only"
    record["evidence_kind"] = "live" if "error" not in observations else "unverified"
    record["provenance"] = ("live: one minimized and one headless disposable kitty with "
                            "--config NONE and a temporary socket; readback by kitten @ ls")
    return record


def probe_terminator(ctx):
    path, source = install_info("terminator")
    if not path:
        return not_installed_record("terminator not found on PATH")
    work = ctx.root / "terminator"
    for name in ("cwd", "io"):
        (work / name).mkdir(parents=True, mode=0o700)
    tracker = Tracker([str(work)])
    io = work / "io"
    config = work / "config"
    config.write_text("")
    script = io / "target.sh"
    script.write_text(
        f'd="{io}"\nenv > "$d/env.tmp" && mv "$d/env.tmp" "$d/env"\n'
        'echo $$ > "$d/pid.tmp" && mv "$d/pid.tmp" "$d/pid"\nsleep 3\n')
    version = run(["terminator", "--version"])[1]
    record = {
        "installed": True, "version": version or None, "install_source": source,
        "select_argv": None, "readback_argv": None, "readback_proven": False,
        "multi_client_behavior": "not applicable: detection-only per #47, no selection API probed",
        "version_floor": "not applicable: detection-only per #47",
        "pid_only_find_tab": {"viable": False,
                              "method": "not applicable: detection-only, find_tab returns None"},
    }
    observations = {}
    try:
        if not shutil.which("dbus-run-session"):
            raise RuntimeError("dbus-run-session not found; refusing to use the user bus")
        process = subprocess.Popen(
            ["dbus-run-session", "--", "terminator", "-H", "-g", str(config),
             "--working-directory", str(work / "cwd"), "-x", "sh", str(script)],
            env=ctx.base_env(), cwd=str(work / "cwd"), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        tracker.add(process.pid, "dbus-run-session")
        tracker.direct.append(process.pid)
        if not wait_until(lambda: (io / "pid").exists(), 20):
            raise RuntimeError("terminator child did not start")
        tracker.sweep()
        shell = read_pid(io / "pid")
        chain = ancestry(shell, os.getpid())
        gui_pid = chain[1]["pid"] if len(chain) > 1 else None
        roles = {shell: "child shell", process.pid: "dbus-run-session"}
        if gui_pid:
            roles[gui_pid] = "gui"
        child_env = read_env_file(io / "env")
        record["env_markers"] = describe_markers(
            child_env, ("TERMINATOR_UUID", "TERMINATOR_DBUS_NAME", "TERMINATOR_DBUS_PATH",
                        "VTE_VERSION", "COLORTERM"), ctx.launcher_env, ctx.redact)
        record["env_markers"]["term_in_child"] = child_env.get("TERM")
        gui = process_facts(gui_pid) if gui_pid else None
        record["process_comm"] = {"gui": {"comm": gui["comm"], "exe": gui["exe"]} if gui else None,
                                  "server": None, "client": None}
        record["ancestry"] = public_chain(chain, roles)
        record["ancestry_reaches_gui"] = bool(gui and gui["comm"] == "terminator")
        observations["all_three_markers_present"] = all(
            name in child_env for name in
            ("TERMINATOR_UUID", "TERMINATOR_DBUS_NAME", "TERMINATOR_DBUS_PATH"))
        observations["windowid_inherited_unchanged"] = (
            "WINDOWID" in child_env
            and child_env.get("WINDOWID") == ctx.launcher_env.get("WINDOWID"))
        observations["isolation"] = ("private session bus via dbus-run-session and -H "
                                     "(hidden window), so no user Terminator was contacted")
        wait_until(lambda: process.poll() is not None, 10)
    except Exception as error:
        observations["error"] = ctx.redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        record["cleanup"] = tracker.terminate()
    record["observations"] = observations
    record.setdefault("env_markers", {})
    record.setdefault("process_comm", {})
    record.setdefault("ancestry_reaches_gui", None)
    record["activation_readback"] = {
        "status": "unverified", "method": "detection-only per #47; " + NO_KWIN}
    record["recommendation"] = "none"
    record["evidence_kind"] = "live" if "error" not in observations else "inspected"
    record["provenance"] = ("live: hidden disposable Terminator on a private D-Bus session "
                            "bus; child env and process ancestry only")
    return record


def probe_wezterm(ctx):
    return not_installed_record(
        "skipped by CTO decision",
        candidate=("unverified candidates from the plan: wezterm cli activate-pane "
                   "--pane-id N; readback wezterm cli list-clients --format json "
                   "focused_pane_id or wezterm cli list --format json"))


PROBES = {
    "zellij": probe_zellij, "wezterm": probe_wezterm, "kitty": probe_kitty,
    "screen": probe_screen, "terminator": probe_terminator,
}
USER_CONFIG = (".config/kitty", ".config/zellij", ".screenrc", ".config/terminator",
               ".config/wezterm", ".wezterm.lua")


def config_snapshot():
    snapshot = {}
    for relative in USER_CONFIG:
        path = Path.home() / relative
        entries = {}
        if path.is_dir():
            for item in sorted(path.rglob("*")):
                try:
                    entries[str(item)] = item.stat().st_mtime_ns
                except OSError:
                    pass
        elif path.exists():
            entries[str(path)] = path.stat().st_mtime_ns
        snapshot[relative] = entries
    return snapshot


def zellij_cache_mentions(token):
    cache = Path.home() / ".cache" / "zellij"
    if not cache.is_dir():
        return 0
    return sum(1 for item in cache.rglob(f"*{token}*"))


def repo_facts():
    root = Path(__file__).resolve().parents[1]
    code, head, _ = run(["git", "-C", str(root), "rev-parse", "HEAD"])
    _, dirty, _ = run(["git", "-C", str(root), "status", "--porcelain", "--",
                       "validation/probe_terminals.py"])
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {"tested_commit": head if code == 0 else None,
            "probe_modified_since_commit": bool(dirty),
            "probe_sha256": digest}


def platform_facts():
    pretty = None
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return {
        "os": pretty, "kernel_release": os.uname().release,
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
        "session_type": os.environ.get("XDG_SESSION_TYPE"),
        "python_version": sys.version.split()[0],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="validation/evidence/terminal-probe-fedora44.json")
    parser.add_argument("--only", nargs="*", choices=TERMINALS, default=list(TERMINALS))
    arguments = parser.parse_args(argv)
    if sys.platform != "linux":
        print("This probe requires Linux", file=sys.stderr)
        return 2
    token = "fleetprobe-" + secrets.token_hex(4)
    before = config_snapshot()
    record = {}
    with tempfile.TemporaryDirectory(prefix=f"{token}-", dir="/tmp") as temporary:
        redact = Redactor.for_host({temporary: "<probe_tmp>", token: "<token>"})
        ctx = Context(Path(temporary), token, redact)
        for name in TERMINALS:
            if name not in arguments.only:
                record[name] = not_installed_record("not selected for this run")
                continue
            print(f"probing {name}", file=sys.stderr)
            record[name] = PROBES[name](ctx)
        stray = Tracker([temporary, token]).stray()
    after = config_snapshot()
    survivors = sum(entry.get("cleanup", {}).get("survivors", 0) for entry in record.values())
    record["probe"] = {
        "schema": "terminal-probe/1",
        "platform": platform_facts(),
        **repo_facts(),
        "kwin_calls": 0,
        "user_config_unchanged": before == after,
        "user_zellij_cache_entries_for_probe": zellij_cache_mentions(token),
        "cleanup": {"survivors": survivors, "marker_strays_after_run": len(stray)},
        "labels": {
            "live": "observed on this host with real terminal processes",
            "inspected": "read from installed files or documentation, not executed",
            "unverified": "not observed",
        },
    }
    text = json.dumps(record, indent=2, sort_keys=False) + "\n"
    text = redact(text)
    leaks = Redactor.for_host().leaks(text)
    if "/home/" in text:
        leaks.append("/home/")
    errors = validate_record(json.loads(text))
    if leaks or errors:
        print(f"refusing to write evidence: leaks={leaks} errors={errors}", file=sys.stderr)
        return 1
    Path(arguments.out).write_text(text)
    print(text)
    healthy = survivors == 0 and not stray and before == after
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
