"""Run the Pi validator in a unique, bounded tmux server."""

import argparse
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def run_inside(output_path, error_path, status_path, validator):
    validator = Path(validator)
    result = subprocess.run(
        [sys.executable, str(validator), "--require-tmux"],
        cwd=validator.parents[2],
        capture_output=True,
        text=True,
    )
    Path(output_path).write_text(result.stdout)
    Path(error_path).write_text(result.stderr)
    Path(status_path).write_text(str(result.returncode))
    return result.returncode


def run(timeout):
    tmux = shutil.which("tmux")
    if tmux is None:
        print("tmux is required for Pi validation", file=sys.stderr)
        return 1
    validator = Path(__file__).with_name("validate_pi.py").resolve()
    socket_name = f"fleet-pi-{os.getpid()}-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="fleet-pi-tmux-") as temporary:
        root = Path(temporary)
        output = root / "stdout.json"
        errors = root / "stderr.txt"
        status = root / "status.txt"
        inside = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--inside",
            str(output),
            str(errors),
            str(status),
            str(validator),
        ]
        server = [tmux, "-L", socket_name, "-f", "/dev/null"]
        command = [
            *server,
            "new-session", "-d",
            "-s", "fleet-pi-validation",
            "-c", str(validator.parents[2]),
            f"sleep {timeout + 30:g}",
        ]
        started = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if started.returncode != 0:
            print(started.stderr.strip(), file=sys.stderr)
            return started.returncode
        try:
            retained = subprocess.run(
                [
                    *server, "set-option", "-t", "fleet-pi-validation",
                    "remain-on-exit", "on",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if retained.returncode != 0:
                print(retained.stderr.strip(), file=sys.stderr)
                return retained.returncode
            command = [
                *server,
                "respawn-pane", "-k",
                "-t", "fleet-pi-validation:0.0",
                "-c", str(validator.parents[2]),
                shlex.join(inside),
            ]
            started = subprocess.run(
                command, capture_output=True, text=True, timeout=10
            )
            if started.returncode != 0:
                print(started.stderr.strip(), file=sys.stderr)
                return started.returncode
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if status.exists():
                    break
                pane = subprocess.run(
                    [
                        *server, "display-message", "-p",
                        "-t", "fleet-pi-validation:0.0", "#{pane_dead}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if pane.returncode != 0 or pane.stdout.strip() == "1":
                    captured = subprocess.run(
                        [
                            *server, "capture-pane", "-p", "-S", "-200",
                            "-t", "fleet-pi-validation:0.0",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    print(captured.stdout, file=sys.stderr)
                    return 1
                time.sleep(0.1)
            else:
                print(f"Pi validation timed out after {timeout:g} seconds", file=sys.stderr)
                return 124
            try:
                returncode = int(status.read_text().strip())
            except (OSError, ValueError):
                print("Pi validation did not record a valid exit status", file=sys.stderr)
                return 1
            if output.exists():
                sys.stdout.write(output.read_text())
            if errors.exists():
                sys.stderr.write(errors.read_text())
            return returncode
        finally:
            try:
                subprocess.run(
                    [*server, "kill-server"],
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--inside", nargs=4, metavar=("OUT", "ERR", "STATUS", "VALIDATOR"))
    args = parser.parse_args()
    if args.inside:
        raise SystemExit(run_inside(*args.inside))
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        parser.error("--timeout must be a positive finite number")
    raise SystemExit(run(args.timeout))


if __name__ == "__main__":
    main()
