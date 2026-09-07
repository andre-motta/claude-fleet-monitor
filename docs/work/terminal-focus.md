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
