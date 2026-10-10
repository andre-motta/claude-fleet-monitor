"""Validate Kitty remote-control selection with disposable isolated instances.

Local-only Linux helper; it is never run in CI. It starts one minimized kitty
with --config NONE, allow_remote_control=socket-only and a temporary unix
listen_on, plus one kitty with remote control off. Window environments are
captured by the real KittyAPI inside each kitty window. Duplicate-title
windows and tabs are selected through KittyAPI.focus_result and confirmed by
an independent `kitten @ ls`. It never edits user config, never calls KWin,
qdbus or xdotool, and only signals processes it started. The evidence JSON
contains placeholders only, never home paths, user names or host names.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
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

from claude_fleet_monitor.terminal_apis import kitty as kitty_module
from claude_fleet_monitor.terminal_apis.kitty import KittyAPI

ROOT = Path(__file__).resolve().parents[1]
OWNED = ("src/claude_fleet_monitor/terminal_apis/kitty.py", "validation/kitty.py")
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


def launch(work, env, tracker, address, remote_control, script, token):
    process = subprocess.Popen(
        ["kitty", "--config", "NONE", "-o", f"allow_remote_control={remote_control}",
         "-o", "confirm_os_window_close=0", "--listen-on", address,
         "--class", f"{token}-kitty", "--start-as=minimized",
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
    for name in ("cfg", "cache", "cwd", "io", "off"):
        (work / name).mkdir(parents=True, mode=0o700)
    tracker = Tracker([str(work)])
    env = child_env(work)
    io = work / "io"
    address = f"unix:{work}/rc.sock"
    evidence = {}

    def kitten(*arguments, to=address):
        return run(["kitten", "@", "--to", to, *arguments], env=env)

    def tree(to=address):
        code, out, _ = kitten("ls", to=to)
        try:
            return kitty_tree(json.loads(out)) if code == 0 else None
        except ValueError:
            return None

    api = KittyAPI()
    try:
        process = launch(work, env, tracker, address, "socket-only",
                         window_script(io), token)
        if not wait_until(lambda: tree() and read_capture(io, "1"), 20):
            raise RuntimeError("kitty remote control did not become ready")
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
                "selection": {"attempted": result.selection.attempted,
                              "succeeded": result.selection.succeeded,
                              "detail": result.selection.detail},
                "activation": {"attempted": result.activation.attempted,
                               "detail": result.activation.detail},
                "readback_target_tab_active": target["tab_active"],
                "readback_target_window_active": target["window_active"],
                "readback_same_tab_others_active": [s["window_active"] for s in same_tab],
                "readback_other_tabs_active": sorted({s["tab_active"] for s in other_tabs}),
            })
        evidence["selections"] = selections
        selected_ok = all(
            item["selection"]["succeeded"] and item["state"] == "partial"
            and not item["activation"]["attempted"]
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
                      and evidence["capture"]["keys"] == ["KITTY_LISTEN_ON", "KITTY_WINDOW_ID"])
        duplicates = evidence["duplicate_targets"]
        duplicates_ok = (duplicates["window_titles"] == ["dup"]
                         and duplicates["tab_titles"] == ["dup"] and duplicates["same_cwd"]
                         and duplicates["windows_sharing_a_tab"]
                         and duplicates["separate_tabs"])
        evidence["checks"] = {
            "capture": capture_ok, "duplicates": duplicates_ok, "selections": selected_ok,
            "failures_rejected": rejected, "kitty_at_fallback": fallback_ok,
        }
        kitten("close-window", "--match", "all")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    except Exception as error:
        evidence["error"] = redact(f"{type(error).__name__}: {error}")[:300]
    finally:
        evidence["cleanup"] = tracker.terminate()
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
    )
    record = {
        "result": "pass" if passed else "fail",
        "kitty_version": " ".join(version.split()[:2]) if version else None,
        "install_source": source,
        "remote_control": ("kitty --config NONE, allow_remote_control=socket-only, temporary "
                           "unix listen_on; Fleet never edits kitty.conf"),
        **evidence,
        "provenance": ("live: disposable minimized kitty instances; env captured by KittyAPI "
                       "inside each kitty window; selection by KittyAPI.focus_result; "
                       "independent readback by kitten @ ls (tab and window is_active)"),
        "evidence_kind": "live",
        "gui_activation": ("unverified: not claimed (activation_supported is False); no KWin, "
                           "qdbus or xdotool calls"),
        "kwin_calls": 0,
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
