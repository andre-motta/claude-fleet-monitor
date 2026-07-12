# Claude Fleet Monitor

[![PyPI version](https://img.shields.io/pypi/v/claude-fleet-monitor)](https://pypi.org/project/claude-fleet-monitor/)
[![Downloads](https://img.shields.io/pypi/dm/claude-fleet-monitor)](https://pypistats.org/packages/claude-fleet-monitor)
[![License](https://img.shields.io/pypi/l/claude-fleet-monitor)](https://github.com/andre-motta/claude-fleet-monitor/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/claude-fleet-monitor)](https://pypi.org/project/claude-fleet-monitor/)

Fleet monitoring for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions. See all your running sessions at a glance, get notified when one needs input, and jump to the right terminal tab instantly.

## Features

- **TUI Dashboard** -- interactive curses UI with arrow key navigation and enter-to-focus
- **Process Discovery** -- finds running sessions cross-platform even before hooks fire
- **MCP Server** -- any Claude session can query fleet status programmatically
- **Terminal Focus** -- switch to a session's tab and raise the window, across 8 supported terminals
- **Desktop Notifications** -- `notify-send` alerts when a session has been idle for over 2 minutes
- **Hooks Integration** -- Claude Code hooks emit real-time status (running, idle, waiting, error) per session
- **Per-Session Terminal Detection** -- each session captures its terminal type at hook time, not at focus time

## Supported Terminals

| Terminal | Tab Switching | Window Raise | Nested Support |
|----------|:---:|:---:|:---:|
| **KDE Konsole** | Yes (qdbus) | Yes (KWin) | -- |
| **tmux** | Yes (tmux CLI) | Via parent terminal | Yes |
| **zellij** | Yes (zellij CLI) | Via parent terminal | Yes |
| **GNOME Terminal** | No | Yes (xdotool) | -- |
| **iTerm2** | Yes (osascript) | Yes (osascript) | -- |
| **macOS Terminal** | Yes (osascript) | Yes (osascript) | -- |
| **Windows Terminal** | No | Yes (pywinctl) | -- |
| **Generic fallback** | No | Best effort | -- |

Nested terminals (e.g. tmux inside Konsole) are handled automatically: the focus command switches the tmux pane, then detects the parent terminal via process tree walking and raises that window too.

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

Restart your Claude Code sessions after the first install to activate hooks.

### Upgrading

```bash
pip install --upgrade claude-fleet-monitor
```

No need to re-run `claude-fleet install` or restart sessions. Hooks and MCP server point to pip-installed entry points, so upgrades take effect immediately.

### Dependencies

- `python3` >= 3.10

Optional (for terminal focus):
- `qdbus` -- Konsole tab switching (KDE)
- `xdotool` -- GNOME Terminal / X11 window focus
- `pywinctl` -- Windows Terminal window focus
- `notify-send` -- desktop notifications (Linux)

## Usage

### TUI Dashboard

```bash
claude-fleet monitor              # default 2s refresh
claude-fleet monitor --refresh 5  # 5s refresh
```

Arrow keys to navigate, Enter to focus a session, `q` to quit.

### Focus a Session

```bash
claude-fleet focus autofix         # by repo name
claude-fleet focus 2467709         # by PID
claude-fleet focus abc123          # by session ID prefix
```

The focus command reads the session's stored terminal type and uses the right API. Works across Konsole, tmux, iTerm2, and others.

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
| `fleet_sessions_needing_attention` | Sessions idle over 2 minutes or waiting for input |
| `fleet_focus` | Focus terminal tab for a session |
| `fleet_cleanup` | Remove stale ended session files |

Just ask Claude: "what sessions are running?" or "focus on the autofix session".

## How It Works

```
                                                              <-- MCP server
Claude Code sessions --\                                      <-- TUI monitor
  (hooks per event)     |-- write --> ~/.claude/fleet/*.json   <-- CLI status
                       /                                      <-- focus command
  (process discovery) -
```

1. **Hooks** fire on Claude Code events (start, prompt, tool use, stop, permission request, end)
2. Each hook captures the session's **terminal type** and **PID**, writes to `~/.claude/fleet/`
3. **Process discovery** scans for `claude` processes cross-platform to find sessions without hooks
4. **Consumers** (TUI, MCP, CLI, focus) read the JSON files
5. **Focus** reads the session's `terminal` field and dispatches to the right terminal API

### Terminal Detection Flow

```
Hook fires inside session
  --> detect terminal via env vars (TMUX, KONSOLE_VERSION, ITERM_SESSION_ID, ...)
  --> capture terminal-specific env (socket paths, DBus service, session IDs)
  --> store in fleet JSON: {"terminal": "tmux", "terminal_env": {"TMUX": "..."}}

Focus command reads session JSON
  --> get_terminal_api("tmux") --> TmuxAPI
  --> find_tab(pid) --> switch_tab() --> raise_window()
  --> for nested terminals: detect parent terminal, chain to parent API
```

### Session States

| State | Meaning |
|-------|---------|
| `STARTED` | Session just began |
| `RUNNING` | Processing a prompt or using tools |
| `IDLE` | Finished responding, waiting for next prompt |
| `WAITING` | Blocked on permission request or user input |
| `ERROR` | Turn failed (API error) |
| `ENDED` | Session closed |
| `DISCOVERED` | Found via process scan, no hook data yet |

## Known Limitations

- **Same-name tabs in different windows (Konsole/KDE):** When multiple sessions share the same repo name and live in different Konsole windows, the focus command will switch to the correct tab but may raise the wrong window. Workaround: keep same-name sessions grouped in the same Konsole window.
- **Wayland window activation:** On Wayland/KDE, window raising uses KWin scripting via DBus. Other Wayland compositors may not support programmatic window activation.
- **GNOME Terminal / Windows Terminal:** No tab switching API available; window raise only.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR process.

## License

MIT
