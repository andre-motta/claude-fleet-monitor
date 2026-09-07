# Optional Fleet desktop interface

Status: **planned feature**, not implemented or published as an issue.
Workflow: Agent SDLC 0.1.0, source
`4e851d1b8a903aa8bebceea078860a21152ee8e8`; see [profile](../SDLC.md) and
[initiative](harnesses-desktop.md). Design approval is pending.

## Source and proposed scope

The user requested this feature after pointing to Tongs' `docs/work/desktop.md`.
The inspected local Tongs checkout was at
`c8ead224a92d33486c9d97aa27568b8136cb7cb0`. Its desktop design is still planned.
This is a Fleet-specific feature record; it does not adopt or modify Tongs policy.

The user confirmed on 2026-09-07: Fleet is an opt-in Tongs desktop plugin first.
A standalone Fleet desktop application is outside this initial scope. Preserve
the standalone Fleet TUI and existing Tongs terminal plugin. Share non-Textual
session reading, normalization, filtering and focus services across consumers.

Tongs plans a React/TypeScript web UI and will compare Electron with a
Python-hosted webview before choosing its shell. Fleet must wait for the approved,
versioned desktop plugin contract rather than choose a competing shell or invent
a bridge independently. Tongs owns the shell, plugin module/API versions,
frontend loading, lifecycle and compatibility policy. Fleet owns its module,
assets and backend operations within that contract. The proposed packaging shape
is conditional on the host contract; resolve the precise asset format and
distribution mechanism before implementation.

## User journey and acceptance

- Open Fleet from Tongs desktop navigation or a command, see agents and current
  session status, search/filter/sort and inspect the selected session.
- Focus a selected terminal session and see whether exact focus succeeded;
  show unsupported, unavailable or partial capabilities honestly.
- Reuse the same session identities and status semantics as CLI/TUI/MCP.
  A failed refresh leaves a clear stale/error indication and can recover.
- Propose bundled compiled frontend assets in the Fleet Python package, subject
  to the host contract; ordinary users
  need no Node/npm or Fleet frontend rebuild. Keep desktop runtime dependencies
  optional and ordinary Fleet/Tongs TUI startup free of desktop imports.
- Exercise plugin enabled/disabled states, absent or incompatible assets/API,
  backend failure, lifecycle shutdown and an independently installed package.
  Make Fleet plugin documentation accessible from the desktop UI.
- Match Tongs' planned Linux x86_64 targets: Fedora KDE and Ubuntu GNOME,
  Wayland and X11. These are future desktop acceptance targets, not current
  evidence or a reduction in existing terminal cross-platform support.
- Demonstrate actual desktop launch, status refresh and terminal focus on each
  claimed target, with versions and inspectable interaction evidence. Mocks
  alone cannot establish window activation.

Desktop bridge methods must be narrow (session list/detail and validated focus
selection), not arbitrary command execution. Keep frontend code from reading
arbitrary local files. Installed Python plugins remain trusted code; a facade
is not a sandbox. Detailed protocol/security choices await Tongs' contract.

## Dependencies and next action

Work item D1 in the initiative follows the host contract decision and common
Fleet service contracts. Tongs' side-by-side diff and draft-review work are host
features, not Fleet scope. Jira remains Tongs' stretch goal. No Tongs edits,
issues, prototype work or publication are authorized by this Fleet planning task.

Save this feature now; finalize its UI/contract after the host design is approved.
Do not block Pi support on the desktop shell decision.
