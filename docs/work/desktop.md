# Optional Fleet desktop interface

Status: **tracked feature, blocked on the production Tongs host contract**.
Workflow: Agent SDLC 0.1.0, source
`4e851d1b8a903aa8bebceea078860a21152ee8e8`; see [profile](../SDLC.md) and
[initiative](harnesses-desktop.md). The staged plugin-first design is approved;
the concrete host API and Fleet UI implementation retain their design gate.
Tracker: [feature #21](https://github.com/andre-motta/claude-fleet-monitor/issues/21)
and [implementation #30](https://github.com/andre-motta/claude-fleet-monitor/issues/30).

## Source and proposed scope

The user requested this feature after pointing to Tongs' `docs/work/desktop.md`.
The inspected local Tongs checkout was at
`c8ead224a92d33486c9d97aa27568b8136cb7cb0` during initial planning. The later
[Tongs host issue #17](https://github.com/andre-motta/tongs/issues/17) records
Electron selection and production contract work on `feat/desktop-app`.
This is a Fleet-specific feature record; it does not adopt or modify Tongs policy.

The user confirmed on 2026-09-07: Fleet is an opt-in Tongs desktop plugin first.
A standalone Fleet desktop application is outside this initial scope. Preserve
the standalone Fleet TUI and existing Tongs terminal plugin. Share non-Textual
session reading, normalization, filtering and focus services across consumers.

Tongs has selected Electron with a React/TypeScript web UI. Fleet waits for the
approved, versioned desktop plugin contract. Tongs owns the shell, plugin module/API versions,
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
- Follow the host's initial Fedora 44 KDE x86_64 target and record the actual
  Wayland or XWayland backend. Tongs deferred other environments; Fleet does not
  expand host support through this plugin. Existing terminal cross-platform
  behavior remains a separate concern.
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
features, not Fleet scope. Jira remains Tongs' stretch goal.

Andre authorized cross-repository issue dependency updates on 2026-09-07.
Tongs #17 now natively blocks Fleet #30 and records the host prerequisites:
versioned module/backend APIs, packaged frontend assets, compatibility/lifecycle
fixtures and an accepted host revision. Its prototype contract is not a production
SDK. Tongs code changes remain outside this Fleet assignment.

Save this feature now; finalize its UI/contract after the host design is approved.
Pi support proceeds independently of the desktop host contract.
