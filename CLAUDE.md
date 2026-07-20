# Claude Fleet Monitor

Fleet monitoring for Claude Code sessions. Pure Python, cross-platform.

## Architecture

```
Claude Code sessions --> hook.py --> ~/.claude/fleet/*.json
                            |                 |
                    captures terminal    +-----+-----+------+------+
                    type + env vars      |     |     |      |      |
                                    discovery mcp   tui   focus  tongs
                                      .py   _server .py    .py  _plugin
                                             .py     |           .py
                                                  widgets/   views/
                                               session_table fleet_screen
                                                  .py         .py
                                                          |
                                                   terminal_apis/
                                                     konsole.py
                                                     tmux.py
                                                     gnome.py
                                                     iterm2.py
                                                     ...
```

### Modules

- `hook.py`: Claude Code hook handler. Receives events via stdin JSON, writes session status to fleet dir. Captures terminal type and PID per session.
- `discovery.py`: Shared module. Cross-platform process discovery (`/proc` on Linux, `lsof`/`ps` on macOS, `tasklist` on Windows). Reads/deduplicates/cleans session files. Used by all consumers.
- `models.py`: Typed data models. `SessionStatus` enum, `FleetSession` frozen dataclass, `parse_session()` converter, `format_age()` utility.
- `mcp_server.py`: FastMCP server exposing fleet tools to Claude Code sessions.
- `tui.py`: Textual-based interactive dashboard (`FleetMonitorApp`). Polling, search/filter, desktop notifications, session focus.
- `widgets/session_table.py`: `SessionTable(DataTable)` widget with status-colored rows. Shared between standalone TUI and tongs screen.
- `views/fleet_screen.py`: `FleetScreen(Screen)` for embedding in tongs. Same features as standalone but escape pops back.
- `tongs_plugin.py`: `FleetMonitorPlugin(TongsPlugin)` ABC implementation. Optional tongs dependency. Registers command palette entry and screen.
- `focus.py`: Session lookup and PID resolution. Delegates to terminal APIs for actual focus.
- `cli.py`: Entry point for `claude-fleet` command. Handles install/uninstall, delegates to tui/focus/status.

### Terminal APIs (`terminal_apis/`)

Pluggable terminal abstraction. Each terminal has a class implementing `TerminalAPI`:

- `base.py`: ABC defining `detect()`, `capture_env()`, `find_tab()`, `switch_tab()`, `raise_window()`, `focus()`
- `konsole.py`: KDE Konsole via qdbus + KWin scripting
- `tmux.py`: tmux via CLI. Detects parent terminal for window raising.
- `zellij.py`: zellij via CLI. Detects parent terminal for window raising.
- `gnome.py`: GNOME Terminal via xdotool (no tab switching API)
- `iterm2.py`: iTerm2 via osascript
- `macos_terminal.py`: macOS Terminal.app via osascript
- `windows_terminal.py`: Windows Terminal via pywinctl (window raise only)
- `generic.py`: Fallback using pywinctl/xdotool/osascript
- `__init__.py`: `detect_terminal()`, `capture_terminal_info()`, `get_terminal_api()`

Detection order: tmux > zellij > konsole > iterm2 > macos_terminal > gnome > windows_terminal > generic. tmux/zellij first because they run inside other terminals.

Terminal info is captured per-session in the hook (not guessed at focus time). Each session's fleet JSON stores `terminal` and `terminal_env` fields.

For nested terminals (tmux inside Konsole), `raise_window()` walks the process tree from the tmux client PID to detect the parent terminal and chains to its API.

## Key Design Decisions

- No file copying after install. Hooks and MCP point to pip-installed entry points.
- Fleet dir (`~/.claude/fleet/`) is filesystem-based pub/sub. No daemon, no database, no IPC.
- Hook must be fast (runs on every Claude Code event). Python startup (~17ms) is acceptable.
- Cross-platform: use `sys.platform` checks, never assume `/proc` exists.
- Terminal detection at hook time, not focus time. Handles mixed terminal setups.

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## Session States

- `started`: session just began
- `running`: processing prompt or using tools
- `idle`: finished responding, waiting for next prompt
- `waiting`: blocked on permission request or user input
- `error`: turn failed (API error)
- `ended`: session closed
- `discovered`: found via process scan, no hook data yet

## Style

- Pure Python, no bash/jq dependencies in Python code
- Module-level imports (function-level only for circular deps or optional deps)
- No comments unless the "why" is non-obvious
- No em-dashes in text or commits
- Cross-platform by default
