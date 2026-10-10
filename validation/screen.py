"""Validate the GNU screen adapter against isolated live screen sessions.

Local-only Linux helper; it is never run in CI. It starts two screen sessions
in a temporary SCREENDIR with a temporary SCREENRC, attaches real displays in
private PTYs, and drives ScreenAPI exactly as the focus path does. Selection is
checked independently by keystroke routing into the window shells. It never
reads or edits user config, never touches screen sessions it did not start,
never calls KWin, qdbus or xdotool, and only signals processes it started,
identified by PID plus kernel start time. Run it as a script so the probe
helpers in this directory are importable; it writes public-safe JSON.
"""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import tempfile
import time
from unittest.mock import patch

from probe_terminals import (
    PtyClient,
    Redactor,
    Tracker,
    config_snapshot,
    install_info,
    platform_facts,
    process_facts,
    process_cmdline,
    read_pid,
    run,
    typed_target,
    wait_until,
)

from claude_fleet_monitor.terminal_apis import screen as screen_module
from claude_fleet_monitor.terminal_apis.screen import ScreenAPI

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = "src/claude_fleet_monitor/terminal_apis/screen.py"
VALIDATOR = "validation/screen.py"
WINDOWS = ("0", "1", "2", "3")
CAPTURE_CODE = (
    "import json, subprocess, sys\n"
    "def forbidden(*args, **kwargs):\n"
    "    raise AssertionError('capture started a process')\n"
    "subprocess.run = subprocess.Popen = forbidden\n"
    "from claude_fleet_monitor.terminal_apis.screen import ScreenAPI\n"
    "json.dump({'detect': ScreenAPI.detect(), 'env': ScreenAPI.capture_env()}, sys.stdout)\n"
)
NO_GUI = ("not supported: a screen session owns no GUI window, ScreenAPI declares "
          "activation_supported False, and no KWin, qdbus or xdotool calls were made")


def window_script(directory):
    script = Path(directory) / "window.sh"
    script.write_text(
        f'd={shlex.quote(str(directory))}; i="$WINDOW"\n'
        f'{shlex.quote(sys.executable)} -c {shlex.quote(CAPTURE_CODE)} '
        '> "$d/cap-$i.tmp" 2> "$d/err-$i" && mv "$d/cap-$i.tmp" "$d/cap-$i"\n'
        'echo $$ > "$d/pid-$i.tmp" && mv "$d/pid-$i.tmp" "$d/pid-$i"\n'
        'while IFS= read -r line; do printf "%s\\n" "$line" >> "$d/in-$i"; done\n'
    )
    return str(script)


def read_capture(directory, window):
    try:
        return json.loads((Path(directory) / f"cap-{window}").read_text())
    except (OSError, ValueError):
        return None


def summarize(result):
    return {
        "state": result.state,
        "selection": {"attempted": result.selection.attempted,
                      "succeeded": result.selection.succeeded,
                      "detail": result.selection.detail},
        "activation": {"attempted": result.activation.attempted,
                       "succeeded": result.activation.succeeded,
                       "detail": result.activation.detail},
    }


def file_digest(relative):
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def repo_facts():
    code, head, _ = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    _, dirty, _ = run(["git", "-C", str(ROOT), "status", "--porcelain", "--", ADAPTER,
                       VALIDATOR])
    return {
        "tested_commit": head if code == 0 else None,
        "modified_since_commit": bool(dirty),
        "sha256": {ADAPTER: file_digest(ADAPTER), VALIDATOR: file_digest(VALIDATOR)},
    }


class Fixture:
    """Two isolated screen sessions whose names share a prefix."""

    def __init__(self, root, token):
        self.root = root
        self.session = f"{token}-screen"
        self.other = f"{token}-screenx"
        self.io = root / "io"
        self.other_io = root / "other-io"
        for path in (root / "sockets", root / "cwd", self.io, self.other_io):
            path.mkdir(parents=True, mode=0o700)
        self.rc = root / "screenrc"
        self.rc.write_text("startup_message off\n")
        self.cwd = str(root / "cwd")
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ("STY", "WINDOW", "TMUX", "TMUX_PANE")
                    and not key.startswith("ZELLIJ")}
        self.env.update({"SCREENDIR": str(root / "sockets"), "SCREENRC": str(self.rc),
                         "TERM": "xterm-256color"})
        self.tracker = Tracker([str(root), self.session])
        self.displays = []
        self.stys = []

    def screen(self, name, *arguments):
        return run(["screen", "-c", str(self.rc), "-S", name, *arguments],
                   env=self.env, cwd=self.cwd)

    def start(self, name, directory, count):
        script = window_script(directory)
        code, _, _ = run(["screen", "-c", str(self.rc), "-dmS", name, "-t", "dup", "sh",
                          script], env=self.env, cwd=self.cwd)
        if code != 0:
            raise RuntimeError("screen -dmS failed")
        if not wait_until(lambda: (directory / "pid-0").exists(), 15):
            raise RuntimeError("first screen window did not start")
        server = process_facts(read_pid(directory / "pid-0"))["ppid"]
        self.tracker.add(server, "server")
        sty = f"{server}.{name}"
        self.stys.append(sty)
        for _ in range(count - 1):
            self.screen(sty, "-X", "screen", "-t", "dup", "sh", script)
        windows = [str(index) for index in range(count)]
        if not wait_until(lambda: all((directory / f"pid-{i}").exists() for i in windows), 15):
            raise RuntimeError("screen windows did not start")
        self.tracker.sweep()
        pids = {i: read_pid(directory / f"pid-{i}") for i in windows}
        for pid in pids.values():
            self.tracker.add(pid, "window")
        return sty, server, pids

    def attach(self, sty):
        client = PtyClient(["screen", "-c", str(self.rc), "-x", sty], self.env, self.cwd,
                           self.tracker, "display")
        self.displays.append(client)
        if not wait_until(lambda: self.windows_query(sty), 10):
            raise RuntimeError("screen display did not attach")
        time.sleep(1.0)
        return client

    def windows_query(self, sty):
        return self.screen(sty, "-Q", "windows")[1]

    def number(self, name):
        code, out, _ = self.screen(name, "-Q", "number")
        token = out.split()[0] if code == 0 and out else ""
        return token if token.isdigit() else None


def focus(api, pids, captures, window):
    return api.focus_result(pids[window], dict(captures[window]["env"]))


def validate(fixture, checks, cases):
    api = ScreenAPI()
    server_sty, server, pids = fixture.start(fixture.session, fixture.io, len(WINDOWS))
    other_sty, _, _ = fixture.start(fixture.other, fixture.other_io, 2)
    captures = {window: read_capture(fixture.io, window) for window in WINDOWS}
    checks["capture_ran_in_every_window"] = all(captures.values())
    if not checks["capture_ran_in_every_window"]:
        raise RuntimeError("capture did not run in every window")
    sty = captures["0"]["env"]["STY"]
    checks["capture_detects_screen_without_subprocess"] = all(
        item["detect"] for item in captures.values())
    checks["capture_keys_exact"] = all(
        set(item["env"]) == {"STY", "WINDOW"} for item in captures.values())
    checks["sty_shared_and_window_unique"] = (
        {item["env"]["STY"] for item in captures.values()} == {sty}
        and [captures[w]["env"]["WINDOW"] for w in WINDOWS] == list(WINDOWS))
    checks["sty_is_server_pid_dot_session"] = sty == server_sty
    checks["find_tab_returns_window"] = all(
        api.find_tab(pids[w], captures[w]["env"]) == w for w in WINDOWS)
    cases["identity"] = {
        "sty_shape": "<server pid>.<session>",
        "window_titles": "duplicate",
        "window_cwd": "identical",
        "prefix_sharing_session_present": True,
        "server_comm": process_facts(server)["comm"],
        "server_argv0": process_cmdline(server).split(" ", 1)[0],
    }

    before = fixture.number(sty)
    result = focus(api, pids, captures, "1")
    cases["detached_never_attached"] = {
        "result": summarize(result), "number_before": before,
        "number_after": fixture.number(sty), "windows_query_empty": not fixture.windows_query(sty),
    }
    checks["detached_fails_with_named_step"] = (
        result.state == "failed"
        and result.selection.detail == "no attached screen display"
        and fixture.number(sty) == before)

    first = fixture.attach(sty)
    fixture.attach(other_sty)
    other_before = fixture.number(other_sty)
    one_display = []
    for target in ("1", "0", "2", "3"):
        result = focus(api, pids, captures, target)
        routed = typed_target(first, fixture.io, f"one-{target}")
        one_display.append({"target": target, "result": summarize(result),
                            "number": fixture.number(sty), "keystroke_window": routed})
    cases["one_display"] = one_display
    checks["one_display_selection_verified"] = all(
        item["result"]["state"] == "partial"
        and item["result"]["selection"]["succeeded"]
        and not item["result"]["activation"]["attempted"]
        and item["number"] == item["target"]
        and item["keystroke_window"] == [item["target"]]
        for item in one_display)

    current = fixture.number(sty)
    try:
        api.switch_tab("9", {"STY": sty, "WINDOW": "9"})
        unknown = "claimed"
    except screen_module.ScreenFocusError as error:
        unknown = str(error)
    cases["unknown_window"] = {"detail": unknown, "number_after": fixture.number(sty)}
    checks["unknown_window_rejected_by_readback"] = (
        unknown == f"screen shows window {current}, not window 9"
        and fixture.number(sty) == current)

    fixture.screen(sty, "-p", "3", "-X", "kill")
    wait_until(lambda: fixture.number(sty) != "3", 5)
    current = fixture.number(sty)
    result = focus(api, pids, captures, "3")
    routed = typed_target(first, fixture.io, "stale-3")
    cases["stale_window"] = {"result": summarize(result), "number_after": fixture.number(sty),
                             "keystroke_window": routed}
    checks["stale_window_rejected"] = (
        result.state == "failed"
        and result.selection.detail == f"screen shows window {current}, not window 3"
        and routed == [current])

    second = fixture.attach(sty)
    two_displays = []
    for primed, target in (((second, first), "1"), ((first, second), "0")):
        for display in primed:
            typed_target(display, fixture.io, f"prime-{target}-{display.pid}")
        result = focus(api, pids, captures, target)
        number = fixture.number(sty)
        routed = {name: typed_target(display, fixture.io, f"two-{target}-{name}")
                  for name, display in (("d1", first), ("d2", second))}
        moved = sorted(name for name, got in routed.items() if got == [target])
        two_displays.append({
            "target": target,
            "last_input_display": "d1" if primed[-1] is first else "d2",
            "newest_display": "d2", "result": summarize(result), "number": number,
            "displays_showing_target": moved,
        })
    cases["two_displays"] = two_displays
    if all(item["displays_showing_target"] == ["d2"] for item in two_displays):
        cases["two_displays_observed_rule"] = "most recently attached display"
    elif all(item["displays_showing_target"] == [item["last_input_display"]]
             for item in two_displays):
        cases["two_displays_observed_rule"] = "display that last received input"
    else:
        cases["two_displays_observed_rule"] = "inconsistent"
    checks["two_displays_selection_verified_on_one_display"] = all(
        item["result"]["selection"]["succeeded"] and item["number"] == item["target"]
        and len(item["displays_showing_target"]) >= 1
        for item in two_displays)

    checks["unrelated_session_unchanged"] = fixture.number(other_sty) == other_before
    cases["unrelated_session"] = {"name_shares_prefix": True,
                                  "current_window_unchanged":
                                      checks["unrelated_session_unchanged"]}

    for _ in range(len(fixture.displays) + 1):
        if not fixture.windows_query(sty):
            break
        fixture.screen(sty, "-X", "detach")
        wait_until(lambda: not fixture.windows_query(sty), 3)
    before = fixture.number(sty)
    target = "0" if before != "0" else "1"
    result = focus(api, pids, captures, target)
    cases["detached_after_attach"] = {
        "result": summarize(result), "number_before": before,
        "number_after": fixture.number(sty), "windows_query_empty": not fixture.windows_query(sty),
    }
    checks["detached_after_attach_fails"] = (
        result.state == "failed"
        and result.selection.detail == "no attached screen display"
        and fixture.number(sty) == before)

    calls = []
    with patch.object(screen_module, "_run", side_effect=lambda argv: calls.append(argv)):
        malformed = [api.focus_result(pids["0"], {"STY": value, "WINDOW": "0"})
                     for value in ("-X", f"{server}.{fixture.session}/x", "x.y", "")]
    checks["malformed_sty_never_reaches_argv"] = (
        not calls and all(item.state == "failed" for item in malformed))

    fixture.screen(sty, "-X", "quit")
    wait_until(lambda: fixture.screen(sty, "-Q", "number")[0] not in (0, None), 5)
    result = focus(api, pids, captures, "0")
    cases["stale_session"] = {"result": summarize(result)}
    checks["stale_session_fails"] = (
        result.state == "failed"
        and result.selection.detail == "screen session could not be queried")
    fixture.screen(other_sty, "-X", "quit")


def user_sessions():
    """List socket names in the user's screen directories without contacting them."""
    user = getpass.getuser()
    directories = [os.environ.get("SCREENDIR"), f"/run/screen/S-{user}",
                   f"/var/run/screen/S-{user}", str(Path.home() / ".screen")]
    found = {}
    for directory in filter(None, directories):
        try:
            found[directory] = sorted(os.listdir(directory))
        except OSError:
            continue
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help="write the evidence JSON here")
    arguments = parser.parse_args(argv)
    if sys.platform != "linux":
        print("This check requires Linux", file=sys.stderr)
        return 2
    path, source = install_info("screen")
    if not path:
        print("screen is not installed", file=sys.stderr)
        return 2
    token = "fleetscreen-" + secrets.token_hex(4)
    config_before = config_snapshot()
    sessions_before = user_sessions()
    saved = {key: os.environ.get(key) for key in ("SCREENDIR", "SCREENRC", "STY", "WINDOW")}
    checks = {}
    cases = {}
    error = None
    with tempfile.TemporaryDirectory(prefix=f"{token}-", dir="/tmp") as temporary:
        root = Path(temporary)
        fixture = Fixture(root, token)
        redact = Redactor.for_host({temporary: "<tmp>", token: "<token>"})
        os.environ.pop("STY", None)
        os.environ.pop("WINDOW", None)
        os.environ["SCREENDIR"] = fixture.env["SCREENDIR"]
        os.environ["SCREENRC"] = fixture.env["SCREENRC"]
        try:
            validate(fixture, checks, cases)
        except Exception as failure:
            error = redact(f"{type(failure).__name__}: {failure}")[:300]
        finally:
            for sty in fixture.stys:
                fixture.screen(sty, "-X", "quit")
            cleanup = fixture.tracker.terminate()
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        stray = Tracker([temporary, token]).stray()
    checks["cleanup_no_survivors"] = cleanup["survivors"] == 0 and not stray
    checks["user_config_unchanged"] = config_snapshot() == config_before
    checks["user_screen_sessions_unchanged"] = user_sessions() == sessions_before
    passed = error is None and bool(checks) and all(checks.values())
    version = run(["screen", "--version"])[1].split("(")[0].strip()
    evidence = {
        "schema": "screen-validation/1",
        "result": "pass" if passed else "fail",
        "verdict": "adapter",
        "versions": {"screen": version or None, "install_source": source,
                     "python": sys.version.split()[0]},
        "platform": platform_facts(),
        **repo_facts(),
        "provenance": ("live: real screen servers in a temporary SCREENDIR and real "
                       "displays in private PTYs; ScreenAPI argv executed unmodified; "
                       "selection confirmed by -Q number and keystroke routing"),
        "gui_activation": NO_GUI,
        "version_floor": ("not established: only this version was validated; the adapter "
                          "gates on behavior (-Q readback and a non-empty -Q windows)"),
        "select_argv": ["screen", "-S", "<STY>", "-X", "select", "<WINDOW>"],
        "readback_argv": ["screen", "-S", "<STY>", "-Q", "number"],
        "display_guard_argv": ["screen", "-S", "<STY>", "-Q", "windows"],
        "detection_signal": "STY matching <digits>.<name> plus a decimal WINDOW",
        "find_tab": "env-only: WINDOW from the captured env; None without valid STY and WINDOW",
        "process_comm": {"server": "screen", "server_argv0": "SCREEN", "client": "screen",
                         "add_to_terminal_process_names": False},
        "proposed_detection_slot": "immediately before GenericAPI",
        "multi_display_rule": ("select and -Q number act on the same single display "
                               "(see cases.two_displays_observed_rule); success proves "
                               "that display shows the window, not what other displays show"),
        "checks": checks,
        "cases": cases,
        "error": error,
        "cleanup": {**cleanup, "marker_strays": len(stray)},
        "kwin_calls": 0,
        "labels": {"live": "observed on this host with real screen processes",
                   "instrumented": "adapter seam wrapped to count argv"},
    }
    text = redact(json.dumps(evidence, indent=2) + "\n")
    leaks = Redactor.for_host().leaks(text)
    if "/home/" in text:
        leaks.append("/home/")
    if leaks:
        print(f"refusing to write evidence: leaks={leaks}", file=sys.stderr)
        return 1
    if arguments.out:
        Path(arguments.out).write_text(text)
    print(text)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
