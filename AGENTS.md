# Agent Contributing Guide

Guidelines for AI agents (Claude Code, Copilot, etc.) contributing to this repository.

## Before You Start

1. Read `CLAUDE.md` for architecture and design decisions.
2. Run `pytest` to confirm the test suite passes before making changes.
3. Check existing issues and PRs to avoid duplicate work.

## Making Changes

- Write tests for new functionality. Tests live in `tests/` and use pytest with `tmp_path` fixtures.
- Keep changes cross-platform. Never assume Linux (`/proc`, `pgrep`). Use `sys.platform` checks and the abstractions in `discovery.py`.
- All process/filesystem interaction goes through `discovery.py`. Don't duplicate platform-specific logic in other modules.
- The hook (`hook.py`) must stay fast. No heavy imports at module level, no network calls.

### Terminal APIs

- Focus logic goes through `focus.py`, which delegates to terminal APIs in `terminal_apis/`.
- Each terminal emulator has its own module implementing `TerminalAPI` (see `terminal_apis/base.py`).
- To add a new terminal: create `terminal_apis/newterminal.py`, implement the ABC, add to `TERMINALS` list in `terminal_apis/__init__.py`, add detection env var to `TERMINAL_PROCESS_NAMES` in `tmux.py` for nested terminal support.
- Terminal detection happens at hook time via env vars, not at focus time. Each session stores its `terminal` and `terminal_env` in the fleet JSON.
- For multiplexers (tmux, zellij) that run inside other terminals, `raise_window()` must detect the parent terminal via process tree walking and chain to its API.

## Code Conventions

- Pure Python. No shell subprocess calls for things Python can do natively (JSON parsing, file I/O, string manipulation).
- `subprocess` is acceptable only for platform integration (qdbus, xdotool, osascript, pgrep, lsof, tmux, zellij).
- Module-level imports. Function-level imports only to avoid circular deps or for optional deps (`pywinctl`).
- No comments unless the "why" would surprise a reader.
- No em-dashes in text or commit messages.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

- Mock the filesystem, not the functions. Use `tmp_path` and `monkeypatch` to set `FLEET_DIR`.
- Don't require running Claude sessions, terminal emulators, or display servers.
- Test cross-platform logic by mocking `sys.platform` and platform-specific calls.
- Terminal detection tests: mock env vars, verify right terminal detected (see `tests/test_terminal_apis.py`).

## Commit Messages

- Imperative mood, under 50 chars for subject
- Body explains "why", not "what"
- Sign off with `-s` flag

## What Not to Do

- Don't add bash scripts. We removed them for a reason.
- Don't add runtime dependencies without discussion. The core should stay lightweight.
- Don't modify `settings.json` format without updating `cli.py` install/uninstall.
- Don't write to any directory outside `FLEET_DIR` from hook or discovery code.
- Don't put terminal-specific logic in `focus.py`. It belongs in `terminal_apis/`.
