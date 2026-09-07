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
`feat/konsole-qdbus`, with independent Sol high review. The established child-PR
and final-main-PR workflow continues on this feature branch. The earlier
`feat/harnesses-desktop` branch was delivered and cleaned up. Reviewed local
commits are signed off, and Astra verifies all six hosted checks before child
integration. Final main merge and another release remain CTO-gated.

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
