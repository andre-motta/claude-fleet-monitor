# Manual integration validation

These checks are separate from ordinary pytest. Use an environment with the
project and its dependencies installed. They use synthetic temporary fleet data;
they do not prove live harness activity or desktop focus.

## MCP stdio on Linux/macOS

```console
python validation/mcp_stdio.py
```

The script starts the real MCP server process, initializes a protocol session,
lists all five tools and queries a synthetic waiting session. It writes only in
a temporary fleet directory and terminates its child process on completion.
Its pipe selector implementation is for POSIX platforms, not a claimed Windows
validation tool. Process discovery may see host agents but their data stays in
the temporary directory and is not printed.

On the 2026-09-07 validation host, sandboxed AnyIO stdio reads stalled. The same
check passed in the normal host environment, with no external network requests.
A sandbox timeout is not a pass and must be reported separately.

## GitHub Actions workflow lint

The `workflow-lint` job in `.github/workflows/test.yml` downloads the pinned
official actionlint 1.7.12 Linux release, verifies its SHA-256 before
extraction, and checks every `.github/workflows/*.yml` file. It disables the
optional shellcheck and pyflakes integrations so the gate has no project
dependency beyond the standard Ubuntu runner tools.

To reproduce locally with a downloaded actionlint binary:

```console
actionlint -no-color -shellcheck= -pyflakes= .github/workflows/*.yml
```

## Headless Textual application journey

```console
python validation/tui.py
```

This runs the real standalone Textual application with its headless driver and
temporary synthetic Claude, Codex and Pi session records. It checks initial
loading, status and search filters, selected-session details, attention navigation
and clean quit. Only host process enumeration is mocked to prevent unrelated
sessions from entering the fixture; session files, parsing, application workers
and widgets are real. A parent process enforces a 30-second timeout and propagates
failure. The check does not invoke focus, the clipboard or desktop notifications.

This is UI integration evidence using legacy-shaped fixture records, not Pi
ingestion, terminal rendering or live desktop focus evidence. On the validation
host, the sandboxed asynchronous app stalled and was terminated; the normal host
run passed. Run outside a sandbox that blocks the asynchronous driver and record
any timeout as a failure, rather than accepting an incomplete run.

Each hosted Python matrix job also runs this helper after pytest. A failure or
timeout fails that job; the context manager's teardown cannot substitute for a
working quit action, and merely making an empty detail panel visible is rejected.

## Native Konsole tab selection on Linux

```console
python validation/konsole.py
```

This optional native check requires an installed Konsole, a working desktop
session and `qdbus`, `qdbus6` or `qdbus-qt6`. It opens a separate disposable
Konsole window with temporary configuration and synthetic Python children.
Two target sessions have the same working directory and duplicate titles;
both properties are observed before testing. The helper selects each target,
independently reads the current session through D-Bus, and rejects a stale ID.
It verifies that all three fixture children exit before reporting success.

Run with the candidate package installed, or set `PYTHONPATH=src` from its
checkout. Ordinary headless CI does not run this GUI check. It does not exercise
KWin activation, nested multiplexers, or real harness lifecycle events. Its
Linux process-lifetime checks and native result do not establish other platform
support. User settings and existing terminal sessions are not test targets.

## Stable tmux selection and client routing on Linux

```console
python validation/tmux.py
```

This headless check creates an isolated tmux server with a socket containing a
comma, synthetic Python pane processes, and two real PTY clients attached to
different sessions. It verifies stable targets after a session rename and window
renumbering, linked-window session identity, independent active-pane readback,
detached-session selection, stale-target rejection and cleanup of all fixture
clients and pane children. The unrelated client's session and selected pane
must remain unchanged.

Parent terminal detection and calls are instrumented to observe which real
tmux client is routed and whether failed parent-tab selection stops activation.
This proves routing against real tmux state, not GUI window activation or live
harness behavior. No desktop server is required. The existing Pi validation
job runs this check before the real Pi lifecycle test and uploads its JSON
alongside the other validation evidence.

## Shared safety rules for terminal validators

The terminal probe and the zellij, Kitty and GNU screen validators below are
local-only Linux helpers. Ordinary pytest and hosted CI never run them, and CI
does not install these terminals. Each helper starts only disposable
instances: private PTYs, temporary socket, config, cache and data directories,
and unique session names. It records the PID and kernel start time of every
process it starts, signals only those, and reports survivors and stray marker
processes as a failure. It never reads or edits user configuration (a
before-and-after snapshot is compared), never attaches to the user's own
sessions or default socket directories, and never calls KWin, qdbus or
xdotool. Evidence JSON is redacted to placeholders and the helpers refuse to
write a file that still contains a home path, user name or host name. Run each
as a script from the checkout with the candidate package installed in the
active environment.

## Terminal capability probe

```console
python validation/probe_terminals.py --out /tmp/terminal-probe.json
```

The probe records, per terminal (zellij, wezterm, kitty, screen, terminator),
whether it is installed, its version and install source, the environment
marker names and value shapes, process names along the agent ancestry, the
selection and readback commands, whether readback was proven, multi-client
behavior, PID-only lookup viability and activation readback status. `--only`
limits the run to some terminals. The committed
[probe record](evidence/terminal-probe-fedora44.json) was produced on Fedora
44 KDE Plasma Wayland; `tests/test_probe_record.py` checks its schema. It gated
the zellij, Kitty and screen adapters. WezTerm was skipped by CTO decision and
is recorded as `unverified`; Terminator was observed on a private D-Bus
session bus with a hidden window for detection only.

## Exact zellij pane selection on Linux

```console
python validation/zellij.py --no-write
```

This starts a uniquely named zellij session in a private `ZELLIJ_SOCKET_DIR`
with temporary config, cache and data directories, drives it through private
PTY clients, and selects duplicate-title panes across two tabs through
`ZellijAPI`. Each selection is read back with `list-clients` and confirmed by
keystroke routing. It also checks that `--session` overrides an inherited
`ZELLIJ_SESSION_NAME`, that unknown and closed pane IDs fail without moving any
client, that zero attached clients is a failure, that selection before any
client sent input is not reported as success, and that a second client keeps
its own pane. Without `--no-write` it updates
[the evidence](evidence/zellij-fedora44.json) (zellij 0.45.1). GUI activation
is reported unavailable: client PIDs are not exposed and the server is
daemonized.

## Kitty remote-control selection on Linux

```console
python validation/kitty.py --out /tmp/kitty-validation.json
```

This opens disposable minimized kitty windows with `--config NONE`,
`allow_remote_control=socket-only` and a temporary unix `--listen-on`, plus one
instance with remote control off. Environments are captured by the real
`KittyAPI` inside each kitty window. Duplicate-title windows and tabs are
selected through `KittyAPI.focus_result` and confirmed independently with
`kitten @ ls` (tab and window `is_active`; `is_focused` is not used). It also
records stale-window, missing-socket and remote-control-off failures and the
`kitty @` fallback when `kitten` is absent. Because it opens GUI windows, run
it only on a desktop where that is acceptable; it closes every window it
opened. The committed [evidence](evidence/kitty-fedora44.json) covers kitty
0.47.1. Window activation is not claimed.

## GNU screen window selection on Linux

```console
python validation/screen.py --out /tmp/screen-validation.json
```

This starts two screen sessions in a temporary `SCREENDIR` with a temporary
`SCREENRC`, attaches real displays in private PTYs and drives `ScreenAPI` as
the focus path does. Each selection is confirmed by `-Q number` and by
keystroke routing into the window shells. It covers a never-attached and a
detached session (named failure), one and two displays, an unknown or stale
window, a stale session, a malformed `STY` that never reaches argv and an
unrelated session that must not change. Without `--out` it only prints the
JSON. The committed [evidence](evidence/screen-fedora44.json) covers screen
5.0.1. A screen session owns no GUI window, so activation is not supported.

## Combined terminal focus acceptance

The integrated candidate for #32 and #47 is accepted locally with full pytest
on Python 3.10, 3.12 and 3.13, the marker-leak run below, the headless Textual
journey, and reruns of the tmux, zellij and screen validators. The Kitty and
Konsole validators open GUI windows and are run only at the desktop.

```console
env KONSOLE_VERSION=1 KONSOLE_DBUS_SERVICE=x TERMINATOR_UUID=urn:uuid:x \
  KITTY_WINDOW_ID=1 WEZTERM_PANE=1 STY=1.x ZELLIJ=0 ZELLIJ_PANE_ID=1 \
  GNOME_TERMINAL_SERVICE=x TERM_PROGRAM=ghostty TMUX=/tmp/x,1,0 \
  python -m pytest -q tests/test_terminal_apis.py tests/test_terminator.py \
  tests/test_zellij.py tests/test_fallback_terminals.py tests/test_kitty.py \
  tests/test_screen.py
```

The marker-leak run proves that terminal tests do not depend on the markers of
the terminal that runs pytest. Results are recorded in
[the terminal focus record](../docs/work/terminal-focus.md).
