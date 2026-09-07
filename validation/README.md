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
