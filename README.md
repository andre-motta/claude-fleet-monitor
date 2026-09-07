# Claude Fleet Monitor

[![PyPI version](https://img.shields.io/pypi/v/claude-fleet-monitor)](https://pypi.org/project/claude-fleet-monitor/)
[![Downloads](https://img.shields.io/pypi/dm/claude-fleet-monitor)](https://pypistats.org/packages/claude-fleet-monitor)
[![License](https://img.shields.io/pypi/l/claude-fleet-monitor)](https://github.com/andre-motta/claude-fleet-monitor/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/claude-fleet-monitor)](https://pypi.org/project/claude-fleet-monitor/)

Fleet monitoring for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [Codex](https://learn.chatgpt.com/codex) sessions, with optional [Pi](https://github.com/earendil-works/pi) lifecycle integration. See all your running agent sessions at a glance, get notified when one needs input, and jump to the right terminal tab instantly.

## Features

- **TUI Dashboard** -- Textual-based interactive UI with search/filter, status-colored rows, and click-to-focus
- **tongs Plugin** -- embeds as a screen in [tongs](https://github.com/andre-motta/tongs) via the TongsPlugin ABC
- **Process Discovery** -- finds running Claude Code and Codex sessions cross-platform even before hooks fire
- **MCP Server** -- Claude Code and Codex sessions can query fleet status programmatically
- **Terminal Focus** -- switch to a session's tab and raise the window, across supported terminal backends
- **Desktop Notifications** -- `notify-send` alerts when a session has been idle for over 2 minutes
- **Hooks Integration** -- Claude Code and Codex hooks emit real-time status (running, idle, waiting, error) per session
- **Per-Session Terminal Detection** -- each session captures its terminal type at hook time, not at focus time

## Harness support

The support matrix separates lifecycle ingestion from process identity and
focus. A lifecycle event does not by itself prove that a process is
discoverable, that a terminal target can be selected, or that a desktop window
can be activated. See the [adapter author guide](docs/harness-adapters.md) and
the implemented [event, identity and focus contract](docs/work/harness-contract.md)
before adding another harness.

| Harness | Lifecycle ingestion | Process identity | Terminal selection | GUI window activation | MCP consumer access | Native harness MCP registration |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Code | Installed native hooks for start, prompt, tool, permission, stop, failure, elicitation and end | Discoverable by registered exact process names and ancestry; unresolved records are explicit when process evidence is unavailable | Captured terminal metadata is dispatched to the matching backend; result is complete, partial, unavailable or failed according to observed operations | Desktop conversation targets have no accepted backend; parent-terminal activation is backend-specific | Fleet MCP is available to configured Claude Code sessions | Fleet MCP is registered in Claude Code settings by the default installer |
| Codex | Installed native hooks for start, prompt, tool, permission, stop and end | Discoverable by registered exact process names and ancestry; unresolved records are explicit when process evidence is unavailable | Captured terminal metadata is dispatched to the matching backend; result is complete, partial, unavailable or failed according to observed operations | Desktop conversation targets have no accepted backend; parent-terminal activation is backend-specific | Fleet MCP is available to configured Codex sessions | Fleet MCP is registered through the Codex MCP configuration by the default installer |
| Pi | Optional dependency-free extension emits normalized `fleet-event` records | Emitter supplies the exact Pi PID, native session ID, extension instance and sequence; Pi is not process-name discovered | Accepted live validation selected the exact tmux pane for a real Pi process; other terminal backends require their own evidence | No live desktop GUI result is claimed; detached tmux has no GUI parent and reports activation separately | Fleet consumers can read Pi records, but Pi itself has no Fleet MCP client | None; Pi installation adds the lifecycle extension only |

The evidence behind this table has defined limits:

- The strict [shell validation](validation/shells/README.md) runs the existing
  hook through nine real shells in rootless Podman. Its 18 lifecycle cases,
  nine manual quoted-path controls and 108 generated-command checks use
  synthetic payloads. They do not prove live Claude or Codex processes, TTY
  discovery, terminal focus or GUI activation.
- The [Pi validation](validation/pi/README.md) runs a real Pi 0.85.0 process
  with Node.js 22.23.1 and Python 3.12.14 against a synthetic localhost
  provider. It validates lifecycle behavior and exact tmux pane selection in an
  isolated server. It does not claim a desktop window result.
- Platform-specific process and terminal behavior in the regular test suite is
  mocked. No live Claude or Codex runtime or desktop GUI acceptance is included
  in this matrix.

## Supported Terminals

| Terminal | Tab Switching | Window Raise | Nested Support |
|----------|:---:|:---:|:---:|
| **KDE Konsole** | Yes (qdbus) | Yes (KWin) | -- |
| **tmux** | Yes (tmux CLI) | Via parent terminal | Yes |
| **zellij** | Yes (zellij CLI) | Via parent terminal | Yes |
| **Ghostty (Linux)** | Best effort (ydotool/xdotool) | GTK DBus / KWin | -- |
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

The installer updates Claude Code's `~/.claude/settings.json`, writes Codex
hooks to `~/.codex/hooks.json`, and registers the Fleet MCP server for Claude
Code and, when the Codex CLI is available, Codex. Restart your sessions after
the first install. Codex requires you to review and trust the installed hooks
through `/hooks` before they run.

Pi support is optional and requires Pi 0.84.4 or newer:

```bash
claude-fleet install --agent pi
```

This installs the dependency-free Pi lifecycle extension packaged with Fleet.
It preserves other Pi extensions and does not register an MCP server. See the
[Pi integration guide](docs/pi.md) for lifecycle, privacy, upgrade and removal
behavior. `--agent all` installs Claude Code, Codex and Pi together.

### tongs Integration

To use the fleet monitor as a plugin inside [tongs](https://github.com/andre-motta/tongs):

```bash
pip install claude-fleet-monitor[tongs]
```

Then launch tongs and open the command palette (Ctrl+P) to find "Fleet Monitor".

### Upgrading

```bash
pip install --upgrade claude-fleet-monitor
```

Claude Code and Codex hooks point to pip-installed entry points, so their
upgrades take effect immediately. If Fleet moves to another virtual environment,
run `claude-fleet install --agent pi` again to update Pi's exact extension and
hook paths.

### Dependencies

- `python3` >= 3.10
- `textual` >= 1.0

Optional (for terminal focus):
- `qdbus` -- Konsole tab switching (KDE)
- `xdotool` -- GNOME Terminal / X11 window focus
- `pywinctl` -- Windows Terminal window focus
- `notify-send` -- desktop notifications (Linux)

Optional agent integration:
- Pi >= 0.84.4 and Node.js, installed separately

## Usage

### TUI Dashboard

```bash
claude-fleet monitor              # default 2s refresh
claude-fleet monitor --refresh 5  # 5s refresh
```

Navigate with arrow keys or mouse. Press Enter or click a row to focus that session's terminal. Press `/` to search/filter by repo name, detail, or status. Press `q` to quit.

### Focus a Session

```bash
claude-fleet focus autofix         # by repo name
claude-fleet focus 2467709         # by PID
claude-fleet focus abc123          # by session ID prefix
```

The focus command reads the session's stored terminal type and uses the right
API. It reports complete, partial or unavailable outcomes, with capability and
evidence varying by terminal backend.

### Quick Status (no TUI)

```bash
claude-fleet status
```

### MCP Tools

Any Claude Code or Codex session with the fleet MCP server can use these tools:

| Tool | Description |
|------|-------------|
| `fleet_status` | All sessions with summary counts |
| `fleet_session` | Single session detail by ID or prefix |
| `fleet_sessions_needing_attention` | Sessions idle over 2 minutes or waiting for input |
| `fleet_focus` | Focus terminal tab for a session |
| `fleet_cleanup` | Remove stale ended session files |

Ask your agent: "what sessions are running?" or "focus on the autofix session".

## How It Works

```
                                                              <-- MCP server
Claude Code sessions --\                                      <-- TUI monitor
  (hooks per event)     |                                      <-- tongs plugin
                       |-- write --> ~/.claude/fleet/*.json    <-- CLI status
Codex sessions --------|                                      <-- focus command
  (hooks per event)     |
Pi sessions ------------|
  (optional extension)  |
                       /
  (process discovery) -
```

1. **Hooks** fire on Claude Code and Codex events; the optional Pi extension translates Pi lifecycle events
2. Each hook captures the session's **terminal type** and **PID**, writes to `~/.claude/fleet/`
3. **Process discovery** scans for `claude` and `codex` processes cross-platform to find sessions without hooks
4. **Consumers** (TUI, MCP, tongs plugin, CLI, focus) read the JSON files
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

## Architecture

```
src/claude_fleet_monitor/
    models.py           # SessionStatus enum, FleetSession dataclass
    hook.py             # Claude Code and Codex hook handler
    discovery.py        # Process discovery, session file I/O
    tui.py              # Textual standalone app (FleetMonitorApp)
    cli.py              # claude-fleet CLI entry point
    pi_install.py       # Optional Pi package lifecycle
    pi_extension/       # Dependency-free packaged Pi bridge
    focus.py            # Session lookup + terminal focus dispatch
    mcp_server.py       # FastMCP server
    tongs_plugin.py     # TongsPlugin ABC implementation
    widgets/
        session_table.py  # SessionTable(DataTable) widget
    views/
        fleet_screen.py   # FleetScreen(Screen) for tongs
    terminal_apis/
        base.py           # TerminalAPI ABC
        konsole.py        # KDE Konsole
        tmux.py           # tmux
        zellij.py         # zellij
        ghostty.py        # Ghostty (Linux GTK DBus)
        gnome.py          # GNOME Terminal
        iterm2.py         # iTerm2
        macos_terminal.py # macOS Terminal.app
        windows_terminal.py # Windows Terminal
        generic.py        # Fallback
```

## Known Limitations

- **Same-name tabs in different windows (Konsole/KDE):** When multiple sessions share the same repo name and live in different Konsole windows, the focus command will switch to the correct tab but may raise the wrong window. Workaround: keep same-name sessions grouped in the same Konsole window.
- **Wayland window activation:** On Wayland/KDE, window raising uses KWin scripting via DBus. Other Wayland compositors may not support programmatic window activation.
- **GNOME Terminal / Windows Terminal:** No tab switching API available; window raise only.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FLEET_DIR` | `~/.claude/fleet` | Shared directory for Claude Code and Codex session status files |

### Uninstall

```bash
claude-fleet uninstall              # removes hooks, MCP config, and data
claude-fleet uninstall --keep-data  # keeps ~/.claude/fleet/
claude-fleet uninstall --agent pi   # removes only Fleet's owned Pi extension
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR process.
Harness contributors should follow the [adapter author guide](docs/harness-adapters.md)
and the [implemented harness contract](docs/work/harness-contract.md).
Agent-led initiatives follow [the SDLC profile](docs/SDLC.md).
Future desktop UI and ChatGPT focus work is tracked in
[harnesses and desktop](docs/work/harnesses-desktop.md).

## License

MIT
