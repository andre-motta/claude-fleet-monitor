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

| Backend | Detection | Exact target | OS window activation | Evidence and truthful current claim |
| --- | --- | --- | --- | --- |
| tmux | `$TMUX` | Pane by pane-shell PID or Linux ancestor walk | Delegates to a small parent-terminal process allowlist | **Live exact-pane selection** on isolated tmux 3.7c for three panes; parent window untested |
| Konsole | `$KONSOLE_VERSION` and captured D-Bus values | Session PID lookup through qdbus | KWin script by tab title | Inspected and mocked only; Konsole 26.08.0 was installed but qdbus and a live Konsole process were unavailable |
| Zellij | `$ZELLIJ` | Not implemented; current code returns the agent PID as a placeholder | Best-effort parent walk | Detection mocked only; current `focus-tab` call has no exact target and must not be called exact support |
| Ghostty | `TERM_PROGRAM=ghostty` | Guesses tab number from direct-child order, limited to 1 through 9, then simulates Alt+number | KWin class match or xdotool | Inspected and mocked only; fallback target plus ignored failures can produce false success |
| GNOME Terminal and VTE family | Broad `VTE_VERSION` or GNOME service test | No tab selection; xdotool ancestor search finds an X11 window | xdotool | Detection mocked only; broad VTE detection can mislabel non-GNOME terminals; unavailable on this Wayland host |
| iTerm2 | `$ITERM_SESSION_ID` | Captured iTerm session ID through AppleScript | AppleScript `activate` | Inspected and detection mocked only; command exit and actual selection are not verified |
| macOS Terminal | `TERM_PROGRAM=Apple_Terminal` | Code compares captured `TERM_SESSION_ID`, or a PID fallback, with a tab tty | AppleScript `activate` | Inspected and detection mocked only; the identifier-to-tty match is not established |
| Windows Terminal | `$WT_SESSION` | Not implemented | Optional pywinctl title match | Detection mocked only; first same-title window may be wrong and pywinctl is not a declared dependency |
| Generic | Always | No exact target; PID is a placeholder | pywinctl, xdotool, or an ineffective macOS fallback | Best effort only; current Boolean can be a false success |

The live tmux probe used a detached server on an isolated temporary socket, did
not attach to or alter a user terminal, and selected `fleetprobe:0.0`, `.1` and
`.2` successfully. This verifies the installed Linux PID-to-pane and
`select-window`/`select-pane` path. It does not verify a nested parent terminal
or OS window activation. The first sandboxed attempt could not create the Unix
socket; the same isolated probe passed outside that sandbox restriction.

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
| tmux | Exact pane selection is implemented; parent detection only recognizes Konsole, Ghostty, GNOME Terminal, iTerm2, Terminal.app and Windows Terminal process names | Claim exact pane only where live; test each parent backend separately and add Kitty/WezTerm names only with a backend |
| Zellij | Detected first, but the agent PID is not a pane ID and current action has no exact target | No exact-focus claim until hook-time pane ID is stored and live duplicate-pane tests pass |
| GNU screen | No backend | Untested; prove window and region identity plus parent activation before support |
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
