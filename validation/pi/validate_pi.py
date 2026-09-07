"""Run the real Pi lifecycle against an isolated synthetic provider."""

import argparse
import http.server
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


class FixtureProvider(http.server.BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        type(self).calls += 1
        if type(self).calls > 2:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                b'{"error":{"message":"Synthetic private provider error",'
                b'"type":"invalid_request_error"}}'
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if type(self).calls == 1:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "fixture-call",
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": '{"path":"fixture.txt"}',
                    },
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "Synthetic response."}
            finish = "stop"
        for content, reason in ((delta, None), ({}, finish)):
            event = {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "fixture",
                "choices": [{
                    "index": 0,
                    "delta": content,
                    "finish_reason": reason,
                }],
            }
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


class FleetObserver:
    def __init__(self, fleet_dir):
        self.fleet_dir = fleet_dir
        self.events = []
        self._seen = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self.scan()

    def scan(self):
        for path in self.fleet_dir.glob("fleet-v1-*.json"):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if record.get("harness_id", record.get("agent")) != "pi":
                continue
            key = (record.get("canonical_id"), record.get("sequence"))
            if key in self._seen:
                continue
            self._seen.add(key)
            self.events.append({
                key: record.get(key)
                for key in (
                    "canonical_id", "session_id", "instance_id", "sequence",
                    "pid", "process_start", "status", "detail", "tool",
                    "last_event", "terminal", "terminal_env",
                )
            })

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.scan()
            for record in reversed(self.events):
                if predicate(record):
                    return record
            time.sleep(0.01)
        raise RuntimeError("Fleet state transition timed out")

    def _watch(self):
        while not self._stop.wait(0.005):
            self.scan()


class RpcProcess:
    def __init__(self, command, cwd, environment):
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.output = queue.Queue()
        self.errors = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.process.stdout:
            self.output.put(json.loads(line))

    def _read_stderr(self):
        self.errors.extend(self.process.stderr.readlines())

    def send(self, payload):
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def wait_output(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.output.get(
                    timeout=max(0.01, deadline - time.monotonic())
                )
            except queue.Empty as error:
                raise RuntimeError("Pi RPC response timed out") from error
            if predicate(event):
                return event
        raise RuntimeError("Pi RPC response timed out")

    def request(self, request_id, payload, timeout=20):
        self.send({"id": request_id, **payload})
        return self.wait_output(
            lambda item: item.get("type") == "response"
            and item.get("id") == request_id,
            timeout,
        )

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)


def read_current_records(fleet_dir):
    records = []
    for path in fleet_dir.glob("fleet-v1-*.json"):
        try:
            records.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass
    return records


def base_pi_command(pi_command, config, sessions):
    return [
        pi_command,
        "--mode", "rpc",
        "--provider", "fixture",
        "--model", "fixture",
        "--offline",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-approve",
        "--session-dir", str(sessions),
    ]


def active_tmux_pane(command):
    result = subprocess.run(
        [*command, "list-panes", "-a", "-F", "#{pane_id} #{pane_active}"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return next(
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.endswith(" 1")
    )


def verify_tmux_focus(started, fleet_dir):
    socket = os.environ["TMUX"].split(",", 1)[0]
    command = ["tmux", "-S", socket]
    target_pane = os.environ["TMUX_PANE"]
    other = subprocess.run(
        [
            *command, "split-window", "-d", "-P", "-F", "#{pane_id}",
            "sleep 60",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    ).stdout.strip()
    try:
        subprocess.run(
            [*command, "select-pane", "-t", other], timeout=5, check=True
        )
        before = active_tmux_pane(command)
        from claude_fleet_monitor import discovery
        from claude_fleet_monitor.focus import focus_session

        discovery.FLEET_DIR = fleet_dir
        result = focus_session(started["canonical_id"])
        after = active_tmux_pane(command)
        evidence = result.to_dict()
        evidence.update({
            "target_pane": target_pane,
            "active_pane_before": before,
            "active_pane_after": after,
        })
        if (
            result.backend != "tmux"
            or not result.selection.succeeded
            or before == target_pane
            or after != target_pane
        ):
            raise RuntimeError(
                f"Pi was not independently selected in tmux: {evidence}"
            )
        return evidence
    finally:
        subprocess.run(
            [*command, "kill-pane", "-t", other],
            capture_output=True,
            timeout=5,
        )


def validate(require_tmux):
    FixtureProvider.calls = 0
    pi_command = shutil.which("pi")
    hook_command = shutil.which("claude-fleet-hook")
    tmux_command = shutil.which("tmux")
    if pi_command is None or hook_command is None:
        raise RuntimeError("pi and claude-fleet-hook must be on PATH")
    if require_tmux and (tmux_command is None or not os.environ.get("TMUX")):
        raise RuntimeError("run this validator inside an isolated tmux session")

    with tempfile.TemporaryDirectory(prefix="fleet-pi-validation-") as temporary:
        root = Path(temporary)
        config = root / "config"
        sessions = root / "sessions"
        fleet_dir = root / "fleet"
        config.mkdir()
        sessions.mkdir()
        fleet_dir.mkdir()
        fixture_extension = Path(__file__).with_name("fixture-extension.mjs").resolve()
        fixture_file = root / "fixture.txt"
        fixture_file.write_text("Public synthetic validation fixture.\n")
        settings = {
            "retry": {"enabled": False},
            "compaction": {"enabled": False},
            "extensions": [str(fixture_extension)],
        }
        (config / "settings.json").write_text(json.dumps(settings, indent=2))

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FixtureProvider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        (config / "models.json").write_text(json.dumps({
            "providers": {
                "fixture": {
                    "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                    "api": "openai-completions",
                    "apiKey": "synthetic-local-key",
                    "models": [{
                        "id": "fixture",
                        "contextWindow": 128000,
                        "maxTokens": 2048,
                        "reasoning": False,
                    }],
                }
            }
        }))
        environment = os.environ.copy()
        environment.update({
            "HOME": str(root),
            "USERPROFILE": str(root),
            "PI_CODING_AGENT_DIR": str(config),
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "FLEET_DIR": str(fleet_dir),
            "LANG": "C.UTF-8",
        })

        install = subprocess.run(
            [sys.executable, "-m", "claude_fleet_monitor.cli", "install", "--agent", "pi"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )
        if install.returncode != 0:
            raise RuntimeError(f"Pi install failed: {install.stdout}{install.stderr}")
        installed_settings = json.loads((config / "settings.json").read_text())
        if installed_settings.get("extensions") != [str(fixture_extension)]:
            raise RuntimeError("Pi install replaced an unrelated extension")
        repeated_install = subprocess.run(
            [sys.executable, "-m", "claude_fleet_monitor.cli", "install", "--agent", "pi"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )
        if repeated_install.returncode != 0:
            raise RuntimeError("repeated Pi install failed")
        if json.loads((config / "settings.json").read_text()) != installed_settings:
            raise RuntimeError("repeated Pi install was not idempotent")

        observer = FleetObserver(fleet_dir)
        observer.start()
        pi = RpcProcess(
            base_pi_command(pi_command, config, sessions), root, environment
        )
        focus_evidence = None
        initial_session_file = None
        initial_session_id = None
        new_session_id = None
        try:
            state = pi.request("initial-state", {"type": "get_state"})
            initial_session_id = state["data"]["sessionId"]
            initial_session_file = state["data"]["sessionFile"]
            started = observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.session-start"
            )
            if require_tmux:
                focus_evidence = verify_tmux_focus(started, fleet_dir)

            pi.request("tool-turn", {
                "type": "prompt",
                "message": "Read the synthetic fixture file.",
            })
            pi.wait_output(lambda item: item.get("type") == "agent_settled")
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.tool-execution-start"
                and item["tool"] == "read"
            )
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.agent-settled"
                and item["status"] == "idle"
            )

            pi.send({
                "id": "wait",
                "type": "prompt",
                "message": "/fleet-fixture-wait",
            })
            ui_request = pi.wait_output(
                lambda item: item.get("type") == "extension_ui_request"
                and item.get("method") == "input"
            )
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.ui-prompt-start"
                and item["status"] == "waiting"
            )
            pi.send({
                "type": "extension_ui_response",
                "id": ui_request["id"],
                "value": "Synthetic input",
            })
            pi.wait_output(
                lambda item: item.get("type") == "response"
                and item.get("id") == "wait"
            )
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.ui-prompt-end"
                and item["status"] == "idle"
            )

            pi.request("error-turn", {
                "type": "prompt",
                "message": "Trigger the synthetic provider failure.",
            })
            pi.wait_output(lambda item: item.get("type") == "agent_settled")
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.agent-settled"
                and item["status"] == "error"
                and item["detail"] == "turn failed"
            )

            pi.request("new", {"type": "new_session"})
            new_state = pi.request("new-state", {"type": "get_state"})
            new_session_id = new_state["data"]["sessionId"]
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.session-shutdown"
            )
            observer.wait_for(
                lambda item: item["session_id"] == new_session_id
                and item["last_event"] == "pi.session-start"
            )

            pi.request("resume", {
                "type": "switch_session",
                "sessionPath": initial_session_file,
            })
            resumed = pi.request("resumed-state", {"type": "get_state"})
            if resumed["data"]["sessionId"] != initial_session_id:
                raise RuntimeError("Pi did not resume the original session")
            resume_event = observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.session-start"
                and item["sequence"] > started["sequence"]
            )
            before_reload_sequence = resume_event["sequence"]
            pi.request("reload", {
                "type": "prompt",
                "message": "/fleet-fixture-reload",
            })
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.session-start"
                and item["sequence"] > before_reload_sequence
            )

            pi.send({
                "id": "exit",
                "type": "prompt",
                "message": "/fleet-fixture-exit",
            })
            pi.process.wait(timeout=15)
            observer.wait_for(
                lambda item: item["session_id"] == initial_session_id
                and item["last_event"] == "pi.session-shutdown"
            )
        finally:
            pi.close()

        abrupt = RpcProcess(
            [*base_pi_command(pi_command, config, sessions), "--no-session"],
            root,
            environment,
        )
        try:
            abrupt_state = abrupt.request("state", {"type": "get_state"})
            abrupt_id = abrupt_state["data"]["sessionId"]
            abrupt_record = observer.wait_for(
                lambda item: item["session_id"] == abrupt_id
                and item["last_event"] == "pi.session-start"
            )
            abrupt.process.kill()
            abrupt.process.wait(timeout=10)
            from claude_fleet_monitor import discovery

            discovery.FLEET_DIR = fleet_dir
            discovery.read_sessions()
            if any(
                item.get("canonical_id") == abrupt_record["canonical_id"]
                for item in read_current_records(fleet_dir)
            ):
                raise RuntimeError("dead Pi process record survived liveness cleanup")
        finally:
            abrupt.close()
            observer.stop()
            server.shutdown()
            server.server_close()

        pi_version = subprocess.run(
            [pi_command, "--version"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        node_version = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        uninstall = subprocess.run(
            [
                sys.executable, "-m", "claude_fleet_monitor.cli", "uninstall",
                "--agent", "pi", "--keep-data",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=40,
        )
        if uninstall.returncode != 0:
            raise RuntimeError(f"Pi uninstall failed: {uninstall.stdout}{uninstall.stderr}")
        uninstalled_settings = json.loads((config / "settings.json").read_text())
        if uninstalled_settings.get("extensions") != [str(fixture_extension)]:
            raise RuntimeError("Pi uninstall removed an unrelated extension")
        if uninstalled_settings.get("packages"):
            raise RuntimeError("Pi uninstall left its managed package reference")
        if (config / "claude-fleet-monitor.json").exists():
            raise RuntimeError("Pi uninstall left its ownership config")
        event_names = [item["last_event"] for item in observer.events]
        required = {
            "pi.session-start", "pi.before-agent-start",
            "pi.tool-execution-start", "pi.agent-settled",
            "pi.ui-prompt-start", "pi.ui-prompt-end", "pi.session-shutdown",
        }
        if not required.issubset(event_names):
            raise RuntimeError(f"missing lifecycle events: {sorted(required - set(event_names))}")
        if len({item["instance_id"] for item in observer.events if item["pid"] == started["pid"]}) != 1:
            raise RuntimeError("Pi instance identity changed within one process")
        sequences = {}
        for event in observer.events:
            sequences.setdefault(event["canonical_id"], []).append(event["sequence"])
        if any(values != sorted(set(values)) for values in sequences.values()):
            raise RuntimeError("Pi event sequences were not strictly increasing")
        encoded_events = json.dumps(observer.events)
        for private_value in (
            "Synthetic private provider error",
            "Read the synthetic fixture file.",
            "Trigger the synthetic provider failure.",
            "Synthetic validation input",
        ):
            if private_value in encoded_events:
                raise RuntimeError("private Pi content reached Fleet state")
        evidence = {
            "result": "pass",
            "pi_version": pi_version,
            "node_version": node_version,
            "python_version": sys.version.split()[0],
            "provider": "synthetic localhost HTTP fixture",
            "provider_calls": FixtureProvider.calls,
            "initial_session_id": initial_session_id,
            "new_session_id": new_session_id,
            "lifecycle_events": observer.events,
            "tmux_focus": focus_evidence,
            "abrupt_pid_cleanup": True,
            "pi_install_idempotent": True,
            "pi_uninstall_removed_only_owned_package": True,
            "pi_settings_preserved_unrelated_extension": True,
            "stderr": "".join(pi.errors),
        }
        print(json.dumps(evidence, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-tmux",
        action="store_true",
        help="Require and verify exact tmux pane selection",
    )
    args = parser.parse_args()
    validate(args.require_tmux)


if __name__ == "__main__":
    main()
