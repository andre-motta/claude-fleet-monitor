# Terminal focus follow-up

Issue: [#32](https://github.com/andre-motta/claude-fleet-monitor/issues/32),
under [#23](https://github.com/andre-motta/claude-fleet-monitor/issues/23).
Workflow: Agent SDLC 0.1.0, source
`4e851d1b8a903aa8bebceea078860a21152ee8e8`.

## Approved first slice

Andre accepted the bounded Konsole correction after the v0.7.0 release.
Base: `e80eebb21e98a916fa3cf72f53cb50742383c10f`.
The baseline passed 193 tests with optional Tongs installed.

Resolve the installed Qt D-Bus executable, handle failed commands consistently,
and verify selected-session readback. Preserve the existing structured focus
contract. A successful KWin script launch does not establish window activation.
Correct the related Konsole and Zellij capability-table claims.

Astra owns isolated `feat/terminal-focus`; Luna xhigh authors the correction in
`feat/konsole-qdbus`, with independent Sol high review. Andre subsequently
authorized publishing the combined reviewed change directly as a PR against
`main`, superseding the proposed child-PR step for this terminal follow-up.
The earlier `feat/harnesses-desktop` branch was delivered and cleaned up.
Reviewed local commits are signed off; all six hosted checks remain required.
Main merge and another release remain CTO-gated.

Tmux routing, new terminal adapters, the Tongs desktop module, and ChatGPT focus
retain separate scope and acceptance. This first slice does not close #32.

## Verification requirements

- Supported Qt D-Bus aliases and deterministic precedence; missing or disappearing
  executables, timeouts, nonzero status and misleading output fail safely.
- Successful selection requires the requested session to be read back from the
  addressed Konsole window. Stale targets cannot succeed merely because a void
  D-Bus method returned zero.
- A disposable native Konsole instance exercises synthetic Python sessions with
  duplicate titles and the same working directory. Each selected session is
  independently read back through D-Bus. Temporary configuration and child
  processes are cleaned up. User sessions and settings are not test targets.
- KWin window activation is not exercised or claimed. A successful tab selection
  can remain a partial focus result. Other platforms and multiplexer nesting do
  not gain live acceptance from this probe.
- Full pytest, semantic workflow lint, and the existing hosted Python, TUI, shell
  and Pi gates remain required for the combined candidate.

The initial sandboxed `konsole --help` process aborted during Qt initialization;
the same read-only command succeeded in the normal desktop environment. Native
acceptance uses that environment rather than treating the aborted run as proof.

## Delivery checkpoint

Luna's correction is committed at
`e613d3dbc8835a6929aca230e3ea723215c33e7e`: 10 focused tests and all 203 tests
passed. The native check passed on Konsole 26.08.0 using `qdbus-qt6`, selecting
sessions 1, 2, then 1 with independent readback and rejecting a stale session.
The unchanged native API returned exit code zero for that stale ID, confirming
why command status alone cannot establish selection.

Independent evidence review required actual title/cwd observations and verified
cleanup of all synthetic children. The revised helper observes both fixture
properties and verifies three children have exited before reporting success.
See [native evidence](../../validation/evidence/konsole-fedora44.json) and
the [reproduction command](../../validation/README.md#native-konsole-tab-selection-on-linux).

Independent Sol high review approved the exact implementation and acceptance
helper/evidence, with no mandatory findings. Sol independently passed all 10
focused tests and all 203 tests. Hosted PR gates remain required before final
main acceptance. The live result covers tab selection only; window activation
remains unverified.
## Approved tmux follow-up

Andre approved the next bounded slice under #32: stable tmux target IDs and
correct client routing. Base: `00cf29b2ce90327ed76f4c0758e7363440b00b48`.
The source baseline passes 203 tests. An initial run accidentally imported the
older installed v0.7 package; rerunning with the checkout source path passed.

Sol high authors the backend and focused regressions in `feat/tmux-routing`.
Astra owns separate live validation, documentation and integration. Another Sol
high reviews the actual combined candidate. Signed-off local commits are
permitted; the user's existing direct-main-PR instruction applies. Main merge
and releases remain Andre's gate.

Use stable session/window/pane IDs and the captured socket. Select and verify
the exact target after renaming or index changes. Resolve process ancestry
through shared discovery. Parent activation considers only clients attached to
the target session and requires successful parent tab selection where supported.
Detached, ambiguous, stale, missing-tool and failed-command cases fail safely;
never fall back to activating an arbitrary window. Existing structured focus
results remain unchanged.

Validation covers focused regressions plus a real isolated tmux server with
synthetic processes and clients, independent selection readback and cleanup.
Any instrumented parent routing is labeled separately from real GUI activation,
which this slice does not claim. Existing Python/TUI, shell and Pi gates remain
required. Tongs and other terminal adapters are outside this assignment.

## Tmux acceptance checkpoint

The combined implementation and validation candidate is
`ee6ccde1c7a1537bebbf02bb38b3d1f3566cfa7e`, based on the Konsole squash merge
`00cf29b2ce90327ed76f4c0758e7363440b00b48`. Operational tmux calls require
valid captured socket and session metadata. Session/window/pane IDs replace
mutable names and indexes, selection requires readback, and only attached
non-control clients currently viewing the exact target are eligible for parent
routing. Missing metadata never probes the caller's default server.

Local acceptance passed all 246 tests on Python 3.12.14 with optional Tongs,
the headless Textual journey, workflow semantic lint and whitespace checks.
Existing Python 3.10 and 3.13 container environments each passed 229 tests with
17 optional Node/Tongs-dependent skips. The strict shell gate passed all nine
shells, 18 synthetic lifecycles, nine quoted-path controls and 108 generated
installer commands.

The [retained evidence](../../validation/evidence/tmux-fedora44.json) records
source/helper hashes and actual tmux 3.7c results: renamed sessions, renumbered
windows, swapped pane indexes, linked-window identity, moved-pane rediscovery,
stale rejection and two real PTY clients attached to separate sessions. Parent
terminal calls are instrumented; actual GUI activation is not claimed. All four
pane children and both clients exited. Real Pi 0.85.0 with Node.js 22.23.1 also
passed its synthetic-provider lifecycle journey and exact pane selection from
`%1` to `%0`, with partial focus for the detached session.

Independent review identified two corrected failures: validator cleanup could
stop after a shutdown-command error, and absent TMUX metadata could consult the
default server. Cleanup now uses bounded signals restricted to recorded process
birth identities, with three regression controls. A fifteen-case matrix proves
invalid captures cannot invoke a subprocess through any operational method.

An initial local container matrix attempt used private SELinux labels on a
shared read-only worktree and lacked usable VCS build metadata. It failed with
mount/build errors and the unchanged atomic-reader test on container overlay
storage. Rerunning unchanged tests in writable temporary copies with shared
read-only source labeling and explicit build version metadata passed both
versions. No test was weakened or gate waived.

Independent Sol high review approved the exact candidate with no remaining
mandatory findings, independently passing 66 focused tests and all 246 tests.
The reviewer's first native helper attempt failed to start tmux inside the
sandbox; its normal-host rerun passed. That startup failure is not acceptance.
The subsequent acceptance commit adds only this record and the evidence JSON;
product code, tests, validator and workflow behavior remain as reviewed.

This remains a bounded evolution of #32. Publication is a reviewed PR against
main; all six hosted checks are required and Andre retains the merge gate.

## Terminal focus 2 (finish #32, close #47)

Workflow: Agent SDLC 0.2.4 (see [the profile](../SDLC.md)). Andre approved the
design gate on 2026-10-09 for items T2, F3a, F3b, K1, K1b, P4, Z5, K7, S8 and
R9. W6 (WezTerm) was dropped: WezTerm is not validated and has no adapter.
Items were built in separate worktrees and merged into the local integration
branch `feat/terminal-focus-2`, which becomes one combined PR into `main`.
Base: `main` at `2e01b6f`. Before the items, the branch took the Ghostty qdbus
fast lane (`22235eb`), the Konsole verify-after-activation fixes (`9231dac`,
`dd29f6d`, `52b87ac`) and the SDLC 0.2.4 migration (`bfe20aa`).

### Live confirmation on 2026-10-09

Andre reported a Konsole cross-window false failure: with the TUI in one
Konsole window and the target tab in another, inactive window, the window
switched to the target tab but the TUI said "Focus failed". Konsole only
reports the selected tab once its window is active, so the selection readback
was stale. `9231dac` verifies selection again after KWin activation, and
`dd29f6d` ties the activation check to one unique window of the owning
Konsole process and cleans up KWin scripts on every path. After restarting
the TUI on the integration build, Andre confirmed live on KDE Plasma Wayland
with Konsole 26.08 that the same scenario now reports success. This is a
hands-on, manual observation; no JSON was recorded for it.

### Slice records

- **T2** (`0eb46ad`, integrated `e825bf8`): Terminator detection-only exactly
  as #47 specifies, reported by @EmilienM. Shared `_env` capture helpers, an
  opt-in test marker cleaner, a subprocess-free capture totality test over
  every registered adapter and a CLAUDE.md detection-order test. Evidence:
  mocked, plus live detection in the probe below.
- **F3a** (`fdc7f2a`, `8db535c`; `b32bae8`, `e9c152e`): the generic fallback
  no longer claims a target or raises any window. GNOME Terminal activates
  only the single X11 window owned by its `gnome-terminal-server` ancestor,
  with a bounded walk and `getactivewindow` readback. Windows Terminal became
  detection only because its owner window cannot be identified without Win32
  enumeration validated on Windows. Evidence: mocked.
- **K1** (`91ce25a`, `55f27ab`): partial and failed focus toasts name the
  failing step, Konsole hard failures raise short step details, and
  `deferred_selection_readback` marks Konsole as a parent whose selection is
  confirmed after activation. Evidence: mocked; the live behavior is the
  confirmation above.
- **F3b** (`82728df`, `fb8d32d`): one `parent.activate_parent` helper for tmux
  and zellij. Konsole parents are raised then verified; other selection-first
  parents still never raise after a failed selection. Zellij's GenericAPI
  fallback raise was removed. The tmux validator still passed with unchanged
  evidence keys. Evidence: mocked plus the instrumented tmux validator.
- **P4** (`44ddb23`, `b62b2f5`, `57e46a0`): the
  [probe record](../../validation/evidence/terminal-probe-fedora44.json) from
  disposable zellij 0.45.1, kitty 0.47.1, screen 5.0.1 and terminator 2.1.5
  instances proved selection readback for zellij, kitty and screen and gated
  their adapters. WezTerm is recorded as skipped. Evidence: live.
- **K1b** (`98faa27`, `fa9ab0f`): toast details keep both selection and
  activation parts visible, stale Konsole readback is worded as unconfirmed,
  and the Konsole test fakes are shared. Evidence: mocked.
- **Z5** (`7045cda`, `a306ade`, `eac0010`, `75bda5a`): exact zellij pane
  selection from the hook-time `ZELLIJ_PANE_ID` with `list-clients` readback.
  Records without a pane ID report selection unavailable. Evidence: live
  ([JSON](../../validation/evidence/zellij-fedora44.json)); activation
  unavailable.
- **K7** (`4c58e95`, `a29f332`, `44e459b`): Kitty selection over an opt-in
  unix remote-control socket with `ls` readback; activation is not claimed.
  Evidence: live ([JSON](../../validation/evidence/kitty-fedora44.json)).
- **S8** (`33ca29b`, `5f6c3e8`, `d819d2f`): P4 proved readback, so GNU screen
  shipped as an adapter rather than an assessment. Selection uses `-X select`
  with `-Q number` readback and a non-empty `-Q windows` guard, because with
  no attached display `select` is a silent no-op while `-Q number` still
  answers. Evidence: live ([JSON](../../validation/evidence/screen-fedora44.json)).
- **R9**: registers `KittyAPI` and `ScreenAPI` immediately before `GenericAPI`,
  so every earlier detection result is unchanged (screen keeps CTO option (a)).
  Adds `kitty` to `TERMINAL_PROCESS_NAMES`, because `KittyAPI.find_tab(pid, {})`
  truthfully returns None and activation is unsupported, so a tmux or zellij
  parent walk stops at Kitty instead of climbing to whatever launched it.
  Screen is never a parent stop, and `wezterm-gui` is not added without an
  adapter. Adds the `kty` and `scr` table labels and reconciles README,
  CLAUDE.md, the compatibility matrix and the validation guide with the
  evidence.
- **F10**: closes the independent adapter review notes. The zellij selection
  rule was tightened after the live evidence was recorded: a `list-clients`
  snapshot is taken before `focus-pane-id`, and selection succeeds only when a
  client that was elsewhere moves to the pane, or when every attached client
  already showed it (reported as "pane already focused"). An idle client
  already on the pane no longer counts. Evidence: mocked; an isolated
  `python validation/zellij.py --no-write` rerun passed on zellij 0.45.1 and
  the committed JSON was left as recorded. Kitty errors are classified on
  kitty's fixed message prefixes, connect failure first, so words in an
  echoed socket path no longer change the label, and the unavailable detail
  names the `unix:` listen_on requirement (the committed kitty JSON keeps the
  earlier wording it recorded). Screen capture stores `''` for an invalid
  `STY` or `WINDOW`, and the screen validator's two-display check now requires
  exactly one display showing the target and a consistent rule (the committed
  evidence already shows one display; not rerun). README rows now state the
  attached display or client requirement, the zellij socket directory match
  and the kitty `unix:` socket requirement.
- **F11**: closes the final whole-branch review notes (base `2e01b6f`, head
  `065d3a6`). The qdbus helpers and the KWin load, run and always-unload
  helper (unique plugin name, temp file removed on every path) moved to
  `terminal_apis/_qdbus.py`, shared by Konsole and Ghostty; Konsole behavior
  is unchanged. Ghostty no longer activates an arbitrary window: activation
  first requires the session to descend from the running Ghostty process, the
  KWin script activates only when exactly one window has that owner PID and is
  never a success on its own, and the xdotool path acts only on exactly one
  owned window and succeeds only when `getactivewindow` reads it back.
  Otherwise activation fails with a detail and Alt+N is not sent. GTK's hidden
  client-leader window no longer makes every GNOME Terminal server look like
  it owns two windows. Without a captured
  `KONSOLE_DBUS_SERVICE` (a tmux parent is called with `{}`), Konsole now picks
  the `org.kde.konsole*` service whose D-Bus owner is the nearest ancestor of
  the client (bounded, cycle-safe walk of at most 64 steps) and fails safely
  when none or several names match, instead of taking the first listed name.
  tmux `raise_window` raises a short reason when no client succeeds (no
  attached client shows the pane, no parent emulator, parent unsupported, or
  parent did not activate; list failures are named too). `claude-fleet focus`
  and MCP `fleet_focus` print the same step details as the toast for partial
  and failed results, and an operation never attempted because the backend
  does not support it renders as `unsupported`. The zellij pre-capture detail
  now tells the user to restart the agent session. Evidence: mocked only.
  Ghostty and GNOME Terminal activation are mocked only (Ghostty is not
  installed; no GNOME session was used); no live validator was run and no
  real qdbus, KWin or xdotool was called.
- **F11 correction round** (review of `2415d10` and `763077a`): the first F11
  window lookup searched `--onlyvisible`, but on X11 a minimized window or one
  on another desktop is unmapped, so a process with the session window hidden
  and an unrelated window visible looked like it owned exactly one window and
  the wrong one was activated (and Ghostty then sent Alt+N into it). Ghostty
  and GNOME Terminal now share `terminal_apis/_x11.py`: an unfiltered
  `xdotool search --pid`, at most 16 candidates, and only windows for which
  `xdotool get_desktop_for_window` succeeds (managed clients carry
  `_NET_WM_DESKTOP`; GTK's client leader does not), all within one lookup
  deadline. Exactly one managed window is required, which matches the KWin
  script's rule over `workspace.windowList()` (minimized windows included).
  Ghostty now finds its process by walking the session's own ancestry
  (bounded, cycle-safe, `comm`, executable or `argv[0]` named `ghostty`)
  instead of taking the first `pgrep -x ghostty` result. The KWin helper
  closes the raw temp descriptor if `os.fdopen` fails, and Ghostty records a
  KWin write `OSError` as a detail and still tries the X11 path. The Konsole
  `ambiguous-names` test now puts both names on the ancestor owner, so it
  reaches the ambiguity branch. `validation/tmux.py` expects the raised
  reasons ("parent terminal instrumented did not activate", "no attached tmux
  client shows the pane") and passed locally on tmux 3.7c with the same output
  keys as the committed evidence, which was left as recorded (it pins the
  hashes of the commit it tested). `validation/zellij.py` expects the new
  pre-capture detail. The committed zellij JSON was not rerun and still shows
  the old "record predates pane capture" text it recorded live: it is left
  untouched rather than edited to a value no run produced, and a unit test
  ties the validator's expectation to the adapter's current message.
  Evidence: mocked plus the local tmux validator; no real qdbus, KWin or
  xdotool was called.
- Acceptance follow-up: zellij now names a parent that did not activate
  ("parent terminal <name> did not activate"), and the remaining docs that
  described the removed Ghostty GTK D-Bus path were corrected. The zellij live
  validator was rerun on that commit (isolated sockets and PTYs, zellij
  0.45.1): it passed under the tightened selection rule, and the committed
  evidence now records the new pre-capture detail.

### Multi-client tmux routing note

With several attached tmux clients showing the target pane in different
emulator windows, tmux tries each client's parent in turn. R9 kept trying the
next client after a delegated parent (Konsole, Ghostty, GNOME Terminal) raised
its window but reported failure, so more than one window could be raised.
[#51](https://github.com/andre-motta/claude-fleet-monitor/issues/51) fixed
this:

- `TerminalAPI.raise_requested` is set by an adapter when it actually sends a
  raise request: Konsole after its KWin activation script ran, Ghostty after
  its KWin owner-pid script ran or before `xdotool windowactivate`, GNOME
  Terminal before `xdotool windowactivate`. `parent.activate_parent` resets
  it before delegating. For strict parents the call to `raise_window` counts.
- `parent.activate_parent` returns a `ParentActivation`: `activated` (a
  window may have been raised: activation succeeded or a request was sent),
  `confirmed` (the parent's full protocol succeeded) and a bounded `detail`
  that carries the parent's own reason.
- tmux and zellij stop at the first activated parent. When it is not
  confirmed they report the detail, for example `parent terminal konsole may
  have raised its window but could not confirm it (...)`, never success.
  Parents that fail before any request (no unique window, unreadable D-Bus
  owner, no tab) still let tmux try the next client.
- The strict order is unchanged: a failed parent selection never raises.
- Konsole's standalone `focus_result` reports exactly what it did before.

Residual: a KWin `Script.run` call that fails or times out is treated as no
request (Konsole and Ghostty set the flag only after it returns), so in that rare
case a second client can still be tried.

### Zellij parent activation and socket dirs

[#50](https://github.com/andre-motta/claude-fleet-monitor/issues/50), after a
live probe on zellij 0.45.1 (Linux):

- The agent's ancestry ends at the daemonized server, whose argv is
  `zellij --server <socket dir>/contract_version_N/<session>`. Every zellij
  CLI call now sets `ZELLIJ_SOCKET_DIR`: derived from that argv (only when the
  parent directory starts with `contract_version_`), else the absolute
  `ZELLIJ_SOCKET_DIR` captured at hook time (env-only), else zellij's own
  default. "There is no active session" names the socket dir searched.
- `list-clients` IDs are reused lowest-free and carry no PID, so the client is
  found through sockets instead: a `sock_diag` netlink dump maps the server's
  accepted sockets to peer inodes, and `/proc/<pid>/fd` links of same-UID
  `zellij` processes map them to PIDs (`terminal_apis/_unix_peers.py`, stdlib
  only, never raising, Linux only, about 5-10 ms, one 2 s total deadline,
  keeping only the server's own inodes). The dump is not an atomic snapshot:
  under heavy socket churn it can miss entries, which only lowers the peer
  count, so the result is a refusal or the one real client, never a wrong one.
- Activation is claimed only when `list-clients` shows one client, the
  server's socket name matches the captured session (not renamed) and exactly
  one interactive peer is connected: argv parsed past global options to a
  plain `zellij` or `attach`/`a` subcommand, with a controlling tty.
  `action`/`ac` peers are transient and ignored; any other peer (`web`,
  `watch`/`w`, `pipe`, `subscribe`, `run`, `edit`, `plugin`, unknown shapes)
  is refused, as are several clients or a mismatch. The parent is then never
  called. The client's emulator comes
  from its own ancestry and is raised through `parent.activate_parent`; its
  start time is checked before and after so a reused PID is never trusted.
- Live: `validation/zellij.py` maps the PTY client, routes to an instrumented
  parent, refuses two clients and a watcher, and selects with the monitor's
  own `ZELLIJ_SOCKET_DIR` unset through both the captured and the derived dir
  ([JSON](../../validation/evidence/zellij-fedora44.json)). No KWin, qdbus or
  xdotool call was made; real GUI activation through the client's emulator is
  covered by the existing parent adapters and still needs a hands-on check.

### Kitty window activation (#49)

[#49](https://github.com/andre-motta/claude-fleet-monitor/issues/49) replaces
the earlier CTO decision that left kitty window raise unverified. Live probes
on kitty 0.47.1 under KWin (Plasma Wayland) showed: `KITTY_PID` in every
window equals the kitty GUI pid (also with `--single-instance` handoff and
`launch --type=os-window`); KWin lists each OS window of that process with
the same pid, so two OS windows are indistinguishable; after a KWin
activation `kitten @ ls` reports the target OS window `is_focused` on the
first poll, also for minimized targets; a refused focus leaves it false; and
a `--start-as=hidden` kitty can report `is_focused` true with no window.

- `terminal_apis/_kwin.py` is extracted from Konsole: pid filter, optional
  normal-window and caption-title filters, exactly one match, un-minimize and
  activate, values embedded as JSON. Konsole uses it with its caption rule
  and without the normal-window filter, so its script and standalone
  `focus_result` behave as before (its tests are unchanged).
- KWin scripts have no return channel. A reporting script calls
  `unloadScript` on its own plugin only when `workspace.activeWindow` is the
  matched window right after the assignment (KWin accepted it); the caller
  polls `isScriptLoaded` for up to 0.5 s before its own unload. False means
  KWin found no single window, refused it, or could not report it, and
  activation is not claimed. Konsole does not use report mode, so its script
  is unchanged.
- Kitty captures `KITTY_PID` at hook time. At focus time activation is
  unavailable, with the reason, unless `KITTY_PID` is captured, is a `kitty`
  ancestor of the session pid (bounded, cycle-safe walk), qdbus and KWin are
  on the session bus, and `kitten @ ls` lists exactly one OS window holding
  `KITTY_WINDOW_ID` whose child process descends from `KITTY_PID` (which
  refuses a nested kitty that inherited an outer `KITTY_LISTEN_ON`).
- Placeholders in the KWin script are filled in one pass, so a title holding
  a placeholder name (for example a program-set tab title) stays literal data.
  This also fixes the same exposure in Konsole's caption script.
- Verified on Plasma Wayland only; Plasma X11 and XWayland kitty are not
  verified.
- Selection uses the same ownership rule and refuses, before any
  `focus-window`, unless `KITTY_PID` is captured, is an ancestor of the
  session (checked first, so leaked variables never send `ls` to a foreign
  kitty) and owns the child process of the window the socket lists. Records
  without `KITTY_PID` are refused with "restart the agent session to enable
  kitty focus" rather than trusted, because without
  it an inherited outer socket could select a same-numbered window in the
  wrong kitty.
- Order: selection (`focus-window` plus `is_active` readback) then
  activation. Activation re-checks the single OS window, runs the reporting
  script, sets `raise_requested`, and succeeds only if the script confirmed
  and kitty reports the OS window `is_focused` within 1 s and again 0.2 s
  later; a focus that drops is polled until the deadline and otherwise fails
  with "kitty OS window lost focus after activation". Requiring the KWin
  confirmation covers the hidden-window case where `is_focused` is already
  true.
- Kitty stays an unsupported nested parent (`parent_activation_supported =
  False`): tmux and zellij route with an empty env, which has no socket or
  `KITTY_PID`.
- Live: `validation/kitty.py` activates two probe instances alternately and
  records refusals and the hidden case
  ([JSON](../../validation/evidence/kitty-fedora44.json)).
- Failed live run, not committed as evidence: on `80f0ca8` (before the
  rebase onto #59 to #61; now `c699dbe`) the first
  alternation reported A activated (kitty read `is_focused` true), but the
  validator's own readback about 0.1 s later showed neither probe focused.
  Suspected cause: a late map or minimize of probe B, started just before,
  took focus after the raise. The validator now waits until the probes'
  focus state is unchanged for 0.5 s (at most 5 s) before alternating, and
  activation requires a stable second readback.
- Two more failed live runs, after that hardening (pre-rebase `7488b3c`, and
  `8ed4ffc` on current main): in each, one or two of the six alternations
  failed honestly. KWin accepted the activation (the script confirmed), but
  kitty reported "lost focus after activation" or no focus within 1 s, and
  the validator then saw neither probe focused, so a non-probe window had
  focus. Probes had settled first. No run claimed a raise that the readback
  did not show. Suspected cause: concurrent desktop activity on the shared
  validation desktop; not proven, because identifying the active non-probe
  window would mean reading it through KWin. The next run on `8ed4ffc`
  passed and is the committed evidence. Live activation is therefore
  sensitive to other focus changes while it runs.
- Upgrade note: sessions recorded before this change have no `KITTY_PID` and
  lose kitty selection (and activation) until the agent session is
  restarted; kitty versions that do not export `KITTY_PID` lose selection.

### R9 combined local acceptance

Run on 2026-10-09 in the R9 worktree on the integrated tree plus the R9
change, Fedora 44 KDE Plasma Wayland:

- Full pytest: 648 passed, 4 skipped (optional Tongs not installed) on Python
  3.10.21, 3.12.14 and 3.13.15 through `uv run --no-project --python 3.X`, and
  on the worktree's Python 3.14.7.
- Marker-leak run (all markers from the
  [command](../../validation/README.md#combined-terminal-focus-acceptance) set):
  314 passed over the six terminal test modules; the same modules passed
  without the markers; the full suite also passed with the markers set.
- `python validation/tui.py`: pass.
- `python validation/tmux.py`: pass, tmux 3.7c, two clients and four pane
  children exited; same result keys as the committed evidence.
- `python validation/zellij.py --no-write`: pass, eight tracked processes, no
  survivors, user config unchanged.
- `python validation/screen.py`: pass, verdict adapter, eleven tracked
  processes, no survivors.
- `validation/kitty.py` and `validation/konsole.py` were not rerun because
  they open GUI windows on Andre's desktop; their committed evidence stands.
- No change to `pyproject.toml` dependencies; no U+2014 in changed files;
  `git diff --check` clean.

### Pending and unmet

- Hosted gates (workflow lint, Python matrix with the headless TUI journey,
  strict Podman shell validation, real Pi lifecycle and tmux validation) have
  not run: nothing is published yet. They are required on the combined PR.
  actionlint is not installed locally; no workflow file changed.
- Andre at the desktop: tmux inside a background Konsole window, focused from
  the TUI, should report complete (needs K1 and F3b together); this is the
  post-K1 hands-on re-run.
- Andre at the desktop: a fresh agent session in each installed terminal
  should show its label (`KDE`, `tmx`, `zel`, `kty`, `scr`, `trm`) and the
  focus result listed in the README table. Sessions recorded before the
  upgrade keep their old label and environment.

### Follow-ups

- Windows Terminal: Win32 owner-window activation, which needs validation on a
  Windows host.
- WezTerm GUI activation through the shared KWin helper in
  `terminal_apis/_kwin.py` (Kitty uses it since #49).
- Kitty as a nested parent (tmux or zellij inside kitty): would need the
  client's kitty socket and `KITTY_PID`, which parent routing does not have.
- Zellij parent activation off Linux (no client PID route) and with several
  attached clients (no way to tell which window shows the pane).
- Version floors: only one version of kitty and screen was validated;
  adapters gate on behavior, not on a version number. zellij: see #52 below.
- Leaked-marker misclassification on macOS and Windows (env-only detection).
  Linux uses the #52 ancestry walk below.

## #52 follow-up: leaked markers and version floors

Issue: [#52](https://github.com/andre-motta/claude-fleet-monitor/issues/52),
branch `fix/52-ancestry-floors`, rebased onto `main` at `f20e70f`.

### Ancestry-based labels (Linux)

Andre approved on 2026-10-10 a change to the env-only hook rule: on Linux,
terminal capture may walk the hook's process ancestry reading only
`/proc/<pid>/stat`. `terminal_apis/_ancestry.py` parses comm (between the
first `(` and the last `)`) and ppid, starting at the hook's parent, for at
most 64 steps, stopping on a repeated PID, PID 0, an unreadable or malformed
entry or any exception. comm names map through `tmux.TERMINAL_PROCESS_NAMES`
truncated to the kernel's 15 characters (`gnome-terminal-server` becomes
`gnome-terminal-`) plus `tmux` / `tmux:*`, `zellij`, `screen` and `SCREEN`.
The nearest match wins over env detection and its adapter's env-only
`capture_env()` records whatever markers are present; no match or any failure
keeps the env order. `/proc/<pid>/environ` and `cmdline` are never read, and
non-Linux platforms are unchanged.

Evidence:

- mocked: a fake `/proc` seam covers Kitty from Konsole, screen inside
  Konsole, tmux inside Konsole, Konsole with a leaked `TMUX`, Terminator from a
  Terminator shell, Kitty with a leaked `TERMINATOR_UUID`, zellij inside tmux,
  the truncated GNOME comm, no known ancestor, unreadable `/proc`, cycles,
  self-parenting, the 64-step bound, malformed stat lines, reader exceptions
  and non-Linux platforms; plus one hook-level record. An autouse fixture in
  `tests/conftest.py` makes the real `/proc` unreadable for every test, so
  results do not depend on the terminal running pytest.
- synthetic live (real kernel comm, wrapper scripts named after terminals, an
  isolated `FLEET_DIR`): under Konsole on Fedora 44 the hook labelled
  `konsole`; wrappers named `kitty`, `zellij` and `gnome-terminal-server`
  produced `kitty`, `zellij` and `gnome` despite the leaked `KONSOLE_*`; a
  `wezterm-gui` wrapper stayed `konsole` (documented WezTerm limit).
- cost: the real walk took about 21 us per call for a five-process chain,
  against roughly 20 ms of hook start-up.

### zellij version floor

Live, isolated runs of the unchanged `validation/zellij.py` on 2026-10-10
(recorded at `tested_commit`, the ancestry commit rebased onto `f20e70f`; two
earlier rounds before and after that rebase gave identical outcomes) against upstream x86_64 musl release binaries (no-web build where
published), each extracted into its own new scratch directory and used only
through a temporary `PATH` prefix. Tarballs matched the GitHub asset digest
where the API publishes one (0.43.1 and later) and every binary matched its
release `.sha256sum`. Every run used private sockets, config, cache, data and
PTYs, left no survivors and no user config or cache change. Evidence:
[floor JSON](../../validation/evidence/zellij-version-floor-fedora44.json).

| zellij | `focus-pane-id` | Validator | Failing step | False success |
| --- | --- | --- | --- | --- |
| 0.45.1, 0.45.0, 0.44.3, 0.44.2 | yes | pass | none | no |
| 0.44.1 | yes | fail (2 of 2 runs, every round) | two-client check; all 4 single-client selections confirmed | no |
| 0.44.0 | no | fail | warmup keystroke (adapter already reported "could not focus pane") | no |
| 0.43.1, 0.42.2, 0.41.2 | no | fail | `list-panes` fixture check; with it substituted, warmup keystroke after the same adapter failure | no |
| 0.40.1, 0.40.0 | no | fail | fixture session not ready (not diagnosed); no adapter call | no |

Minimum validated version: 0.44.2. On 0.44.1 the second client's first
keystroke reached no pane, so `focus-pane-id` moved the first client; the
adapter's success claim was still true (that client's keystrokes reached the
target), only the validator's most-recent-input expectation failed. The host's
own zellij 0.45.1 is byte-identical to the upstream build and passed as a
control. The adapter was not changed: it gates on behavior and no version gave
a false success.

## macOS AppleScript hardening (#55)

Andre approved hardening the iTerm2 and Terminal.app adapters on
2026-10-10 without a Mac: all evidence is mocked or inspected, and the README
keeps both rows unvalidated on macOS.

- Injection: both adapters interpolated the captured session ID into
  AppleScript source, and fleet records are writable by any same-user process.
  Identifiers are now validated at capture and again before use, and are
  passed to `osascript` only as `on run argv` arguments
  (`terminal_apis/_applescript.py`), so data is never compiled as code.
- iTerm2 target: `ITERM_SESSION_ID` is `w<N>t<N>p<N>:<guid>` and the guid is
  the session's AppleScript `unique ID` (inspected in iTerm2's
  `PTYSession.sessionId`, `iTerm2.sdef` and `revealSessionID:`). The old code
  compared the whole value against `unique ID` and could never match.
- iTerm2 leaked markers: `ITERM_SESSION_ID` is inherited by anything started
  from an iTerm2 shell (VS Code, screen), so a session matches only when its
  `unique ID` and its `tty` both equal the agent's; the tty comes from `ps` at
  focus time and an unreadable tty refuses the target. A record without the
  variable (the tmux parent lookup) matches by tty alone and requires exactly
  one such session, which makes iTerm2 reachable as a tmux parent.
- Terminal.app target: `TERM_SESSION_ID` is a restoration UUID with no
  AppleScript counterpart, and the old fallback matched the agent pid against
  `tty of t`. The target is now the agent's controlling tty, read with
  `ps -o tty= -p <pid>` at focus time (the hook stays env-only), compared
  exactly with `tty of t`. No tty means no target. The same lookup lets
  Terminal.app act as a tmux parent through the tmux client's tty.
- Readback: selection never reorders windows and is claimed only when a
  separate query reports the target as the current session (iTerm2) or
  selected tab (Terminal) of the app's front window; for a background window
  that is confirmed after activation (`deferred_selection_readback`, which
  also routes tmux parents through `focus_result`). Activation un-minimizes
  and fronts the target's window, and is claimed only when the app is
  frontmost and its front window, not minimized, holds the target (bounded
  polling). A raise request that was sent, or timed out, marks
  `raise_requested` for nested routing.
- Not verified: the AppleScript itself has never run. Known unknowns are how
  `contents of` loop references behave as `select` targets, whether iTerm2's
  `tty of s` uses the `/dev/ttysNNN` form compared here, the exact
  `ps -o tty=` spelling on macOS (`ttys003`, `s003` and `/dev/ttys003` are
  accepted) and Automation permission prompts (error -1743 is reported as a
  denied permission).
