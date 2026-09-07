# Pi lifecycle integration

Pi support is optional. Install it after installing both Pi and Claude Fleet
Monitor:

```bash
claude-fleet install --agent pi
```

The installer requires Pi 0.84.4 or newer. It checks the version with a temporary
offline Pi configuration, then asks Pi to install the JavaScript extension that
is packaged with Claude Fleet Monitor. The extension has no npm dependencies.
It does not add an MCP server to Pi.

The default `claude-fleet install` command continues to configure Claude Code
and Codex only. Use `--agent all` to configure all three agents, or select one of
`claude`, `codex` and `pi`.

## Data and privacy

The extension reports lifecycle state through the installed
`claude-fleet-hook` executable. It sends the Pi process ID, native session ID,
working directory, a random extension-runtime instance ID, a monotonic sequence
and minimal status metadata. Tool events include the tool name only.

The extension never sends prompts, assistant messages, tool arguments, tool
results, UI prompt titles, provider responses or raw error messages. Provider
failures are reported as `turn failed`, and aborted turns as `turn aborted`.

Events are serialized through a queue limited to 128 waiting entries. An event
send is stopped after 1.5 seconds. Missing or failing Fleet hooks do not stop Pi.
On shutdown, the bridge spends at most 1.5 seconds draining intermediate events,
drops any remaining intermediate queue, and reserves up to 1.5 seconds for the
final ended event. An abruptly killed Pi process is removed by Fleet's PID and
process-start validation on the next read.

## Lifecycle behavior

| Pi event | Fleet state |
|----------|-------------|
| `session_start` | `started` |
| `before_agent_start` | `running` |
| `tool_execution_start` | `running`, with tool name |
| `agent_settled` | `idle`, `error`, or aborted `idle` |
| `ui_prompt_start` | `waiting` |
| `ui_prompt_end` | Restores the prior state |
| `session_shutdown` | `ended` |

Pi can emit duplicate `session_start` events for one newly created session. The
extension ignores repeated starts while that session is active. New, resumed
and reloaded sessions retain one random instance ID for the Pi process, while
each native session has its own increasing event sequence. Events capture their
session identity before entering the queue, so delayed events cannot be applied
to a later session.

Fleet records the terminal environment inherited by Pi. For example, a Pi
process inside tmux can be associated with its exact pane. Desktop window
activation still depends on the captured parent terminal and available display
integration.

## Upgrade and removal

Run the Pi install command again after moving or recreating the Python virtual
environment that contains Claude Fleet Monitor:

```bash
claude-fleet install --agent pi
```

Fleet stores its exact hook and extension paths in
`$PI_CODING_AGENT_DIR/claude-fleet-monitor.json`, or
`~/.pi/agent/claude-fleet-monitor.json` by default. The file is marked as owned
by Claude Fleet Monitor. A repeated install updates those paths, installs the
new package path first, and removes old owned references. A failed old-reference
removal remains recorded so a later install or uninstall can retry it.

If that config file exists without Fleet's ownership marker, installation and
removal stop without replacing it. Uninstall passes only paths recorded in the
owned file to Pi, preserving every unrelated package and extension:

```bash
claude-fleet uninstall --agent pi
```

Removing only Pi does not delete the shared Fleet status directory. The default
uninstall remains the Claude Code and Codex uninstall. Use `--agent all` to
remove all three integrations and shared status data, or add `--keep-data` to
retain the data.

## Validation

The reproducible validation under `validation/pi/` uses a temporary home, Pi
configuration and Fleet directory. It runs a local synthetic provider and does
not send traffic to an external model provider. See
[`validation/pi/README.md`](../validation/pi/README.md) for the exact command and
coverage.
