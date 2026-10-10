# Shell, terminal and boundary compatibility inventory

Status: **S1 research candidate for issue
[#31](https://github.com/andre-motta/claude-fleet-monitor/issues/31)**. This is a
documentation and evidence item. It does not add or claim new production
support. Baseline: Agent SDLC 0.1.0 at repository revision
`229a9d3c2d935f3fcfeb08a747c7235569180706`. Investigation date: 2026-09-07.

## Meaning of support

Fleet currently combines several independent capabilities behind a Boolean
`focus()` result. A truthful compatibility claim must instead state which of
these capabilities passed:

1. **Emitter**: the harness can run `claude-fleet-hook` and write a valid event.
2. **Detection**: Fleet identifies the terminal or multiplexer at hook time.
3. **Process context**: Fleet records or resolves the agent PID, tty and cwd.
4. **Lifecycle**: start, running, waiting, idle, error and ended states reflect
   real harness events.
5. **Exact target**: Fleet selects the pane or tab containing that agent.
6. **Window activation**: Fleet raises the OS window containing that target.

Evidence in this report is labeled **live** for a real local program and
observable behavior, **synthetic** for the real Fleet emitter with constructed
event input, **mocked** for pytest behavior with substituted OS calls, and
**inspected** for source or primary documentation. A mock or source inspection
does not establish live support.

## Current architecture findings

The configured Claude Code and Codex hooks use a plain command consisting of
the installed `claude-fleet-hook` path plus fixed arguments. Fleet does not
source an interactive shell configuration or generate shell-specific syntax.
The user's command shell therefore has little effect on lifecycle emission.
It can affect process ancestry, executable naming, tty discovery and the
terminal or multiplexer surrounding the agent.

The hook obtains cwd and session ID from the harness event, not the shell. On
Linux it walks `/proc` to find an agent ancestor. On macOS it falls back to
`ps`. The same fallback is used on native Windows even though `ps` is not a
standard Windows command, so a Windows hook can write status without recording
a PID. Process discovery uses `/proc` on Linux, `lsof` plus `ps` on macOS, and
`tasklist` on Windows. It only records tty on Linux. `focus.get_pid()` still
falls back to `pgrep` plus `/proc` without a platform abstraction.

The current focus result is not reliable evidence of focus. The base
`TerminalAPI.focus()` returns true whenever `find_tab()` returns a value and
ignores failures from `switch_tab()` and `raise_window()`. A direct probe with a
backend whose switch and raise methods both returned false still produced true.
The Ghostty override has the same behavior. Generic always returns the PID as a
target, so it can also report success when no window was activated. Most
subprocess-backed methods do not check nonzero exit status. This confirms the
structured, capability-specific result required by H1
[#25](https://github.com/andre-motta/claude-fleet-monitor/issues/25) and S2
[#32](https://github.com/andre-motta/claude-fleet-monitor/issues/32).

## Command shell matrix

These results cover invocation of the installed 0.6.0 emitter whose `hook.py`
matched the baseline source byte for byte. They do not prove PID discovery or
desktop focus. The synthetic payload used a cwd with spaces and Unicode, and
ran `session-start`, `prompt-submit`, `tool-use`, `permission-request`, `stop`
and `session-end` in sequence. Each successful run ended with a valid `ended`
record and the original cwd-derived repository name.

| Command shell | Local availability | Emitter evidence | Current claim |
| --- | --- | --- | --- |
| POSIX `sh` | `/usr/bin/sh`, Bash 5.3.9 | Synthetic sequence passed | Emitter only on this host |
| Bash | 5.3.9 | Synthetic sequence passed | Emitter only on this host |
| Bash POSIX mode | 5.3.9 | Synthetic sequence passed | Emitter only on this host |
| dash | Unavailable; local `sh` is Bash | Not run | Untested |
| zsh | Unavailable | Not run | Untested |
| fish | Unavailable | Not run | Untested |
| ksh / mksh | Unavailable | Not run | Untested |
| Nushell | Unavailable | Not run | Untested |
| PowerShell / `pwsh` | Unavailable | Not run | Untested; native Windows PID path has a known gap |
| Windows `cmd.exe` | Unavailable | Not run | Untested; native Windows PID path has a known gap |
| csh / tcsh, Elvish, Xonsh, Oil | Unavailable | Not run | Candidate coverage only |

The synthetic worker did not have a real agent ancestor or terminal-specific
environment, so the expected record had an empty PID and `generic` terminal.
Those values are limitations of the probe, not shell failures.

Podman was available but was not used in this bounded investigation. A later
isolated container matrix can add real dash, zsh, fish, ksh, mksh and Nushell
emitter and process-ancestry evidence without changing user shell setup. Such a
matrix cannot prove terminal detection or desktop focus because the container
does not own the host terminal or display.

## Current terminal and multiplexer matrix

Refreshed on 2026-10-09 for the terminal focus initiative (#32, #47) on the
`feat/terminal-focus-2` integration branch. Rows below supersede the S1
snapshot from 2026-09-07; the original S1 probe notes follow the table. Live
rows were observed on Fedora 44 KDE Plasma Wayland. Every claimed selection
requires independent readback, and GUI activation that could not be observed
stays unverified.

| Backend | Detection | Exact target | OS window activation | Evidence and truthful current claim |
| --- | --- | --- | --- | --- |
| tmux | `$TMUX` | Stable `$session:@window.%pane` IDs with readback | Per attached client through `parent.activate_parent`; stops at Kitty and Terminator | **Live exact-pane selection** on isolated tmux 3.7c; parent routing instrumented and mocked; tmux inside a background Konsole window pending Andre's hands-on check |
| Konsole | `$KONSOLE_VERSION` and captured D-Bus values | Session PID lookup through qdbus, qdbus6 or qdbus-qt6, current-session readback | KWin script on the one unique window of the owning process, verified after activation | **Live** tab selection on Konsole 26.08.0 (validation JSON); cross-window tab plus window confirmed hands-on by Andre through the TUI on 2026-10-09; duplicate captions fail with a named detail |
| Zellij | `$ZELLIJ` plus captured `ZELLIJ_PANE_ID` and session name | `focus-pane-id` with `list-clients` readback | Unavailable: daemonized server, client PIDs not exposed | **Live exact-pane selection** on zellij 0.45.1 with duplicate panes and tabs; records without a pane ID report selection unavailable |
| Kitty | Decimal `$KITTY_WINDOW_ID` | `kitten @ --to <unix socket> focus-window` with `ls` readback (tab and window `is_active`) | Not claimed | **Live selection** on kitty 0.47.1 with opt-in remote control; activation unverified; remote control off reports unavailable |
| GNU screen | `$STY` (`<digits>.<name>`) plus decimal `$WINDOW` | `-X select` with `-Q number` readback and non-empty `-Q windows` | Not supported (no GUI window) | **Live selection** on screen 5.0.1, one and two displays; detached sessions fail with a named detail |
| Ghostty | `TERM_PROGRAM=ghostty` | Guesses tab number from direct-child order, then simulates Alt+number after activation | Single managed owner window only: KWin owner-pid request (never success alone) plus xdotool activation with `getactivewindow` readback (X11); refuses when the Ghostty process owns several windows | Inspected and mocked only; not installed on the validation host |
| GNOME Terminal | `GNOME_TERMINAL_SERVICE`; `VTE_VERSION` alone is not GNOME | None | Single X11 window owned by the `gnome-terminal-server` ancestor, `getactivewindow` readback | Mocked only; unavailable on Wayland or with several windows |
| Terminator | `$TERMINATOR_UUID` | None (detection only, #47) | None | Detection **live** (terminator 2.1.5 probe, env and ancestry only); focus mocked |
| iTerm2 | `$ITERM_SESSION_ID` | Captured iTerm session ID through AppleScript | AppleScript `activate` | Inspected and mocked only; no macOS host |
| macOS Terminal | `TERM_PROGRAM=Apple_Terminal` | Captured `TERM_SESSION_ID` or a PID fallback compared with a tab tty | AppleScript `activate` | Inspected and mocked only; no macOS host |
| Windows Terminal | `$WT_SESSION` | None (detection only) | None: the owner window is not identifiable without validated Win32 enumeration | Mocked only; no Windows host |
| WezTerm | None (no adapter) | None | None | Not validated (skipped by CTO decision); sessions fall back to generic |
| Generic | Always | None | None | Mocked; the former best-effort pywinctl/xdotool raise was removed as a false positive |

S1 probe notes (2026-09-07). The live tmux probe used a detached server on an
isolated temporary socket, did not attach to or alter a user terminal, and
selected `fleetprobe:0.0`, `.1` and `.2` successfully. This verifies the
installed Linux PID-to-pane and `select-window`/`select-pane` path. It does not
verify a nested parent terminal or OS window activation. The first sandboxed
attempt could not create the Unix socket; the same isolated probe passed outside
that sandbox restriction.

## High-value additions and corrections

1. **Make focus outcomes truthful before adding backends.** Return separate
   target-found, target-selected and window-activated results with reasons.
   Check process return codes and postconditions. Preserve the Boolean API only
   as an explicit compatibility mapping whose partial-success semantics are
   settled in H1.
2. **Correct Zellij targeting.** Current Zellij documents
   `ZELLIJ_PANE_ID` and `zellij action focus-pane-id`. Capture the stable pane ID
   at hook time, retain the session name, select that pane, and verify the
   command result. This is a correction to an existing support claim rather
   than a new emulator.
3. **Add WezTerm.** Capture `WEZTERM_PANE`; its CLI can activate a specific pane
   by ID. `wezterm cli list --format json` exposes window, tab and pane IDs plus
   cwd, but not a child PID in the documented output, so hook-time pane capture
   is the preferred identity. Validate OS window activation separately.
4. **Add Kitty with opt-in remote control.** Kitty remote control lists windows
   and supports PID, cwd and ID match expressions plus `focus-window`. Remote
   control must be enabled and OS focus can still be blocked by the window
   manager. Fleet must report the disabled and blocked cases rather than imply
   universal support.
5. **Assess GNU screen.** Screen exposes `$STY`, window numbers and commands to
   select a named or numbered window. Capturing the current screen window at
   hook time is more reliable than later PID guessing. Region selection and
   parent window activation need separate proof.
6. **Classify simple emulators as window-only until proven otherwise.**
   Alacritty, foot, xterm, Rio, mintty, Hyper, Tilix, Terminator and XFCE Terminal
   should remain untested generic or window-only candidates unless a stable API
   proves exact target selection. Process-title matching alone is insufficient.

Status on 2026-10-09 (#32, #47): item 1 is delivered through structured focus
results, item 2 through hook-time pane capture with live readback, item 4 as
the opt-in Kitty adapter and item 5 as a GNU screen adapter after live readback
was proven. Item 3 (WezTerm) was skipped by CTO decision and stays unvalidated.
Under item 6, Terminator became a detection-only backend (#47) and the generic
fallback no longer raises any window.

Primary references inspected on 2026-09-07:

- [Kitty remote control](https://sw.kovidgoyal.net/kitty/remote-control/)
  documents window listing, PID/cwd/ID matching and focus commands, along with
  the required remote-control configuration.
- [WezTerm pane listing](https://wezterm.org/cli/cli/list.html) and
  [pane activation](https://wezterm.org/cli/cli/activate-pane.html) document
  machine-readable pane IDs and exact activation.
- [Zellij CLI actions](https://zellij.dev/documentation/cli-actions.html)
  documents stable pane IDs, `ZELLIJ_PANE_ID` and `focus-pane-id`.
- [GNU Screen manual](https://www.gnu.org/software/screen/manual/screen.html)
  documents session/window selection and commands directed at a window.

## Boundary matrix

| Boundary | Current behavior | Required claim and validation |
| --- | --- | --- |
| tmux | Exact pane selection is live; the parent walk recognizes Konsole, Ghostty, GNOME Terminal, Terminator, Kitty, iTerm2, Terminal.app and Windows Terminal process names, plus the stop-list of emulators without an adapter (#58), and stops at the first | Kitty, Terminator and stop-listed emulators (WezTerm, Alacritty, foot, ...) stop the walk with activation unsupported; tmux inside a background Konsole window needs Andre's hands-on check |
| Zellij | Hook-time `ZELLIJ_PANE_ID` gives live exact-pane selection; the generic fallback raise was removed | Parent activation stays unavailable unless a reliable client-PID mapping is found |
| GNU screen | Window selection is live with readback; detection sits immediately before generic, so screen inside another emulator keeps that emulator's label | Region (split) selection and parent activation remain unclaimed; screen is never a parent-walk stop |
| SSH to a remote host | Hooks and `FLEET_DIR` are host-local; a remote agent writes a remote store and a remote focus process cannot directly activate the local terminal | Document local and remote Fleet instances explicitly; do not claim cross-host focus without an authenticated bridge design |
| WSL in Windows Terminal | `$WT_SESSION` may identify the outer terminal, while Fleet runs in a separate Linux process/filesystem and the current pywinctl path is not established across WSL | Untested; prove storage location, Windows PID/window mapping, exact pane limits and `wt.exe` behavior on WSL 1 and WSL 2 |
| Nested multiplexers | Detection stops at the first of tmux or Zellij; only tmux/Zellij attempt a parent walk | Test tmux-in-Zellij, Zellij-in-tmux and multiplexer-in-emulator explicitly; report each layer's result |
| Containers and remote dev shells | Namespace PID, `/proc`, filesystem and display ownership can differ | Treat as untested boundary; require an explicit shared-store and host-focus contract |

## Acceptance matrix for implementation work

Every claimed shell, terminal and boundary should be evaluated against the same
tests. Unavailable platforms remain unmet or explicitly waived, never replaced
by mocks.

| Capability | Minimum acceptance |
| --- | --- |
| Detection | Positive and negative environment cases, nested precedence, captured values free of unrelated environment data |
| PID, tty and cwd | Real agent-shaped child process through each available shell; spaces and Unicode cwd; stale and reused PID; Linux, macOS and Windows behavior labeled separately |
| Lifecycle status | Real harness events where available; otherwise labeled synthetic events for every state, including error and end |
| Exact pane/tab | At least two targets with the same cwd and duplicate titles; select each by stable identity and verify the active pane/tab afterward |
| Window activation | Already active, background and minimized window; multiple windows of the same emulator; X11, each claimed Wayland compositor, macOS and Windows tested separately |
| Failure reporting | Missing binary, disabled control API, stale ID, permission denial, nonzero command, timeout and blocked focus all return an accurate partial or failed result |
| Boundaries | Native, each supported multiplexer nesting, SSH/remote, WSL and container results reported independently |

## Local environment and evidence limits

The available host was Fedora Linux 44, kernel 7.1.13, with Python 3.12.14 and
3.14.7, KDE Plasma on Wayland and an X display compatibility variable.
Installed relevant programs were Bash 5.3.9, tmux 3.7c and Konsole 26.08.0. No
live Konsole process, qdbus, xdotool or ydotool was available to the worker. No
supported target was installed merely to improve the matrix.

The repository test command could not start in this worktree because the
environment Python had no pytest module. The initiative baseline already records
86 passing tests and four optional Tongs skips at this same repository revision;
that prior run is inherited evidence, not a new S1 execution. Existing terminal
tests mock environment detection only and do not prove actual focus.

No user shell configuration, harness settings, terminal layout or fleet store
was modified. Synthetic event files and detached tmux sockets were confined to
temporary directories and removed after each probe. macOS, Windows, WSL, SSH,
Zellij, screen and all uninstalled shells and emulators remain untested.
