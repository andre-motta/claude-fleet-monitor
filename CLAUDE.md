# Claude Fleet Monitor

Fleet monitoring for Claude Code sessions. Pure Python, cross-platform.

## Architecture

```
Claude Code sessions --> hook.py --> ~/.claude/fleet/*.json
                                          |
                          +---------------+---------------+
                          |               |               |
                     discovery.py    mcp_server.py     tui.py
                          |                               |
                       focus.py                        curses UI
```

- `hook.py`: Claude Code hook handler. Receives events via stdin JSON, writes session status to fleet dir. Finds parent claude PID by walking process tree.
- `discovery.py`: Shared module. Cross-platform process discovery (`/proc` on Linux, `lsof`/`ps` on macOS, `tasklist` on Windows). Reads/deduplicates/cleans session files. Used by all consumers.
- `mcp_server.py`: FastMCP server exposing `fleet_status`, `fleet_session`, `fleet_focus`, `fleet_sessions_needing_attention`, `fleet_cleanup` tools.
- `tui.py`: Curses-based interactive dashboard. Arrow keys navigate, Enter focuses session.
- `focus.py`: Cross-platform terminal focus. KDE Konsole via qdbus, KWin scripting for window raise, xdotool for X11, osascript for macOS, pywinctl as optional fallback.
- `cli.py`: Entry point for `claude-fleet` command. Handles install/uninstall (patches `~/.claude/settings.json`), delegates to tui/focus/status.

## Key Design Decisions

- No file copying after install. Hooks and MCP point to pip-installed entry points. `pip install --upgrade` updates everything.
- Fleet dir (`~/.claude/fleet/`) is filesystem-based pub/sub. No daemon, no database, no IPC.
- Hook script must be fast (runs on every Claude Code event). Python startup (~17ms) is acceptable.
- Cross-platform: use `sys.platform` checks, never assume `/proc` exists.

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## Session States

- `started`: session just began
- `running`: processing prompt or using tools
- `idle`: finished responding, waiting for next prompt
- `waiting`: blocked on permission request or user input (elicitation)
- `error`: turn failed (API error)
- `ended`: session closed
- `discovered`: found via process scan, no hook data yet

## Style

- Pure Python, no bash/jq dependencies in Python code
- Module-level imports
- No comments unless the "why" is non-obvious
- No em-dashes in text or commits
- Cross-platform by default
