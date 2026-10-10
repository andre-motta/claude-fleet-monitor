"""Validate exact zellij pane selection against an isolated live session.

Local-only Linux helper; it is never run in CI. It starts a uniquely named
zellij session with a temporary socket, config, cache and data directory,
drives it through private PTY clients, and selects duplicate-title panes in two
tabs through ZellijAPI with list-clients readback plus keystroke routing as
independent confirmation. A decoy background session in the same private
socket directory checks that --session wins over ZELLIJ_SESSION_NAME and that
zero attached clients is reported as a failure. It never touches the default
socket directory, user config or cache, makes no KWin, qdbus or xdotool calls,
and only signals processes it started (PID plus kernel start time).
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time
from unittest.mock import patch

from probe_terminals import (
    PtyClient,
    Redactor,
    Tracker,
    config_snapshot,
    input_script,
    platform_facts,
    read_env_file,
    read_pid,
    receivers,
    run,
    typed_target,
    wait_until,
    zellij_cache_mentions,
)

from claude_fleet_monitor.terminal_apis import tmux, zellij
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "validation" / "evidence" / "zellij-fedora44.json"
HASHED = ("src/claude_fleet_monitor/terminal_apis/zellij.py", "validation/zellij.py")
PANES = ("0", "1", "2")
SELECTION_ORDER = ("1", "2", "0", "1")
ISOLATION_KEYS = ("ZELLIJ_SOCKET_DIR", "ZELLIJ_CONFIG_DIR", "XDG_CACHE_HOME", "XDG_DATA_HOME")
GUI_ACTIVATION = (
    "unavailable: client PIDs are not discoverable through the zellij CLI and the "
    "agent PID ancestry ends at the daemonized server, so no parent emulator is "
    "reachable; no KWin, qdbus or xdotool calls were made")


class Check(Exception):
    """A validation expectation that did not hold."""


def expect(condition, message):
    if not condition:
        raise Check(message)


def file_digest(relative):
    return hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()


def repo_facts():
    code, head, _ = run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"])
    _, dirty, _ = run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", *HASHED])
    return {
        "tested_commit": head if code == 0 else None,
        "modified_since_commit": bool(dirty),
        "sha256": {relative: file_digest(relative) for relative in HASHED},
    }


def isolated_env(root):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("ZELLIJ", "TMUX", "KITTY_", "WEZTERM_", "TERMINATOR_"))
           and key not in ("STY", "WINDOW")}
    env.update({
        "TERM": "xterm-256color",
        "ZELLIJ_SOCKET_DIR": str(root / "sock"),
        "ZELLIJ_CONFIG_DIR": str(root / "cfg"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_DATA_HOME": str(root / "data"),
    })
    return env


def write_fixture(root):
    for name in ("sock", "cfg", "cache", "data", "cwd", "io"):
        (root / name).mkdir(parents=True, mode=0o700)
    (root / "cfg" / "config.kdl").write_text(
        "show_startup_tips false\nshow_release_notes false\nsession_serialization false\n")
    script = input_script(root / "io", "ZELLIJ_PANE_ID")
    pane = f'pane name="dup" cwd="{root / "cwd"}" command="sh" {{ args "{script}"; }}'
    layout = root / "layout.kdl"
    layout.write_text(
        f'layout {{\n tab name="dup" {{\n  {pane}\n  {pane}\n }}\n'
        f' tab name="dup" {{\n  {pane}\n }}\n}}\n')
    return layout


class Session:
    """Raw zellij commands for one session in the private socket directory."""

    def __init__(self, name, env):
        self.name = name
        self.env = env

    def action(self, *arguments):
        return run(["zellij", "--session", self.name, "action", *arguments], env=self.env)

    def clients(self):
        code, out, _ = self.action("list-clients")
        if code != 0:
            return None
        return {parts[0]: parts[1] for parts in (line.split() for line in out.splitlines()[1:])
                if len(parts) >= 2}

    def panes(self):
        code, out, _ = self.action("list-panes", "-a", "-j")
        if code != 0 or not out:
            return []
        return [item for item in json.loads(out) if not item.get("is_plugin")]


def captured_env(io_dir, pane):
    """Run ZellijAPI.capture_env against the env a real pane received."""
    child = read_env_file(io_dir / f"env-{pane}")
    names = ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID")
    with patch.dict(os.environ, {name: child[name] for name in names if name in child}):
        return ZellijAPI.capture_env()


def failure_detail(callable_, *arguments):
    try:
        outcome = callable_(*arguments)
    except Exception as error:
        return {"selected": False, "detail": str(error)}
    return {"selected": bool(outcome), "detail": None}


class SpyRun:
    def __init__(self):
        self.calls = 0
        self.real = zellij._run

    def __call__(self, argv):
        self.calls += 1
        return self.real(argv)


def exercise(root, session, decoy, tracker, observations):
    io_dir = root / "io"
    layout = write_fixture(root)
    env = isolated_env(root)
    target = Session(session, env)
    other = Session(decoy, env)
    api = ZellijAPI()
    code, version, _ = run(["zellij", "--version"], env=env)
    expect(code == 0 and version, "zellij --version failed")
    observations["zellij_version"] = version

    code, _, err = run(["zellij", "--config-dir", str(root / "cfg"), "attach",
                        "--create-background", decoy], env=env)
    expect(code == 0, f"decoy session did not start: {err[:120]}")
    tracker.sweep()
    client = PtyClient(["zellij", "--config-dir", str(root / "cfg"), "--session", session,
                        "--new-session-with-layout", str(layout)],
                       env, str(root / "cwd"), tracker, "client")
    ready = wait_until(lambda: all((io_dir / f"pid-{pane}").exists() for pane in PANES)
                       and target.clients(), 20)
    expect(ready, "zellij session did not become ready")
    tracker.sweep()
    pids = {pane: read_pid(io_dir / f"pid-{pane}") for pane in PANES}
    for pid in pids.values():
        tracker.add(pid, "pane")

    listed = target.panes()
    observations["duplicate_targets"] = {
        "terminal_panes": len(listed),
        "titles": sorted({item.get("title") for item in listed}),
        "tabs": len({item.get("tab_position", item.get("tab_id")) for item in listed}),
        "tab_names": sorted({str(item.get("tab_name")) for item in listed}),
        "same_cwd": len({os.path.realpath(f"/proc/{pid}/cwd") for pid in pids.values()}) == 1,
    }
    expect(observations["duplicate_targets"]["titles"] == ["dup"]
           and len(listed) == 3 and observations["duplicate_targets"]["tabs"] == 2,
           "fixture panes are not duplicate titles across two tabs")

    envs = {pane: captured_env(io_dir, pane) for pane in PANES}
    expect(all(envs[pane].get("ZELLIJ_PANE_ID") == pane
               and envs[pane].get("ZELLIJ_SESSION_NAME") == session for pane in PANES),
           "capture_env did not record the pane id and session")
    observations["capture_env_keys"] = sorted(envs["0"])
    find_results = {pane: api.find_tab(pids[pane], envs[pane]) for pane in PANES}
    expect(find_results == {pane: pane for pane in PANES}, f"find_tab mismatch {find_results}")
    legacy = {key: value for key, value in envs["1"].items() if key != "ZELLIJ_PANE_ID"}
    try:
        api.find_tab(pids["1"], legacy)
        legacy_detail = None
    except LookupError as error:
        legacy_detail = str(error)
    observations["pre_upgrade_record_detail"] = legacy_detail
    expect(legacy_detail == "record predates pane capture", "pre-upgrade record not reported")

    with patch.dict(os.environ, {**{key: env[key] for key in ISOLATION_KEYS},
                                 "ZELLIJ_SESSION_NAME": decoy}):
        for name in ("ZELLIJ", "ZELLIJ_PANE_ID"):
            os.environ.pop(name, None)
        spy = SpyRun()
        with patch.object(zellij, "_run", spy):
            rejected = [
                api.find_tab(pids["1"], {**envs["1"], "ZELLIJ_PANE_ID": "1;2"}) is None,
                api.find_tab(pids["1"], {**envs["1"], "ZELLIJ_SESSION_NAME": "-x"}) is None,
                not api.switch_tab("-x", envs["1"]),
                not api.switch_tab("1\x002", envs["1"]),
                not api.switch_tab("1", {**envs["1"], "ZELLIJ_SESSION_NAME": "a\x00b"}),
            ]
        observations["injection_rejected_before_subprocess"] = all(rejected) and spy.calls == 0
        expect(observations["injection_rejected_before_subprocess"], "injection reached zellij")

        before_input = failure_detail(api.switch_tab, "1", envs["1"])
        observations["before_any_client_input"] = {
            **before_input, "client_pane": target.clients()}
        expect(not before_input["selected"], "selection claimed before any client input")
        expect(typed_target(client, io_dir, "warmup") == ["0"], "warmup input not routed")

        steps = []
        for index, pane in enumerate(SELECTION_ORDER):
            selected = failure_detail(api.switch_tab, pane, envs[pane])
            rows = target.clients()
            routed = typed_target(client, io_dir, f"select-{index}-{pane}")
            steps.append({
                "target": pane,
                "tab": 2 if pane == "2" else 1,
                **selected,
                "list_clients_matches": rows == {"1": f"terminal_{pane}"},
                "keystroke_routed_to": routed,
            })
        observations["selections"] = steps
        expect(all(step["selected"] and step["list_clients_matches"]
                   and step["keystroke_routed_to"] == [step["target"]] for step in steps),
               "a selection was not confirmed by readback and keystroke routing")
        observations["session_flag_overrides_env"] = True

        expect(tmux._detect_parent_terminal(pids["1"]) is None,
               "agent ancestry reached a parent emulator; refusing to run activation")
        with patch.object(tmux, "_detect_parent_terminal", lambda pid: None):
            result = api.focus_result(pids["0"], envs["0"])
        observations["focus_result"] = {
            "state": result.state,
            "selection": {"succeeded": result.selection.succeeded,
                          "detail": result.selection.detail},
            "activation": {"succeeded": result.activation.succeeded,
                           "detail": result.activation.detail},
        }
        expect(result.state == "partial" and result.selection.succeeded
               and not result.activation.succeeded, "focus_result was not an honest partial")
        typed_target(client, io_dir, "after-focus-result")

        second = PtyClient(["zellij", "--config-dir", str(root / "cfg"), "attach", session],
                           env, str(root / "cwd"), tracker, "client")
        expect(wait_until(lambda: len(target.clients() or {}) == 2, 10),
               "second client did not attach")
        landed = typed_target(second, io_dir, "second-client-input")
        before = target.clients()
        pane = next((pane for pane in ("2", "1")
                     if f"terminal_{pane}" not in (before or {}).values()), None)
        expect(pane is not None, "no pane free of clients for the two-client check")
        multi = failure_detail(api.switch_tab, pane, envs[pane])
        multi.update({
            "target": pane,
            "list_clients_before": before,
            "list_clients_after": target.clients(),
            "second_client_landed_on": landed,
            "second_client_keystroke_routed_to": typed_target(second, io_dir, "multi-c2"),
            "first_client_keystroke_routed_to": typed_target(client, io_dir, "multi-c1"),
        })
        observations["two_clients"] = multi
        expect(multi["selected"] and multi["second_client_keystroke_routed_to"] == [pane]
               and multi["first_client_keystroke_routed_to"] == ["0"],
               "two-client selection did not follow the most recent input client")

        def stale(pane_id, env_for):
            rows = target.clients()
            outcome = failure_detail(api.switch_tab, pane_id, env_for)
            outcome["clients_unchanged"] = target.clients() == rows
            return outcome

        unknown = stale("99", {**envs["0"], "ZELLIJ_PANE_ID": "99"})
        code, _, err = target.action("close-pane", "--pane-id", "terminal_2")
        expect(code == 0, f"close-pane failed: {err[:120]}")
        expect(wait_until(lambda: len(target.panes()) == 2 and "terminal_2" not in (
            target.clients() or {"": "terminal_2"}).values(), 5), "pane 2 did not close")
        time.sleep(0.5)
        closed = stale("2", envs["2"])
        observations["stale_ids"] = {"unknown_pane": unknown, "closed_pane": closed}
        expect(not unknown["selected"] and not closed["selected"]
               and unknown["clients_unchanged"] and closed["clients_unchanged"],
               "a stale pane id was accepted")

        decoy_before = other.clients()
        zero = failure_detail(api.switch_tab, "0", {**envs["0"], "ZELLIJ_SESSION_NAME": decoy})
        observations["zero_clients"] = {
            **zero, "decoy_clients_before": decoy_before, "decoy_clients_after": other.clients()}
        expect(not zero["selected"] and zero["detail"] == "no attached zellij client",
               "zero attached clients was not reported")


def cleanup(root, sessions, tracker):
    env = isolated_env(root)
    for name in sessions:
        run(["zellij", "kill-session", name], env=env)
        run(["zellij", "delete-session", "--force", name], env=env)
    result = tracker.terminate()
    shutil.rmtree(root, ignore_errors=True)
    result["temp_dir_removed"] = not root.exists()
    return result


def public_text(evidence, redact):
    text = redact(json.dumps(evidence, indent=2) + "\n")
    leaks = Redactor.for_host().leaks(text)
    if "/home/" in text or "/tmp/" in text:
        leaks.append("absolute path")
    return text, leaks


def validate(write=True, output=EVIDENCE):
    if sys.platform != "linux" or not shutil.which("zellij"):
        raise RuntimeError("This check requires Linux and zellij on PATH")
    token = secrets.token_hex(4)
    session = f"fleet-z5-{token}"
    decoy = f"fleet-z5-{token}-decoy"
    config_before = config_snapshot()
    root = Path(tempfile.mkdtemp(prefix=f"fleet-zellij-validation-{token}-"))
    tracker = Tracker([str(root), session])
    observations = {}
    started = time.monotonic()
    try:
        exercise(root, session, decoy, tracker, observations)
        error = None
    except Exception as failure:
        error = f"{type(failure).__name__}: {failure}"
    finally:
        cleanup_result = cleanup(root, (session, decoy), tracker)
    cleanup_result["marker_strays_after_run"] = len(Tracker([str(root), token]).stray())
    healthy_cleanup = (cleanup_result["survivors"] == 0 and cleanup_result["marker_strays"] == 0
                       and cleanup_result["marker_strays_after_run"] == 0
                       and cleanup_result["temp_dir_removed"])
    evidence = {
        "schema": "zellij-validation/1",
        "result": "pass" if error is None and healthy_cleanup else "fail",
        "error": error,
        "zellij_version": observations.pop("zellij_version", None),
        "validated_versions": [zellij.VALIDATED_VERSION],
        "version_floor": (
            "not established: only zellij " + zellij.VALIDATED_VERSION + " was probed and "
            "validated; the adapter gates on behavior (nonzero exit, unknown subcommand or "
            "unrecognized list-clients columns fail selection) rather than a version number"),
        "provenance": "live",
        "provenance_detail": (
            "real zellij server, panes and PTY clients in an isolated socket, config, cache "
            "and data directory; selection read back with list-clients and confirmed by "
            "keystroke routing"),
        "selection_argv": ["zellij", "--session", "<session>", "action", "focus-pane-id",
                           "terminal_<ZELLIJ_PANE_ID>"],
        "readback_argv": ["zellij", "--session", "<session>", "action", "list-clients"],
        "multi_client_rule": (
            "success requires list-clients to show the target pane for at least one client; "
            "focus-pane-id moves only the client that most recently sent input"),
        "gui_activation": GUI_ACTIVATION,
        **observations,
        "cleanup": cleanup_result,
        "user_config_unchanged": config_snapshot() == config_before,
        "user_zellij_cache_entries_for_run": zellij_cache_mentions(token),
        "socket_dir": "private temporary ZELLIJ_SOCKET_DIR for every zellij invocation",
        "kwin_calls": 0,
        "duration_seconds": round(time.monotonic() - started, 1),
        "platform": platform_facts(),
        **repo_facts(),
    }
    if not evidence["user_config_unchanged"] or evidence["user_zellij_cache_entries_for_run"]:
        evidence["result"] = "fail"
    redact = Redactor.for_host({str(root): "<tmp>", decoy: "<decoy>", session: "<session>",
                                token: "<token>"})
    text, leaks = public_text(evidence, redact)
    if leaks:
        raise RuntimeError(f"refusing to write evidence with private data: {leaks}")
    if write:
        Path(output).write_text(text)
    print(text, end="")
    return json.loads(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-write", action="store_true", help="print evidence only")
    parser.add_argument("--out", default=str(EVIDENCE))
    arguments = parser.parse_args(argv)
    evidence = validate(write=not arguments.no_write, output=arguments.out)
    return 0 if evidence["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
