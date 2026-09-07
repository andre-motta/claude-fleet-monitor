import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")


def extension_path():
    from claude_fleet_monitor.pi_install import pi_extension_path

    return pi_extension_path() / "extensions" / "fleet-monitor.js"


def run_bridge(
    tmp_path, script, *, configured=True, hook_body=None, hook_exists=True,
    timeout=15,
):
    config_dir = tmp_path / "Pi config Ω"
    config_dir.mkdir()
    events = tmp_path / "events.jsonl"
    hook_dir = tmp_path / "hook path with spaces"
    hook_dir.mkdir()
    hook = hook_dir / "claude-fleet-hook"
    if hook_exists:
        hook.write_text(hook_body or (
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "with open(os.environ['FLEET_TEST_EVENTS'], 'a', encoding='utf-8') as stream:\n"
            "    stream.write(sys.stdin.read() + '\\n')\n"
        ))
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    if configured:
        (config_dir / "claude-fleet-monitor.json").write_text(json.dumps({
            "schema_version": 1,
            "owner": "claude-fleet-monitor",
            "hook_path": str(hook),
            "extension_path": str(extension_path().parent.parent),
            "managed_paths": [str(extension_path().parent.parent)],
        }))
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        f"import fleetMonitor from {json.dumps(extension_path().as_uri())};\n"
        "const handlers = new Map();\n"
        "fleetMonitor({ on: (name, handler) => handlers.set(name, handler) });\n"
        "let nativeId = 'native-old';\n"
        "const ctx = { cwd: process.cwd(), sessionManager: { getSessionId: () => nativeId } };\n"
        "const fire = (name, event = {}) => handlers.get(name)?.({ type: name, ...event }, ctx);\n"
        + script
    )
    environment = os.environ.copy()
    environment.update({
        "PI_CODING_AGENT_DIR": str(config_dir),
        "FLEET_TEST_EVENTS": str(events),
    })
    result = subprocess.run(
        [NODE, str(runner)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    records = []
    if events.exists():
        records = [json.loads(line) for line in events.read_text().splitlines()]
    output = json.loads(result.stdout) if result.stdout.strip() else None
    return records, output


def test_bridge_lifecycle_is_ordered_private_and_idempotent(tmp_path):
    records, returns = run_bridge(tmp_path, """
const returns = [];
returns.push(fire('session_start', { reason: 'startup' }));
returns.push(fire('session_start', { reason: 'startup' }));
returns.push(fire('before_agent_start', { prompt: 'PRIVATE PROMPT' }));
returns.push(fire('tool_execution_start', {
  toolName: 'Read', args: { path: 'PRIVATE ARGUMENT' }, toolCallId: 'secret-call-id'
}));
fire('agent_end', { messages: [{
  role: 'assistant', stopReason: 'stop', content: 'PRIVATE MESSAGE'
}] });
returns.push(fire('agent_settled'));
returns.push(fire('ui_prompt_start', { title: 'PRIVATE TITLE', kind: 'input' }));
returns.push(fire('ui_prompt_start', { title: 'NESTED PRIVATE TITLE', kind: 'input' }));
returns.push(fire('ui_prompt_end', { title: 'NESTED PRIVATE TITLE', kind: 'input' }));
returns.push(fire('ui_prompt_end', { title: 'PRIVATE TITLE', kind: 'input' }));
await fire('session_shutdown', { reason: 'quit' });
console.log(JSON.stringify(returns.map((value) => value === undefined)));
""")
    assert returns == [True] * 9
    assert [item["event_id"] for item in records] == [
        "pi.session-start",
        "pi.before-agent-start",
        "pi.tool-execution-start",
        "pi.agent-settled",
        "pi.ui-prompt-start",
        "pi.ui-prompt-end",
        "pi.session-shutdown",
    ]
    assert [item["sequence"] for item in records] == list(range(1, 8))
    assert len({item["instance_id"] for item in records}) == 1
    assert all(item["session_id"] == "native-old" for item in records)
    assert records[2]["tool"] == "Read"
    assert records[4]["status"] == "waiting"
    assert records[5]["status"] == "idle"
    encoded = json.dumps(records)
    for secret in (
        "PRIVATE PROMPT", "PRIVATE ARGUMENT", "secret-call-id",
        "PRIVATE MESSAGE", "PRIVATE TITLE",
    ):
        assert secret not in encoded


def test_bridge_retries_error_and_abort_settle_truthfully(tmp_path):
    records, _ = run_bridge(tmp_path, """
fire('session_start', { reason: 'startup' });
fire('before_agent_start', { prompt: 'first' });
fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'error', errorMessage: 'RAW ERROR' }] });
fire('before_agent_start', { prompt: 'retry' });
fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'stop', content: 'secret' }] });
fire('agent_settled');
fire('before_agent_start', { prompt: 'error' });
fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'error', errorMessage: 'PROVIDER SECRET' }] });
fire('agent_settled');
fire('before_agent_start', { prompt: 'abort' });
fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'aborted', content: 'PRIVATE' }] });
fire('agent_settled');
await fire('session_shutdown', { reason: 'quit' });
""")
    settled = [item for item in records if item["event_id"] == "pi.agent-settled"]
    assert [(item["status"], item["detail"]) for item in settled] == [
        ("idle", "finished"),
        ("error", "turn failed"),
        ("idle", "turn aborted"),
    ]
    encoded = json.dumps(records)
    assert "RAW ERROR" not in encoded
    assert "PROVIDER SECRET" not in encoded
    assert "PRIVATE" not in encoded


def test_bridge_session_switch_and_reload_keep_identity_and_order(tmp_path):
    records, _ = run_bridge(tmp_path, """
fire('session_start', { reason: 'startup' });
fire('before_agent_start', { prompt: 'old' });
await fire('session_shutdown', { reason: 'new' });
nativeId = 'native-new';
fire('session_start', { reason: 'new' });
fire('session_start', { reason: 'new' });
fire('before_agent_start', { prompt: 'new' });
await fire('session_shutdown', { reason: 'reload' });
fire('session_start', { reason: 'reload' });
fire('session_start', { reason: 'reload' });
await fire('session_shutdown', { reason: 'quit' });
""")
    assert [item["session_id"] for item in records] == [
        "native-old", "native-old", "native-old",
        "native-new", "native-new", "native-new", "native-new", "native-new",
    ]
    old = [item for item in records if item["session_id"] == "native-old"]
    new = [item for item in records if item["session_id"] == "native-new"]
    assert [item["sequence"] for item in old] == [1, 2, 3]
    assert [item["sequence"] for item in new] == [1, 2, 3, 4, 5]
    assert [item["event_id"] for item in new] == [
        "pi.session-start", "pi.before-agent-start", "pi.session-shutdown",
        "pi.session-start", "pi.session-shutdown",
    ]
    assert len({item["instance_id"] for item in records}) == 1


def test_bridge_captures_session_before_queued_send(tmp_path):
    records, _ = run_bridge(tmp_path, """
fire('session_start', { reason: 'startup' });
fire('before_agent_start', { prompt: 'old' });
nativeId = 'native-new';
fire('session_start', { reason: 'new' });
await fire('session_shutdown', { reason: 'quit' });
""")
    assert [item["session_id"] for item in records] == [
        "native-old", "native-old", "native-new", "native-new",
    ]


def test_bridge_fails_open_without_managed_config(tmp_path):
    records, output = run_bridge(tmp_path, """
let threw = false;
try {
  fire('session_start', { reason: 'startup' });
  fire('before_agent_start', { prompt: 'private' });
  await fire('session_shutdown', { reason: 'quit' });
} catch {
  threw = true;
}
console.log(JSON.stringify({ threw }));
""", configured=False)
    assert records == []
    assert output == {"threw": False}


def test_bridge_fails_open_when_hook_exits_before_reading(tmp_path):
    records, output = run_bridge(
        tmp_path,
        """
let threw = false;
try {
  fire('session_start', { reason: 'startup' });
  for (let index = 0; index < 20; index += 1) {
    fire('tool_execution_start', { toolName: 'Read', args: { secret: 'private' } });
  }
  await fire('session_shutdown', { reason: 'quit' });
} catch {
  threw = true;
}
console.log(JSON.stringify({ threw }));
""",
        hook_body="#!/usr/bin/env python3\nraise SystemExit(0)\n",
    )
    assert records == []
    assert output == {"threw": False}


def test_bridge_fails_open_when_hook_executable_is_missing(tmp_path):
    records, output = run_bridge(
        tmp_path,
        """
let threw = false;
try {
  fire('session_start', { reason: 'startup' });
  await fire('session_shutdown', { reason: 'quit' });
} catch {
  threw = true;
}
console.log(JSON.stringify({ threw }));
""",
        hook_exists=False,
    )
    assert records == []
    assert output == {"threw": False}


def test_bridge_kills_hook_that_closes_stdin_but_stays_alive(tmp_path):
    records, output = run_bridge(
        tmp_path,
        """
ctx.cwd = 'x'.repeat(2 * 1024 * 1024);
const started = Date.now();
fire('session_start', { reason: 'startup' });
await new Promise((resolve) => setTimeout(resolve, 500));
console.log(JSON.stringify({ elapsed: Date.now() - started }));
""",
        hook_body=(
            "#!/usr/bin/env python3\n"
            "import os, time\n"
            "os.close(0)\n"
            "time.sleep(10)\n"
        ),
        timeout=4,
    )
    assert records == []
    assert output["elapsed"] < 2000


def test_bridge_shutdown_discards_saturated_queue_and_sends_end(tmp_path):
    records, output = run_bridge(
        tmp_path,
        """
const started = Date.now();
fire('session_start', { reason: 'startup' });
for (let index = 0; index < 200; index += 1) {
  fire('tool_execution_start', { toolName: 'Read' });
}
await fire('session_shutdown', { reason: 'quit' });
console.log(JSON.stringify({ elapsed: Date.now() - started }));
""",
        hook_body=(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, sys, time\n"
            "marker = pathlib.Path(os.environ['FLEET_TEST_EVENTS'] + '.first')\n"
            "if not marker.exists():\n"
            "    marker.write_text('1')\n"
            "    time.sleep(5)\n"
            "with open(os.environ['FLEET_TEST_EVENTS'], 'a', encoding='utf-8') as stream:\n"
            "    stream.write(sys.stdin.read() + '\\n')\n"
        ),
        timeout=8,
    )
    assert output["elapsed"] < 4000
    assert records[-1]["event_id"] == "pi.session-shutdown"
    assert records[-1]["sequence"] == 202


def test_bridge_queue_keeps_only_128_waiting_events(tmp_path):
    records, _ = run_bridge(
        tmp_path,
        """
fire('session_start', { reason: 'startup' });
for (let index = 0; index < 200; index += 1) {
  fire('tool_execution_start', { toolName: 'Read' });
}
await new Promise((resolve) => setTimeout(resolve, 5000));
await fire('session_shutdown', { reason: 'quit' });
""",
        timeout=12,
    )
    assert len(records) == 130
    assert [item["sequence"] for item in records] == [
        1, *range(74, 203),
    ]


def test_bridge_rejects_oversized_config_without_blocking_pi(tmp_path):
    config_dir = tmp_path / "Pi config Ω"
    config_dir.mkdir()
    (config_dir / "claude-fleet-monitor.json").write_text(" " * (16 * 1024 + 1))
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        f"import fleetMonitor from {json.dumps(extension_path().as_uri())};\n"
        "const handlers = new Map();\n"
        "fleetMonitor({ on: (name, handler) => handlers.set(name, handler) });\n"
        "const ctx = { cwd: process.cwd(), sessionManager: { getSessionId: () => 'native' } };\n"
        "handlers.get('session_start')?.({ type: 'session_start', reason: 'startup' }, ctx);\n"
        "await handlers.get('session_shutdown')?.({ type: 'session_shutdown', reason: 'quit' }, ctx);\n"
        "console.log(JSON.stringify({ survived: true }));\n"
    )
    result = subprocess.run(
        [NODE, str(runner)],
        cwd=tmp_path,
        env={**os.environ, "PI_CODING_AGENT_DIR": str(config_dir)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"survived": True}


@pytest.mark.parametrize("current_first", [False, True])
def test_only_current_extension_copy_registers_during_migration(
    tmp_path, current_first
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    old = tmp_path / "old"
    current = tmp_path / "current"
    for package in (old, current):
        extensions = package / "extensions"
        extensions.mkdir(parents=True)
        shutil.copy2(extension_path(), extensions / "fleet-monitor.js")
        (package / "package.json").write_text('{"type":"module"}')
    events = tmp_path / "events.jsonl"
    hook = tmp_path / "hook"
    hook.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "with open(os.environ['FLEET_TEST_EVENTS'], 'a') as stream:\n"
        "    stream.write(sys.stdin.read() + '\\n')\n"
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    (config_dir / "claude-fleet-monitor.json").write_text(json.dumps({
        "schema_version": 1,
        "owner": "claude-fleet-monitor",
        "hook_path": str(hook),
        "extension_path": str(current),
        "managed_paths": [str(current), str(old)],
    }))
    ordered = [current, old] if current_first else [old, current]
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        "\n".join(
            f"import extension{index} from "
            f"{json.dumps((package / 'extensions' / 'fleet-monitor.js').as_uri())};"
            for index, package in enumerate(ordered)
        )
        + """
const handlers = new Map();
const pi = { on: (name, handler) => {
  const values = handlers.get(name) ?? [];
  values.push(handler);
  handlers.set(name, values);
} };
extension0(pi);
extension1(pi);
const ctx = {
  cwd: process.cwd(),
  sessionManager: { getSessionId: () => 'native-session' },
};
const fire = (name, event = {}) => Promise.all(
  (handlers.get(name) ?? []).map((handler) => handler({ type: name, ...event }, ctx)),
);
await fire('session_start', { reason: 'startup' });
await fire('before_agent_start', { prompt: 'private' });
await fire('tool_execution_start', { toolName: 'Read', args: { private: true } });
await fire('agent_end', { messages: [{ role: 'assistant', stopReason: 'stop' }] });
await fire('agent_settled');
await fire('session_shutdown', { reason: 'quit' });
console.log(JSON.stringify(Object.fromEntries(
  [...handlers].map(([name, values]) => [name, values.length]),
)));
"""
    )
    result = subprocess.run(
        [NODE, str(runner)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PI_CODING_AGENT_DIR": str(config_dir),
            "FLEET_TEST_EVENTS": str(events),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout).values()) == {1}
    records = [json.loads(line) for line in events.read_text().splitlines()]
    assert [record["event_id"] for record in records] == [
        "pi.session-start",
        "pi.before-agent-start",
        "pi.tool-execution-start",
        "pi.agent-settled",
        "pi.session-shutdown",
    ]
    assert [record["sequence"] for record in records] == [1, 2, 3, 4, 5]
