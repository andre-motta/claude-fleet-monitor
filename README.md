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
| Codex | Installed native hooks for start, prompt, tool, permission, stop and end | Discoverable by registered exact process names and ancestry; unresolved records are explicit when process evidence is unavailable | Captured terminal metadata is dispatched to the matching backend; result is complete, partial, unavailable or failed according to observed operations | Desktop conversation targets have no accepted backend; parent-terminal activation is backend-specific | Fleet MCP is available to configured Codex sessions | When the Codex CLI is available, the default installer registers Fleet MCP through the Codex MCP configuration |
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

The table lists implemented backend capabilities and the strongest evidence
behind each claim. Runtime availability, selected-target proof and window
activation vary by environment and are reported as structured focus outcomes;
a successful command alone is never reported as focus. Evidence labels:
**live** (real program observed on Fedora 44 KDE Plasma Wayland),
**instrumented** (real program with Fleet calls recorded), **mocked** (pytest
with substituted OS calls), **inspected** (source or documentation only) and
**unverified** (not observed).

| Terminal | Tab or pane selection | Window raise | Nested support | Evidence |
|----------|:---:|:---:|:---:|---|
| **KDE Konsole** | Yes (qdbus, qdbus6 or qdbus-qt6, D-Bus readback) | Yes (KWin, one unique owned window, readback) | -- | live: Konsole 26.08 tab selection ([JSON](validation/evidence/konsole-fedora44.json)); cross-window tab plus window confirmed hands-on through the TUI; mocked; as a tmux parent the Konsole service owned by the client's nearest ancestor is used (mocked) |
| **tmux** | Yes (stable IDs, readback) | Via parent terminal, per attached client; failures name the reason (no attached client, no parent emulator, unsupported or unconfirmed parent) | Yes | live: tmux 3.7c selection ([JSON](validation/evidence/tmux-fedora44.json)); parent routing instrumented and mocked; failure details mocked |
| **zellij** | Yes (`focus-pane-id`, `list-clients` before and after readback); needs an attached client and the monitor's zellij socket dir | No (parent emulator not reachable) | Yes | live: zellij 0.45.1 ([JSON](validation/evidence/zellij-fedora44.json)); floor 0.44.2, validator passing on 0.44.2 to 0.45.1 ([JSON](validation/evidence/zellij-version-floor-fedora44.json)); moved-client rule mocked |
| **Kitty** | Yes, opt-in remote control with a `unix:` listen_on socket (`kitten @ ls` readback) | No (not claimed) | -- | live: kitty 0.47.1 ([JSON](validation/evidence/kitty-fedora44.json)); window raise unverified |
| **GNU screen** | Yes (`-X select`, `-Q number` readback); needs an attached display, and with several only the most recently attached one switches | No (no GUI window) | -- | live: screen 5.0.1 ([JSON](validation/evidence/screen-fedora44.json)) |
| **Ghostty (Linux)** | Best effort (ydotool/xdotool Alt+N), only after confirmed activation | Requires exactly one window-manager-managed window (minimized or on another desktop counts) owned by the Ghostty process the session descends from; KWin is asked first but success needs xdotool `getactivewindow` readback, so X11 only | -- | mocked and inspected; unvalidated on this branch (Ghostty not installed on the validation host) |
| **GNOME Terminal** | No | Exact owner window only: the single window-manager-managed window (minimized or on another desktop counts) of the session's gnome-terminal-server, X11 only (xdotool readback) | -- | mocked; not live-validated |
| **Terminator** | No (detection only, #47) | No | -- | detection live (terminator 2.1.5 [probe](validation/evidence/terminal-probe-fedora44.json)); mocked; #47 inspection |
| **iTerm2** | Yes (osascript; the session whose `unique ID` (from a well-formed `ITERM_SESSION_ID`) and `tty` both match the agent, readback of the current window's current session) | Yes (the target's own window, un-minimized; readback that iTerm2 is frontmost and its current window holds the session) | -- | mocked and inspected (iTerm2 source); unvalidated on macOS ([#55](https://github.com/andre-motta/claude-fleet-monitor/issues/55)); as a tmux parent the single session using the client's tty is matched (mocked) |
| **macOS Terminal** | Yes (osascript; tab matched by the agent's controlling tty from `ps`, readback of the front window's selected tab) | Yes (the target's own window, un-minimized; readback that Terminal is frontmost and its front window holds the tab) | -- | mocked and inspected; unvalidated on macOS ([#55](https://github.com/andre-motta/claude-fleet-monitor/issues/55)); as a tmux parent the client's tty is matched (mocked) |
| **Windows Terminal** | No (detection only) | No (owner window not identifiable) | -- | mocked; unvalidated on Windows |
| **WezTerm** | No (no adapter) | No | -- | not validated (skipped); sessions fall back to generic |
| **Generic fallback** | No | No | -- | mocked |

"Yes" means the operation is attempted and reported as succeeded only after
independent readback. Version support is the one version validated on the
host, except zellij: the isolated validator passes on 0.44.2 through 0.45.1.
zellij 0.44.1, the first release with `focus-pane-id`, selects panes but did
not pass the two-client check; 0.44.0 and older have no `focus-pane-id`, so
selection reports a failure instead of a guess.

On macOS, captured identifiers are validated (`ITERM_SESSION_ID` must be
`w<N>t<N>p<N>:<UUID>`) and reach `osascript` only as arguments to the
script's run handler, never as AppleScript source. Both adapters match the
agent's controlling tty, read with `ps` at focus time; an agent without one has
no target. When a session ID was captured, iTerm2 also requires it to match,
so an `ITERM_SESSION_ID` inherited by a program launched from an iTerm2 shell
cannot select the wrong session; without one (nested tmux parent routing) the
tty alone must identify exactly one session. Terminal.app's AppleScript exposes no session ID, so its tab is
matched by tty alone. Readback is part of the design, but neither
adapter has been run on a Mac yet; see
[#55](https://github.com/andre-motta/claude-fleet-monitor/issues/55).

Nested terminals (e.g. tmux inside Konsole) are handled automatically: the
focus command selects the exact pane, then routes window activation to the
terminal emulator hosting a client that is attached to that pane. The
structured result reports selection and activation separately, so a detached
session or an unsupported parent gives an honest partial result. Kitty and
Terminator stop the parent walk and report activation unsupported rather than
climbing to whatever launched them. A zellij server is daemonized, so the
emulator showing a zellij client is not reachable and zellij activation is
reported unavailable.

tmux selection uses stable session, window and pane IDs with selection readback.
Parent-window routing considers only clients attached to the target session;
detached sessions can still select their pane without activating a GUI window.
When several attached clients show the target pane in different emulator
windows, each client's parent is tried in turn. Routing stops after the
first parent that sent a raise request (a KWin activation script that ran, an
`xdotool windowactivate`, or a call to a parent's raise), even when the window
or tab could not be confirmed afterwards. Focus then reports why, for example
`parent terminal konsole may have raised its window but could not confirm it
(...)`, instead of trying another window. A parent that fails before sending
any request (no unique GNOME or Ghostty X11 window, Konsole D-Bus owner
unreadable, qdbus missing) lets the next client be tried. For Konsole, window
matching happens inside the KWin script, so a script that ran but matched no
unique window also stops routing. One rare case can still raise two windows: a KWin script run call that
fails or times out is treated as no request, although KWin may have run it.
See the [isolated tmux validation](validation/README.md#stable-tmux-selection-and-client-routing-on-linux)
for the tested routing behavior and its GUI evidence limits.

Terminator is detection only ([#47](https://github.com/andre-motta/claude-fleet-monitor/issues/47),
reported by @EmilienM). Sessions are labelled `terminator` and capture
`TERMINATOR_UUID`, `TERMINATOR_DBUS_NAME` and `TERMINATOR_DBUS_PATH`, but
focus reports an honest unsupported failure: Terminator's D-Bus interface
cannot select a terminal or raise a window.

### Kitty remote control

Kitty selection needs remote control, which Fleet never enables for you and
never writes into `kitty.conf`. Add both settings yourself and restart kitty:

```conf
allow_remote_control socket-only
listen_on unix:${XDG_RUNTIME_DIR}/kitty-{kitty_pid}
```

Kitty then exports `KITTY_LISTEN_ON`, which the hook captures with
`KITTY_WINDOW_ID`. Only `unix:` socket addresses (an absolute path or an
`@abstract` name) are used; `tcp:`, `fd:` and relative addresses are dropped
at capture. Without remote control or a `unix:` listen_on socket, focus reports
"kitty remote control unavailable: needs allow_remote_control and a unix:
listen_on socket" and changes nothing.

**Security warning:** with `allow_remote_control` enabled, any local process
that can reach the socket can control kitty, including sending text to its
windows and running commands. Prefer `socket-only` over `yes`, keep the socket
in a directory only you can access (as `$XDG_RUNTIME_DIR` above), avoid
abstract `@` sockets on shared hosts, and turn remote control off when you do
not need it. Fleet only runs `ls` and `focus-window` and never sends a remote
control password; if kitty requires one, focus reports the refusal instead of
selecting.

### Terminal detection limits

Terminal markers leak into child processes: Kitty started from a Konsole
shell inherits `KONSOLE_*`, anything started from a Terminator shell inherits
`TERMINATOR_UUID`, and a terminal launched from a tmux pane inherits `TMUX`.
On Linux the hook therefore first walks its own process ancestry, reading only
the process name and parent PID from `/proc/<pid>/stat` (never the environment
or command line of another process, at most 64 steps). The nearest Konsole,
Ghostty, GNOME Terminal, Terminator, Kitty, tmux, zellij or GNU screen ancestor
sets the label, and that adapter records whichever of its markers are present.
So Kitty started from Konsole is labelled `kitty`, GNU screen or zellij inside
tmux or Konsole is labelled `screen` or `zellij`, and a Konsole window opened
from a tmux pane is labelled `konsole`. When the walk finds no known terminal
or cannot read `/proc`, detection falls back to the fixed environment-variable
order. Remaining limits:

- On macOS and Windows detection uses environment variables only, so the
  leaked-marker cases above keep the label of the launching terminal.
- A terminal adapter selected by ancestry can lack its own markers (for
  example Kitty without remote control), so focus reports its usual
  unavailable or unsupported failure rather than using the leaked markers.
- WezTerm has no adapter. Its sessions are labelled `generic`, or after a
  known terminal that launched WezTerm (for example `konsole`): the ancestry
  walk passes WezTerm and reaches the launcher, matching the leaked markers.
  If a
  multiplexer inside WezTerm reaches a known emulator that launched WezTerm,
  the parent walk continues to it; that emulator then finds no matching tab.
- Records captured before an upgrade keep their old label and environment;
  start a fresh agent session to pick up new capture keys such as
  `ZELLIJ_PANE_ID`.

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
- `qdbus`, `qdbus6` or `qdbus-qt6` -- Konsole tab switching and KWin activation (KDE)
- `xdotool` -- GNOME Terminal / X11 window focus
- `kitten` or `kitty` with remote control enabled -- Kitty window selection
- `zellij` and `screen` CLIs -- pane and window selection for those multiplexers
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
  --> Linux: nearest known terminal or multiplexer ancestor (/proc/<pid>/stat only)
  --> otherwise detect terminal via env vars (TMUX, KONSOLE_VERSION, ITERM_SESSION_ID, ...)
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
        ghostty.py        # Ghostty (Linux, owner-window KWin/X11)
        gnome.py          # GNOME Terminal
        terminator.py     # Terminator (detection only)
        iterm2.py         # iTerm2
        macos_terminal.py # macOS Terminal.app
        windows_terminal.py # Windows Terminal (detection only)
        kitty.py          # Kitty (opt-in remote control)
        screen.py         # GNU screen
        generic.py        # Fallback (no target)
        parent.py         # Nested parent-terminal routing
        _env.py           # Env-only capture helpers
        _ancestry.py      # Linux hook-time ancestry walk (comm and ppid only)
        _applescript.py   # macOS osascript runner (argv-only data) and tty lookup
```

## Known Limitations

- **Same-title tabs in different windows (Konsole/KDE):** Konsole window activation must match exactly one window of the owning Konsole process. When two windows show the same caption, focus selects the tab but reports activation as failed ("no unique Konsole window matched the tab title") instead of raising a guess.
- **Wayland window activation:** On Wayland/KDE, window raising uses KWin scripting via DBus. Other Wayland compositors may not support programmatic window activation.
- **GNOME Terminal:** No tab switching API available; window raise only for the exact owning window on X11. A server with several windows, including minimized ones or ones on other desktops, reports activation unavailable.
- **Ghostty:** Window activation requires a single managed Ghostty window (minimized and other-desktop windows count) and an X11 readback; with several windows, or on Wayland without xdotool readback, activation fails with a detail and no Alt+N keys are sent. This path is mocked only.
- **Windows Terminal:** Detection only. Its window titles follow the active tab and all windows usually share one process, so the session window cannot be identified without Win32 enumeration validated on Windows.
- **Terminator:** Detection only. Its D-Bus interface has no select or raise method, so focus reports an unsupported failure until Terminator gains one (#47).
- **Kitty, GNU screen and zellij windows:** Selection is read back, but no GUI window activation is claimed. Kitty offers no independent OS focus readback, a screen session owns no window, and a zellij client's emulator is not reachable from the daemonized server.
- **GNU screen and zellij with several displays or clients:** GNU screen switches only the most recently attached display, and zellij moves only the client that most recently received input; other displays and clients keep their own window or pane. Both need an attached display or client: a detached session reports a failed selection.
- **zellij socket directory:** Fleet runs `zellij --session` with its own environment, so it finds a session only when its `ZELLIJ_SOCKET_DIR` matches the session's. Sessions started with a custom `ZELLIJ_SOCKET_DIR` report a failed selection instead of a guess.
- **zellij selection proof:** Selection succeeds only when a client that was elsewhere moves to the pane, or when every attached client already showed it ("pane already focused"). An idle client that already showed the pane while the active client did not move is a failure.
- **Generic fallback:** Unknown terminals get no selection or window raise; the earlier best-effort raise could activate an unrelated window and was removed.

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
