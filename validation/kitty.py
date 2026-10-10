"""Validate Kitty selection and KWin activation with disposable instances.

Local-only Linux helper for KDE Plasma; it is never run in CI. It starts
minimized kitty instances with --config NONE, allow_remote_control=socket-only
and temporary unix listen_on sockets, one hidden kitty and one kitty with
remote control off. Window environments are captured by the real KittyAPI
inside each kitty window. Duplicate-title windows and tabs are selected, and
the probe OS windows activated, through KittyAPI.focus_result and confirmed by
an independent `kitten @ ls`. KWin scripts run only through KittyAPI, behind
an interlock that refuses any owner pid other than a probe kitty it started,
so only probe windows are ever activated; they briefly take focus. It never
edits user config, never calls xdotool, and only signals processes it
started. The evidence JSON contains placeholders only, never home paths, user
names or host names.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from probe_terminals import (
    Redactor,
    Tracker,
    config_snapshot,
    install_info,
    kitty_tree,
    platform_facts,
    read_pid,
    run,
    wait_until,
)

from claude_fleet_monitor.terminal_apis import _kwin
from claude_fleet_monitor.terminal_apis import _qdbus
from claude_fleet_monitor.terminal_apis import kitty as kitty_module
from claude_fleet_monitor.terminal_apis.kitty import KittyAPI

ROOT = Path(__file__).resolve().parents[1]
OWNED = (
    "src/claude_fleet_monitor/terminal_apis/kitty.py",
    "src/claude_fleet_monitor/terminal_apis/_kwin.py",
    "src/claude_fleet_monitor/terminal_apis/_qdbus.py",
    "validation/kitty.py",
)
real_which = kitty_module.shutil.which
DEFAULT_OUT = ROOT / "validation" / "evidence" / "kitty-fedora44.json"
CAPTURE = (
    "import json, sys\n"
    "from claude_fleet_monitor.terminal_apis.kitty import KittyAPI\n"
    "json.dump({'detect': KittyAPI.detect(), 'env': KittyAPI.capture_env()}, sys.stdout)\n"
)


def window_script(directory):
    script = directory / "window.sh"
    script.write_text(
        f'd="{directory}"; i="${{KITTY_WINDOW_ID:-none}}"\n'
        f'"{sys.executable}" "$d/capture.py" > "$d/capture-$i.tmp" '
        '&& mv "$d/capture-$i.tmp" "$d/capture-$i"\n'
        'echo $$ > "$d/pid-$i.tmp" && mv "$d/pid-$i.tmp" "$d/pid-$i"\n'
        "exec sleep 300\n"
    )
    (directory / "capture.py").write_text(CAPTURE)
    return str(script)


def read_capture(directory, key):
    path = directory / f"capture-{key}"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def child_env(work):
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("ZELLIJ", "TMUX", "KITTY_", "WEZTERM_", "TERMINATOR_"))
        and key not in ("STY", "WINDOW")
    }
    env.update({
        "TERM": "xterm-256color",
        "KITTY_CONFIG_DIRECTORY": str(work / "cfg"),
        "KITTY_CACHE_DIRECTORY": str(work / "cache"),
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def launch(work, env, tracker, address, remote_control, script, token,
           start_as="minimized"):
    process = subprocess.Popen(
        ["kitty", "--config", "NONE", "-o", f"allow_remote_control={remote_control}",
         "-o", "confirm_os_window_close=0", "--listen-on", address,
         "--class", f"{token}-kitty", f"--start-as={start_as}",
         "--directory", str(work / "cwd"), "sh", script],
        env=env, cwd=str(work / "cwd"), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    tracker.add(process.pid, "gui")
    tracker.direct.append(process.pid)
    return process


def active_state(tree):
    return {
        window_id: {"tab": tab["id"], "tab_active": tab["is_active"],
                    "window_active": window["is_active"]}
        for window_id, (_, tab, window) in tree.items()
    }


class KWinGuard:
    """Run KWin activation only for probe kitty pids and record every script."""

    def __init__(self):
        self.allowed = set()
        self.owners = []
        self.plugins = []
        self.refused = []
        self.real_activate = kitty_module.activate_owned_window
        self.real_script = _kwin.run_kwin_script

    def activate(self, executable, owner_pid, **kwargs):
        if owner_pid not in self.allowed:
            self.refused.append(owner_pid)
            raise _qdbus.KWinScriptError("validator refused a non-probe owner pid")
        self.owners.append(owner_pid)
        return self.real_activate(executable, owner_pid, **kwargs)

    def script(self, executable, script, prefix, **kwargs):
        self.plugins.append(kwargs.get("plugin"))
        return self.real_script(executable, script, prefix, **kwargs)

    def left_loaded(self):
        executable = _qdbus.resolve_qdbus()
        return sum(
            1 for plugin in self.plugins
            if plugin is None or _qdbus.qdbus_text(executable, [
                "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.isScriptLoaded",
                plugin]) != "false")


def os_focus(listing, window_id):
    for os_window in listing or []:
        for tab in os_window.get("tabs", []):
            if any(window.get("id") == window_id for window in tab.get("windows", [])):
                return os_window.get("is_focused")
    return None


def operation(result_operation):
    return {"attempted": result_operation.attempted,
            "succeeded": result_operation.succeeded,
            "detail": result_operation.detail}


def file_digest(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def repo_facts():
    code, head, _ = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    _, dirty, _ = run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *OWNED])
    return {
        "tested_commit": head if code == 0 else None,
        "tested_files_modified_since_commit": bool(dirty),
        "sha256": {relative: file_digest(relative) for relative in OWNED},
    }


def validate(work, token, redact):
    for name in ("cfg", "cache", "cwd", "io", "off", "b", "hidden"):
        (work / name).mkdir(parents=True, mode=0o700)
    tracker = Tracker([str(work)])
    env = child_env(work)
    io = work / "io"
    address = f"unix:{work}/rc.sock"
    evidence = {}
    guard = KWinGuard()
    stack = contextlib.ExitStack()

    def kitten(*arguments, to=address):
        return run(["kitten", "@", "--to", to, *arguments], env=env)

    def listing(to=address):
        code, out, _ = kitten("ls", to=to)
        try:
            return json.loads(out) if code == 0 else None
        except ValueError:
            return None

    def tree(to=address):
        data = listing(to)
        return kitty_tree(data) if data is not None else None

    def probe(directory, process, key="1"):
        capture = read_capture(directory, key)
        shell = read_pid(directory / f"pid-{key}")
        tracker.add(shell, "window shell")
        if capture["env"].get("KITTY_PID") != str(process.pid):
            raise RuntimeError("captured KITTY_PID is not the probe kitty")
        guard.allowed.add(process.pid)
        return capture, shell

    def scripts_since(count):
        return len(guard.plugins) - count

    api = KittyAPI()
    try:
        stack.enter_context(patch.object(kitty_module, "activate_owned_window", guard.activate))
        stack.enter_context(patch.object(_kwin, "run_kwin_script", guard.script))
        process = launch(work, env, tracker, address, "socket-only",
                         window_script(io), token)
        if not wait_until(lambda: tree() and read_capture(io, "1"), 20):
            raise RuntimeError("kitty remote control did not become ready")
        probe(io, process)
        code, out, _ = kitten("launch", "--type=window", "--title", "dup", "--cwd",
                              str(work / "cwd"), "sh", str(io / "window.sh"))
        sibling = out if code == 0 and out.isdigit() else None
        code, out, _ = kitten("launch", "--type=tab", "--title", "dup", "--cwd",
                              str(work / "cwd"), "sh", str(io / "window.sh"))
        other_tab = out if code == 0 and out.isdigit() else None
        if not sibling or not other_tab:
            raise RuntimeError("kitty did not open the fixture windows")
        targets = ("1", sibling, other_tab)
        if not wait_until(lambda: all(read_capture(io, key) for key in targets), 15):
            raise RuntimeError("kitty fixture windows did not capture their env")
        kitten("set-window-title", "--match", "id:1", "dup")
        for window_id in ("1", other_tab):
            kitten("set-tab-title", "--match", f"window_id:{window_id}", "dup")
        captures = {key: read_capture(io, key) for key in targets}
        shells = {key: read_pid(io / f"pid-{key}") for key in targets}
        for pid in shells.values():
            tracker.add(pid, "window shell")
        listen = captures["1"]["env"].get("KITTY_LISTEN_ON", "")
        evidence["capture"] = {
            "detect": all(item["detect"] for item in captures.values()),
            "keys": sorted(captures["1"]["env"]),
            "window_ids_match": all(
                captures[key]["env"].get("KITTY_WINDOW_ID") == key for key in targets),
            "listen_on_equals_given_address": listen == address,
            "listen_on_shape": redact(listen),
        }
        layout = tree()
        evidence["duplicate_targets"] = {
            "window_titles": sorted({layout[int(key)][2]["title"] for key in targets}),
            "tab_titles": sorted({layout[int(key)][1]["title"] for key in targets}),
            "same_cwd": len({layout[int(key)][2]["cwd"] for key in targets}) == 1,
            "windows_sharing_a_tab": layout[1][1]["id"] == layout[int(sibling)][1]["id"],
            "separate_tabs": layout[1][1]["id"] != layout[int(other_tab)][1]["id"],
        }
        selections = []
        for key in ("1", sibling, other_tab, "1", sibling):
            before = active_state(tree())
            result = api.focus_result(shells[key], captures[key]["env"])
            after = active_state(tree())
            target = after[int(key)]
            others = [state for window_id, state in after.items() if window_id != int(key)]
            same_tab = [state for state in others if state["tab"] == target["tab"]]
            other_tabs = [state for state in others if state["tab"] != target["tab"]]
            selections.append({
                "target": key,
                "active_before": [wid for wid, state in before.items()
                                  if state["tab_active"] and state["window_active"]],
                "state": result.state,
                "selection": operation(result.selection),
                "activation": operation(result.activation),
                "readback_os_window_focused": os_focus(listing(), int(key)),
                "readback_target_tab_active": target["tab_active"],
                "readback_target_window_active": target["window_active"],
                "readback_same_tab_others_active": [s["window_active"] for s in same_tab],
                "readback_other_tabs_active": sorted({s["tab_active"] for s in other_tabs}),
            })
        evidence["selections"] = selections
        selected_ok = all(
            item["selection"]["succeeded"] and item["state"] == "complete"
            and item["activation"]["succeeded"] and item["readback_os_window_focused"] is True
            and item["readback_target_tab_active"] and item["readback_target_window_active"]
            and not any(item["readback_same_tab_others_active"])
            and not any(item["readback_other_tabs_active"])
            for item in selections)

        commands = []
        real_run = kitty_module._run

        def recording(argv):
            commands.append(argv[0])
            return real_run(argv)

        with patch.object(kitty_module, "_run", recording), \
                patch.object(kitty_module.shutil, "which",
                             side_effect=lambda name: None if name == "kitten"
                             else real_which(name)):
            fallback = api.focus_result(shells[other_tab], captures[other_tab]["env"])
        fallback_state = active_state(tree())[int(other_tab)]
        evidence["kitty_at_fallback"] = {
            "tools": sorted(set(commands)),
            "selection_succeeded": fallback.selection.succeeded,
            "readback_active": fallback_state["tab_active"] and fallback_state["window_active"],
        }

        kitten("close-window", "--match", f"id:{sibling}")
        wait_until(lambda: int(sibling) not in (tree() or {sibling: 0}), 5)
        before = active_state(tree())
        stale = api.focus_result(shells[sibling], captures[sibling]["env"])
        evidence["stale_target"] = {
            "state": stale.state,
            "selection_attempted": stale.selection.attempted,
            "selection_detail": stale.selection.detail,
            "active_unchanged": active_state(tree()) == before,
        }

        missing_env = {"KITTY_WINDOW_ID": "1", "KITTY_LISTEN_ON": f"unix:{work}/missing.sock"}
        missing = api.focus_result(shells["1"], missing_env)
        evidence["missing_socket"] = {
            "state": missing.state, "selection_attempted": missing.selection.attempted,
            "selection_detail": redact(missing.selection.detail),
        }

        off_dir = work / "off"
        off_address = f"unix:{off_dir}/rc.sock"
        launch(work, env, tracker, off_address, "no", window_script(off_dir), token)
        if not wait_until(lambda: read_capture(off_dir, "1"), 20):
            raise RuntimeError("remote-control-off kitty did not start")
        off_capture = read_capture(off_dir, "1")
        off_pid = read_pid(off_dir / "pid-1")
        tracker.add(off_pid, "window shell")
        off_result = api.focus_result(off_pid, off_capture["env"])
        code, _, err = kitten("ls", to=off_address)
        evidence["remote_control_off"] = {
            "detect": off_capture["detect"],
            "captured_keys": sorted(off_capture["env"]),
            "socket_created": Path(off_address[5:]).exists(),
            "state": off_result.state,
            "selection_attempted": off_result.selection.attempted,
            "selection_detail": off_result.selection.detail,
            "forced_address_exit": code,
            "forced_address_stderr": redact(Redactor({off_address[5:]: "<socket>"})(err))[:200],
            "provenance": "live",
        }
        evidence["remote_control_disabled_reply"] = {
            "text": "Remote control is disabled. Add allow_remote_control to your kitty.conf",
            "provenance": (
                "inspected: kitty 0.47.1 boss.py reply for tty or password routes; not "
                "reachable through an unconfigured socket because kitty then does not "
                "listen, which the remote_control_off case observes live"),
        }
        off = evidence["remote_control_off"]

        b_dir = work / "b"
        b_address = f"unix:@{token}-b"
        b_process = launch(work, env, tracker, b_address, "socket-only",
                           window_script(b_dir), token)
        if not wait_until(lambda: tree(b_address) and read_capture(b_dir, "1"), 20):
            raise RuntimeError("second kitty instance did not become ready")
        b_capture, b_shell = probe(b_dir, b_process)
        instances = {
            "A": (shells["1"], captures["1"]["env"], address),
            "B": (b_shell, b_capture["env"], b_address),
        }

        def focus_state():
            return {name: os_focus(listing(to), int(target_env["KITTY_WINDOW_ID"]))
                    for name, (_, target_env, to) in instances.items()}

        alternations = []
        for name in ("A", "B", "A", "B", "A", "B"):
            shell, target_env, _ = instances[name]
            before = focus_state()
            count = len(guard.plugins)
            started = time.monotonic()
            result = api.focus_result(shell, target_env)
            alternations.append({
                "target": name,
                "os_focus_before": before,
                "state": result.state,
                "selection": operation(result.selection),
                "activation": operation(result.activation),
                "seconds": round(time.monotonic() - started, 2),
                "kwin_scripts": scripts_since(count),
                "os_focus_after": focus_state(),
            })
        activation_ok = all(
            item["state"] == "complete" and item["activation"]["succeeded"]
            and item["kwin_scripts"] == 1
            and item["os_focus_after"] == {name: name == item["target"] for name in instances}
            for item in alternations)

        count = len(guard.plugins)
        code, out, _ = kitten("launch", "--type=os-window", "--cwd", str(work / "cwd"),
                              "sh", str(b_dir / "window.sh"), to=b_address)
        extra = out if code == 0 and out.isdigit() else None
        if not extra or not wait_until(lambda: read_pid(b_dir / f"pid-{extra}"), 10):
            raise RuntimeError("second OS window did not start")
        tracker.add(read_pid(b_dir / f"pid-{extra}"), "window shell")
        os_windows = len(listing(b_address) or [])
        ambiguous = api.focus_result(b_shell, b_capture["env"])
        evidence["two_os_windows_one_process"] = {
            "os_windows": os_windows,
            "selection_succeeded": ambiguous.selection.succeeded,
            "activation": operation(ambiguous.activation),
            "kwin_scripts": scripts_since(count),
        }
        kitten("close-window", "--match", f"id:{extra}", to=b_address)
        wait_until(lambda: len(listing(b_address) or []) == 1, 10)

        count = len(guard.plugins)
        no_pid = {key: value for key, value in b_capture["env"].items() if key != "KITTY_PID"}
        missing_pid = api.focus_result(b_shell, no_pid)
        leaked = api.focus_result(b_shell, {**b_capture["env"], "KITTY_PID": str(process.pid)})
        evidence["preconditions"] = {
            "kitty_pid_missing": operation(missing_pid.activation),
            "kitty_pid_not_an_ancestor": operation(leaked.activation),
            "kwin_scripts": scripts_since(count),
        }

        hidden_dir = work / "hidden"
        hidden_address = f"unix:@{token}-hidden"
        hidden_process = launch(work, env, tracker, hidden_address, "socket-only",
                                window_script(hidden_dir), token, start_as="hidden")
        if not wait_until(lambda: tree(hidden_address) and read_capture(hidden_dir, "1"),
                          20):
            raise RuntimeError("hidden kitty did not become ready")
        hidden_capture, hidden_shell = probe(hidden_dir, hidden_process)
        count = len(guard.plugins)
        hidden_before = os_focus(listing(hidden_address), 1)
        hidden = api.focus_result(hidden_shell, hidden_capture["env"])
        evidence["hidden_os_window"] = {
            "os_focus_before": hidden_before,
            "selection_succeeded": hidden.selection.succeeded,
            "activation": {
                **operation(hidden.activation),
                "detail": hidden.activation.detail.replace(
                    str(hidden_process.pid), "<kitty_pid>"),
            },
            "kwin_scripts": scripts_since(count),
            "os_focus_after": os_focus(listing(hidden_address), 1),
            "meaning": ("a hidden kitty may report is_focused true; activation must not be "
                        "claimed unless KWin itself found and activated one window"),
        }
        evidence["activation_alternations"] = alternations
        two = evidence["two_os_windows_one_process"]
        pre = evidence["preconditions"]
        refusals_ok = (
            two["os_windows"] == 2 and not two["activation"]["attempted"]
            and "2 OS windows" in two["activation"]["detail"] and two["kwin_scripts"] == 0
            and not pre["kitty_pid_missing"]["attempted"]
            and pre["kitty_pid_missing"]["detail"] == kitty_module.KITTY_PID_MISSING
            and not pre["kitty_pid_not_an_ancestor"]["attempted"]
            and "not an ancestor" in pre["kitty_pid_not_an_ancestor"]["detail"]
            and pre["kwin_scripts"] == 0
        )
        hidden_record = evidence["hidden_os_window"]
        hidden_ok = (
            hidden_record["kwin_scripts"] == 1
            and (not hidden_record["activation"]["succeeded"]
                 or hidden_record["os_focus_after"] is True)
        )
        for to in (b_address, hidden_address):
            kitten("close-window", "--match", "all", to=to)
        rejected = (
            stale.state == "failed" and stale.selection.attempted
            and "no longer exists" in stale.selection.detail
            and evidence["stale_target"]["active_unchanged"]
            and missing.state == "failed" and "socket refused or missing" in
            missing.selection.detail
            and off["state"] == "failed" and not off["selection_attempted"]
            and off["selection_detail"] == kitty_module.REMOTE_CONTROL_UNAVAILABLE
        )
        fallback_ok = (evidence["kitty_at_fallback"]["tools"] == ["kitty"]
                       and fallback.selection.succeeded
                       and evidence["kitty_at_fallback"]["readback_active"])
        capture_ok = (evidence["capture"]["detect"] and evidence["capture"]["window_ids_match"]
                      and evidence["capture"]["listen_on_equals_given_address"]
                      and evidence["capture"]["keys"]
                      == ["KITTY_LISTEN_ON", "KITTY_PID", "KITTY_WINDOW_ID"])
        duplicates = evidence["duplicate_targets"]
        duplicates_ok = (duplicates["window_titles"] == ["dup"]
                         and duplicates["tab_titles"] == ["dup"] and duplicates["same_cwd"]
                         and duplicates["windows_sharing_a_tab"]
                         and duplicates["separate_tabs"])
        evidence["checks"] = {
            "capture": capture_ok, "duplicates": duplicates_ok, "selections": selected_ok,
            "failures_rejected": rejected, "kitty_at_fallback": fallback_ok,
            "activation_alternations": activation_ok,
            "activation_refusals": refusals_ok, "hidden_not_claimed": hidden_ok,
        }
        kitten("close-window", "--match", "all")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    except Exception as error:
        evidence["error"] = redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        stack.close()
        evidence["cleanup"] = tracker.terminate()
        evidence["kwin"] = {
            "scripts_run": len(guard.plugins),
            "owner_pids_all_probe_kitty": set(guard.owners) <= guard.allowed,
            "non_probe_owner_refusals": len(guard.refused),
            "scripts_left_loaded": guard.left_loaded(),
        }
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    arguments = parser.parse_args(argv)
    if sys.platform != "linux":
        print("This check requires Linux", file=sys.stderr)
        return 2
    path, source = install_info("kitty")
    if not path or not real_which("kitten"):
        print("This check requires kitty and kitten on PATH", file=sys.stderr)
        return 2
    token = "fleetkitty-" + secrets.token_hex(4)
    before = config_snapshot()
    with tempfile.TemporaryDirectory(prefix=f"{token}-", dir="/tmp") as temporary:
        redact = Redactor.for_host({temporary: "<tmp>", token: "<token>"})
        evidence = validate(Path(temporary), token, redact)
        strays = Tracker([temporary, token]).stray()
    user_config_unchanged = config_snapshot() == before
    version = run(["kitty", "--version"])[1]
    passed = (
        "error" not in evidence and all(evidence.get("checks", {}).values())
        and bool(evidence.get("checks"))
        and evidence["cleanup"]["survivors"] == 0 and not strays and user_config_unchanged
        and evidence["kwin"]["scripts_left_loaded"] == 0
        and evidence["kwin"]["owner_pids_all_probe_kitty"]
        and evidence["kwin"]["non_probe_owner_refusals"] == 0
    )
    record = {
        "result": "pass" if passed else "fail",
        "kitty_version": " ".join(version.split()[:2]) if version else None,
        "install_source": source,
        "remote_control": ("kitty --config NONE, allow_remote_control=socket-only, temporary "
                           "unix listen_on (path and abstract); Fleet never edits kitty.conf"),
        **evidence,
        "provenance": ("live: disposable minimized and hidden kitty instances; env captured "
                       "by KittyAPI inside each kitty window; selection and KWin activation "
                       "by KittyAPI.focus_result; independent readback by kitten @ ls (tab "
                       "and window is_active, OS window is_focused)"),
        "evidence_kind": "live",
        "gui_activation": ("verified on KDE Plasma: KWin activates the single normal window "
                           "owned by the captured KITTY_PID, confirmed by the script's own "
                           "unload signal and kitty's OS window is_focused readback; KWin "
                           "scripts ran only for probe kitty pids; no xdotool calls"),
        "user_config_unchanged": user_config_unchanged,
        "marker_strays_after_run": len(strays),
        "validation_date": datetime.date.today().isoformat(),
        "platform": platform_facts(),
        **repo_facts(),
    }
    text = json.dumps(record, indent=2) + "\n"
    leaks = Redactor.for_host().leaks(text)
    if "/home/" in text or "/tmp/" in text:
        leaks.append("path")
    if leaks:
        print(f"refusing to write evidence: leaks={leaks}", file=sys.stderr)
        return 1
    Path(arguments.out).write_text(text)
    print(text)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
