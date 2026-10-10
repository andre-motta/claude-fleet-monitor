# Claude Fleet Monitor

Fleet monitoring for Claude Code and Codex sessions. The core is pure Python and cross-platform.
The approved Pi integration may package an optional dependency-free JavaScript extension.

See [docs/SDLC.md](docs/SDLC.md) for the adopted agent workflow, approval gates
and [active planning](docs/work/terminal-focus.md).

## Architecture

```
Claude Code sessions --\
                       +--> hook.py --> ~/.claude/fleet/*.json
Codex sessions --------/
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

- `hook.py`: Claude Code and Codex hook handler. Receives events via stdin JSON, writes session status to the fleet directory, and tags the source agent. Captures terminal type and PID per session.
- `discovery.py`: Shared module. Cross-platform process discovery (`/proc` on Linux, `lsof`/`ps` on macOS, `tasklist` on Windows). Reads/deduplicates/cleans session files. Used by all consumers.
- `models.py`: Typed data models. `SessionStatus` enum, `FleetSession` frozen dataclass, `parse_session()` converter, `format_age()` utility.
- `mcp_server.py`: FastMCP server exposing fleet tools to Claude Code and Codex sessions.
- `tui.py`: Textual-based interactive dashboard (`FleetMonitorApp`). Polling, search/filter, desktop notifications, session focus.
- `widgets/session_table.py`: `SessionTable(DataTable)` widget with status-colored rows. Shared between standalone TUI and tongs screen.
- `views/fleet_screen.py`: `FleetScreen(Screen)` for embedding in tongs. Same features as standalone but escape pops back.
- `tongs_plugin.py`: `FleetMonitorPlugin(TongsPlugin)` ABC implementation. Optional tongs dependency. Registers command palette entry and screen.
- `focus.py`: Session lookup and PID resolution. Delegates to terminal APIs for actual focus.
- `cli.py`: Entry point for `claude-fleet` command. Installs Claude Code and Codex hooks and MCP configuration, then delegates to tui/focus/status.

### Terminal APIs (`terminal_apis/`)

Pluggable terminal abstraction. Each terminal has a class implementing `TerminalAPI`:

- `base.py`: ABC defining `detect()`, `capture_env()`, `find_tab()`, `switch_tab()`, `raise_window()`, `focus()` and the structured `focus_result()`. Capability flags: `selection_supported`, `activation_supported`, `activation_before_selection`, `deferred_selection_readback`.
- `konsole.py`: KDE Konsole via qdbus (qdbus, qdbus6 or qdbus-qt6) + KWin scripting. Selection is read back over D-Bus; activation targets one unique owned window and is verified after KWin activation (`deferred_selection_readback`).
- `tmux.py`: tmux via CLI with stable session/window/pane IDs and readback. Routes parent activation per attached client through `parent.py`; owns `TERMINAL_PROCESS_NAMES` and the bounded parent walk.
- `zellij.py`: zellij via CLI. Exact pane selection with `focus-pane-id` and `list-clients` readback using the captured `ZELLIJ_PANE_ID`. Every CLI call carries the session's socket dir (derived from the daemonized server's `--server` argv, else captured `ZELLIJ_SOCKET_DIR`, else default). Linux parent activation: agent ancestry -> server -> the one attached client via `_unix_peers.py`, then `parent.py`; only a plain `zellij` or `attach` peer counts (argv parsed past global options; `action` ignored); several clients, any other peer (`web`, `watch`, `pipe`, ...), a renamed session, a list-clients mismatch or a client whose start time changed is refused.
- `ghostty.py`: Ghostty on Linux: activates only the single managed window owned by the session's Ghostty ancestor (KWin owner-pid request plus xdotool `getactivewindow` readback, X11 only); Alt+N tab switching via ydotool/xdotool only after confirmed activation (requires ydotoold on Wayland).
- `gnome.py`: GNOME Terminal on Linux X11. No tab selection; activates only the single window owned by the `gnome-terminal-server` ancestor and confirms it with `xdotool getactivewindow`.
- `terminator.py`: Terminator, detection only (#47). Captures `TERMINATOR_UUID`, `TERMINATOR_DBUS_NAME` and `TERMINATOR_DBUS_PATH`; claims no selection or activation because Terminator's D-Bus API cannot select or raise.
- `iterm2.py`: iTerm2 via osascript. A session matches only when its `unique ID` (the UUID after `:` in a validated `ITERM_SESSION_ID`) and its `tty` (the agent's controlling tty) both agree, so a leaked `ITERM_SESSION_ID` cannot verify another session; with no captured ID (tmux parent lookup) exactly one session must use the tty. Selection and activation (iTerm2 frontmost, current window holds the session) are claimed only on readback (`deferred_selection_readback`). Unvalidated on macOS (#55).
- `macos_terminal.py`: macOS Terminal.app via osascript. Target is the agent's controlling tty from `ps -o tty=` at focus time (Terminal's AppleScript has no session ID; no pid fallback), matched against `tty of t`. Selection never reorders windows; selection and activation are claimed only on readback (`deferred_selection_readback`). Unvalidated on macOS (#55).
- `_applescript.py`: Runs fixed AppleScript with validated data passed only as `on run argv` arguments, never interpolated; status-token readback with bounded polling; `controlling_tty()` reads a pid's `/dev/ttysNNN` with `ps` at focus time. darwin-only.
- `windows_terminal.py`: Windows Terminal, detection only (owner window not identifiable without validated Win32 enumeration)
- `kitty.py`: Kitty via opt-in remote control (`kitten @ --to <KITTY_LISTEN_ON>`, unix sockets only). Window selection with `ls` readback; selection and activation both require the captured `KITTY_PID` to be a `kitty` ancestor of the session and of the `ls` window's child process (refuses leaked variables and an inherited outer socket; older records without it are refused). Activation on KDE Plasma via `_kwin.py` (verified on Plasma Wayland; Plasma X11 and XWayland kitty not verified) for the single normal window owned by the captured `KITTY_PID` (must be a `kitty` ancestor of the session, of the `ls` window's child process, and own exactly one OS window), confirmed by the script's self-unload signal and kitty's OS window `is_focused` readback. Not a nested parent (`parent_activation_supported = False`). Fleet never edits kitty.conf.
- `_kwin.py`: Shared KWin owned-window activation on `_qdbus.run_kwin_script`: pid, optional normal-window and caption-title filters, exactly one match, un-minimize, activate; values embedded as JSON. A reporting script unloads its own plugin, observed through `isScriptLoaded`, as its only result channel. Used by Konsole (caption match, unchanged behaviour) and kitty.
- `screen.py`: GNU screen via `-X select` with `-Q number` readback and an attached-display guard. No activation (a screen session owns no GUI window).
- `generic.py`: Fallback that identifies no target and never selects or activates
- `parent.py`: `activate_parent()`, the one nested-parent routing helper (`parent_activation_supported()` lets an adapter that activates standalone, like kitty, still refuse parent routing) used by tmux and zellij. Delegates to the parent's own `focus_result()` for activation-first, selection-less or deferred-readback parents; otherwise a failed selection never raises the window.
- `_env.py`: Env-only, never-raising capture helpers for adapters (`bounded_env`, `is_decimal_id`)
- `_ancestry.py`: Linux-only hook-time ancestry walk (`nearest_terminal()`). Reads only `/proc/<pid>/stat` (comm, ppid), at most 64 steps, cycle-safe and never raising. Maps comm names through `tmux.TERMINAL_PROCESS_NAMES` (truncated to 15 characters) plus the tmux, zellij and screen multiplexers.
- `_unix_peers.py`: Linux-only, never-raising unix-socket peer lookup: `sock_diag` netlink dump plus `/proc/<pid>/fd` links of same-UID processes (never `environ`). Used by zellij client discovery.
- `__init__.py`: `detect_terminal()`, `capture_terminal_info()`, `get_terminal_api()`

Detection order: tmux > zellij > konsole > ghostty > iterm2 > macos_terminal > gnome > terminator > windows_terminal > kitty > screen > generic. tmux/zellij first because they run inside other terminals. Kitty and screen sit immediately before generic so every earlier result is unchanged. This env order applies only when the Linux ancestry walk finds no known terminal: on Linux the nearest known terminal or multiplexer ancestor wins over leaked markers (screen inside Konsole is labelled screen), and its adapter's `capture_env()` records whatever markers are present. Elsewhere leaked markers keep precedence (screen inside Konsole is labelled konsole).

Terminal info is captured per-session in the hook (not guessed at focus time). Each session's fleet JSON stores `terminal` and `terminal_env` fields. Capture reads the environment plus, on Linux only, `/proc/<pid>/stat` of the hook's ancestors (approved 2026-10-10, #52). Never `/proc/<pid>/environ` or `cmdline`, no subprocess and no D-Bus at hook time; any walk failure falls back to env detection.

For nested terminals (tmux inside Konsole), `raise_window()` walks the process tree from the tmux client PID to the first name in `TERMINAL_PROCESS_NAMES` and routes through `parent.activate_parent()`. Terminator and Kitty stop the walk and report activation unsupported; screen is never a parent.

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

- Pure Python core, with the approved optional Pi JavaScript bridge isolated from startup; no bash/jq dependencies in Python code
- Module-level imports (function-level only for circular deps or optional deps)
- No comments unless the "why" is non-obvious
- No em-dashes in text or commits
- Cross-platform by default
