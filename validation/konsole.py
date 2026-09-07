"""Validate native Konsole tab selection using disposable synthetic sessions."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from claude_fleet_monitor.terminal_apis.konsole import KonsoleAPI


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    except (OSError, IndexError):
        return None
    return None if fields[0] == "Z" else fields[19]


def child(output):
    path = Path(output)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "pid": os.getpid(),
        "process_start": process_identity(os.getpid()),
        "cwd": os.getcwd(),
        "env": {key: os.environ.get(key, "") for key in (
            "KONSOLE_DBUS_SERVICE", "KONSOLE_DBUS_SESSION", "KONSOLE_VERSION",
        )},
    }))
    temporary.replace(path)
    time.sleep(90)


def cleanup(process, records):
    children = [json.loads(path.read_text()) for path in records if path.exists()]
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def remaining():
        return [item for item in children if item["process_start"] is not None
                and process_identity(item["pid"]) == item["process_start"]]

    for action in (signal.SIGTERM, signal.SIGKILL):
        for item in remaining():
            try:
                os.kill(item["pid"], action)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while remaining() and time.monotonic() < deadline:
            time.sleep(0.05)
    if remaining():
        raise RuntimeError("Disposable Konsole children did not exit")
    return len(children)


def validate():
    if sys.platform != "linux":
        raise RuntimeError("This native validation helper requires Linux")
    qdbus = next((shutil.which(name) for name in ("qdbus", "qdbus6", "qdbus-qt6")
                  if shutil.which(name)), None)
    konsole = shutil.which("konsole")
    if not qdbus or not konsole:
        raise RuntimeError("Konsole and a Qt D-Bus executable must be installed")

    def query(*arguments):
        return subprocess.run(
            [qdbus, *arguments], capture_output=True, text=True,
            timeout=5, check=True,
        ).stdout.strip()

    with tempfile.TemporaryDirectory(prefix="fleet-konsole-native-") as tmp:
        root = Path(tmp)
        environment = os.environ.copy()
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            directory = root / key.lower()
            directory.mkdir()
            environment[key] = str(directory)
        records = [root / name for name in ("first.json", "second.json", "sentinel.json")]
        script = str(Path(__file__).resolve())
        tabs = root / "tabs.txt"
        tabs.write_text("\n".join(
            "title: Fleet validation;; command: "
            + shlex.join([sys.executable, script, "--child", str(record)])
            + ";; workdir: " + str(root)
            for record in records[:2]
        ) + "\n")
        with (root / "konsole.log").open("w+") as log:
            process = subprocess.Popen(
                [konsole, "--separate", "--builtin-profile", "--show-tabbar",
                 "--tabs-from-file", str(tabs), "-e", sys.executable, script,
                 "--child", str(records[2])],
                env=environment, stdout=log, stderr=log,
            )
            try:
                deadline = time.monotonic() + 20
                while not all(path.exists() for path in records):
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError("Disposable Konsole did not initialize: " + log.read())
                    time.sleep(0.1)
                children = [json.loads(path.read_text()) for path in records]
                assert all(item["process_start"] is not None for item in children)
                values = children[:2]
                service = values[0]["env"]["KONSOLE_DBUS_SERVICE"]
                assert service and service == values[1]["env"]["KONSOLE_DBUS_SERVICE"]
                assert all(value["cwd"] == str(root) for value in values)
                titles = [query(service, value["env"]["KONSOLE_DBUS_SESSION"],
                                "org.kde.konsole.Session.title", "1") for value in values]
                assert titles == ["Fleet validation", "Fleet validation"], titles
                api = KonsoleAPI()
                proof = []
                for value in (values[0], values[1], values[0]):
                    target = api.find_tab(value["pid"], value["env"])
                    assert target, "Synthetic session was not resolved"
                    svc, window, session = target.split("|")
                    assert svc == service
                    assert "/Sessions/" + session == value["env"]["KONSOLE_DBUS_SESSION"]
                    assert api.switch_tab(target, value["env"])
                    observed = query(svc, "/Windows/" + window,
                                     "org.kde.konsole.Window.currentSession")
                    assert observed == session
                    proof.append({"session": session, "observed_current_session": observed})
                assert len({item["session"] for item in proof}) == 2
                assert not api.switch_tab(service + "|" + window + "|2147483647", values[0]["env"])
                evidence = {
                    "result": "pass", "konsole_version": values[0]["env"]["KONSOLE_VERSION"],
                    "qdbus_command": Path(qdbus).name, "duplicate_titles": True,
                    "same_cwd": True, "tab_selection": proof, "stale_target_rejected": True,
                    "window_activation": "not exercised or claimed",
                }
            finally:
                count = cleanup(process, records)
            assert count == 3
            evidence["synthetic_children_exited"] = count
    print(json.dumps(evidence, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.child)
    else:
        validate()


if __name__ == "__main__":
    main()
