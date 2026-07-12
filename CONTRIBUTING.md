# Contributing to Claude Fleet Monitor

## Development Setup

```bash
git clone https://github.com/andre-motta/claude-fleet-monitor.git
cd claude-fleet-monitor
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

Tests use `tmp_path` fixtures and mock the filesystem. No running Claude sessions or terminal emulators needed.

## Code Style

- Pure Python. No bash, jq, or shell dependencies in Python code.
- Cross-platform. Use `sys.platform` checks for OS-specific paths (`/proc` on Linux, `lsof`/`ps` on macOS, `tasklist` on Windows).
- Module-level imports unless avoiding circular deps.
- No comments unless the "why" is non-obvious.
- No em-dashes in text.

## Architecture

```
hooks (hook.py)  -->  ~/.claude/fleet/*.json  <--  discovery.py
                                              <--  mcp_server.py
                                              <--  tui.py
                                              <--  focus.py
```

- **hook.py**: Claude Code hook handler, writes session status JSON on each event.
- **discovery.py**: Cross-platform process discovery + session reading/dedup/cleanup. Shared by all consumers.
- **mcp_server.py**: MCP server exposing fleet tools to Claude Code sessions.
- **tui.py**: Curses-based interactive dashboard.
- **focus.py**: Cross-platform terminal window/tab focus (KDE/GNOME/macOS/Windows).
- **cli.py**: Entry point for `claude-fleet` command.

## Pull Requests

1. Fork and create a feature branch.
2. Write tests for new functionality.
3. Run `pytest` and ensure all tests pass.
4. Keep PRs focused. One feature or fix per PR.
5. Describe what changed and why in the PR description.

## Reporting Issues

Use the GitHub issue templates. Include your OS, terminal emulator, Python version, and the output of `claude-fleet status`.
