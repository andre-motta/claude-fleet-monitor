# Claude Fleet Monitor

Fleet monitoring for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions. See all your running sessions at a glance, get notified when one needs input, and jump to the right terminal tab instantly.

## Features

- **TUI Dashboard** -- live view of all Claude Code sessions with status, detail, and age
- **Process Discovery** -- finds running sessions via `/proc` even before hooks fire
- **MCP Server** -- any Claude session can query fleet status programmatically
- **Terminal Focus** -- switch to a session's Konsole tab (or raise its window on other terminals) by name or PID
- **Desktop Notifications** -- `notify-send` alerts when a session has been idle for over 2 minutes
- **Hooks Integration** -- Claude Code hooks emit real-time status (running, idle, error) as sessions interact

## Install

```bash
pip install claude-fleet-monitor
claude-fleet install
```

Or install from source:

```bash
git clone https://github.com/andre-motta/claude-fleet-monitor.git
cd claude-fleet-monitor
pip install .
claude-fleet install
```

Restart your Claude Code sessions after installing to activate hooks.

### Dependencies

- `jq` -- JSON processing in hook/monitor scripts
- `python3` >= 3.10
- `uv` -- for running the MCP server

Optional:
- `qdbus` -- Konsole tab switching (KDE)
- `xdotool` -- generic window focus (X11)
- `notify-send` -- desktop notifications

## Usage

### TUI Dashboard

```bash
claude-fleet monitor              # default 2s refresh
claude-fleet monitor --refresh 5  # 5s refresh
```

Or run the script directly:

```bash
~/.claude/bin/fleet-monitor.sh
```

### Focus a Session

```bash
claude-fleet focus autofix         # by repo name
claude-fleet focus 2467709         # by PID
claude-fleet focus proc-2467709    # by session ID
```

On Konsole: switches to the exact tab. On other terminals: raises the window.

### Quick Status (no TUI)

```bash
claude-fleet status
```

### MCP Tools

Any Claude Code session with the fleet MCP server can use these tools:

| Tool | Description |
|------|-------------|
| `fleet_status` | All sessions with summary counts |
| `fleet_session` | Single session detail by ID or prefix |
| `fleet_sessions_needing_attention` | Sessions idle over 2 minutes |
| `fleet_focus` | Focus terminal tab for a session |
| `fleet_cleanup` | Remove stale ended session files |

Just ask Claude: "what sessions are running?" or "focus on the autofix session".

## How It Works

```
Claude Code Session A ──┐
Claude Code Session B ──┤── hooks ──> ~/.claude/fleet/*.json <── MCP server
Claude Code Session C ──┘                                    <── TUI monitor
                                                             <── fleet-focus
```

1. **Hooks** in `~/.claude/settings.json` fire on session events (start, prompt, tool use, stop, end)
2. Each hook writes/updates a JSON status file in `~/.claude/fleet/`
3. **Process discovery** also scans `/proc` for `claude` processes to find sessions that started before hooks were installed
4. The **TUI monitor**, **MCP server**, and **CLI** all read these status files

### Session States

| State | Meaning |
|-------|---------|
| `STARTED` | Session just began |
| `RUNNING` | Processing a prompt or using tools |
| `IDLE` | Finished responding, waiting for input |
| `ERROR` | Turn failed (API error) |
| `ENDED` | Session closed |
| `DISCOVERED` | Found via process scan, no hook data yet |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLEET_DIR` | `~/.claude/fleet` | Directory for session status files |

### Uninstall

```bash
claude-fleet uninstall              # removes everything including data
claude-fleet uninstall --keep-data  # keeps ~/.claude/fleet/
```

## Publishing

This project uses [trusted publishing](https://docs.pypi.org/trusted-publishers/) via GitHub Actions. To release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow builds and publishes to PyPI automatically.

## License

MIT
