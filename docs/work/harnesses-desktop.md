# Harness coverage and desktop initiative

Status: **staged design approved; local engineering in progress**. Andre approved
the design and requested GitHub issue publication/maintenance on 2026-09-07.
Code branch/PR publication, merging and releases remain separately gated.
Baseline: Agent SDLC 0.1.0, source
`4e851d1b8a903aa8bebceea078860a21152ee8e8`; [project profile](../SDLC.md).
Repository baseline: `e651c81751c90e5fb6bfb70c8cc0ff17de364953` on `main`.
Discovery date: 2026-09-07.

## Outcomes and confirmed scope

1. Monitor Pi coding agent alongside existing Claude Code and Codex sessions,
   and provide a documented adapter path for other harnesses.
2. Deliver Fleet as an optional **Tongs desktop plugin first**, confirmed by
   Andre during planning. See the saved [desktop feature](desktop.md).
3. Investigate focusing an exact conversation in the **official ChatGPT Linux
   desktop client**, confirmed by Andre. Terminal focus and desktop conversation
   focus are different capabilities; neither proves automatic status discovery.

Keep the Python core lightweight, the current CLI/package names, existing
FLEET_DIR default and TUI/terminal behavior. No daemon, database, transcript
collection, arbitrary command bridge or standalone desktop shell is proposed.
Additional named harnesses follow evidence and prioritization, not a promise
that any process with an agent-like name is fully supported.

## Current tracker and implementation findings

Authenticated GitHub discovery returned **0 open issues and 0 open PRs** for
[the repository](https://github.com/andre-motta/claude-fleet-monitor).
`main` is the public default branch. No existing open work can be reused at this
snapshot. The approved work breakdown is now published below; all issues remain
open until delivered to the upstream target.

| Finding | Evidence and consequence | Proposed item |
| --- | --- | --- |
| Fresh install breaks MCP startup | `mcp[cli]>=1.0.0` resolves to 2.1.1; importing `mcp_server.py` fails at `mcp.server.fastmcp`. Existing pytest suite does not cover this startup | B0 |
| Harness support is hard-coded | hook allowlist, CLI events/install and discovery enumerate Claude/Codex | H1, H2 |
| Focus recovery assumes Claude/Linux | `focus.py:get_pid` uses `pgrep claude` and `/proc`; session lookup also duplicates fleet I/O | H1 |
| Discovery dedup uses agent + cwd | Multiple sessions of the same harness in one directory can suppress process records too broadly | H1 |
| Fleet plugin is Textual-only | `tongs_plugin.py` registers screens and TUI lifecycle; host desktop contract still planned | D1 |
| Documentation drift | README terminal matrix/architecture omitted existing Ghostty; CONTRIBUTING called Textual curses; corrected with this adoption | Adoption |

## Proposed architecture and interface baseline

### Harness ingestion and identity

Use a small built-in adapter registry first, not an arbitrary plugin loader.
Each adapter declares a stable harness ID, process detection evidence, supported
status events and integration capabilities. Keep process enumeration, PID
validation and session store operations in discovery; adapter detection consumes
normalized process evidence. Keep terminal implementations in terminal_apis.
The CLI owns explicit installation/removal and must preserve unrelated settings.

Normalize events into a shared record with harness ID, native session ID,
instance identity, status, timestamp, optional PID/cwd, and optional terminal or
desktop focus target. Separate stable conversation identity from a running
instance, since one session can be resumed and one process can switch sessions.
Use a versioned schema and a safe canonical storage key derived from harness plus
instance/session identity. Never treat raw session IDs as paths. Define collision,
ordering, atomic-write and stale-instance rules before H2 dispatch. H1 acceptance
includes hostile IDs/path traversal, symlink escape, malformed/oversized payloads,
replayed/out-of-order/concurrent events, denied writes and atomic visibility.
Use finite payload/field bounds and confine writes to the validated fleet store.

Read legacy Claude/Codex records unchanged, including the current default agent
when absent. Keep existing filenames readable during migration and deduplicate
legacy/new records by proven identity. No mass deletion or settings reset. Do not
invent a PID for desktop-only conversations or map all unknown harnesses to Claude.
Do not treat a process match as evidence of running/idle/waiting lifecycle state.

Keep status normalization pure and dependency-light; hooks must not import UI,
MCP or desktop runtimes or perform network calls. Unknown event types are ignored
without corrupting known state. Adapters declare limitations explicitly. Public
consumer fields are additive; retain old CLI and MCP contracts during migration.

### Focus and shared services

Resolve sessions by canonical identity, with existing query conveniences retained
and ambiguous matches reported rather than guessed. Focus dispatch reads a typed
target: terminal, desktop conversation, or unavailable. Terminal targets delegate
to the existing terminal APIs; desktop backends belong in a separate optional
module, not terminal-specific branches in focus.py. This module boundary is a
approved design boundary; its concrete ChatGPT mechanism still requires C1 acceptance.

Return a structured outcome distinguishing exact target focused, window raised,
unavailable and failed, with a reason. A launched URL or successful process exit
alone does not prove that the intended conversation is visible. Preserve the
legacy boolean interface through a compatibility wrapper and expose richer
results additively. The decision about partial-focus CLI exit semantics must be
settled and tested in H1 before downstream consumers depend on it.

Session list/detail/filter/attention and focus services stay independent of
Textual so the future Tongs module shares behavior with CLI/TUI/MCP. No desktop
bridge format is frozen before Tongs approves its versioned plugin contract.

### Pi and extensibility

Pi refers to the coding agent now maintained in
[earendil-works/pi](https://github.com/earendil-works/pi), formerly badlogic/pi-mono.
Use its supported
extension lifecycle to emit normalized events, rather than rely on executable
name alone. A tiny optional dependency-free JavaScript bridge is the proposed exception to the
Python-only convention; the core and existing consumers remain Python. Its
installation, ownership, update and uninstall rules need explicit coverage.
The design approval is recorded in AGENTS/CLAUDE/CONTRIBUTING: a small optional
dependency-free JavaScript bridge is allowed, with the core remaining Python.

Sol's feasibility investigation identified these lifecycle contracts:

| Pi event / context | Fleet meaning |
| --- | --- |
| `session_start` | New or switched session started; reconcile the previous session in the same process |
| `before_agent_start` | Running |
| `tool_execution_start` | Running with current tool detail |
| `agent_settled` | Idle after retries, compaction and queued follow-up work settle; `agent_end` alone is too early |
| `ui_prompt_start` / `ui_prompt_end` | Waiting for UI input / restore the prior execution state; available from Pi 0.84.4 |
| `agent_end` assistant stop reason/error, retained until settled | Preserve an actual terminal failure rather than overwrite it with idle; an aborted turn returns idle with an aborted detail |
| `session_shutdown` | Ended |
| `ctx.sessionManager.getSessionId()`, `ctx.cwd`, `process.pid` | Native session ID, directory and exact emitting process; avoid guessing via substring matching |

Propose Pi >=0.84.4 for complete UI-wait event coverage, with explicit version
checks and a documented unsupported/limited mode for older versions. Pi can emit
parallel tool events: serialize bridge delivery and define update ordering so an
older event cannot overwrite newer status. Prompt nesting and restoring prior
state need fixtures and live evidence, not an unconditional idle/running flip.

Pi supports installing a packaged local extension with `pi install <path>` and
removing it with `pi remove <same-path>`; local extension paths are referenced in
settings without copying. H2 must make the Python package's extension location
stable or reconcile old references during upgrades/virtualenv changes. Never
remove user-owned extensions. The optional extension must fail open when Fleet
is missing and keep write operations confined to FLEET_DIR via the Fleet emitter.
Retain only minimal stop/error metadata, not assistant message bodies.
Pi has no built-in MCP support; do not equate lifecycle integration with native
MCP registration or introduce an MCP dependency into Pi.

Acceptance includes start, active work, tools, prompt waits, settled turns,
failures, new/switch/resume, reload, clean shutdown and abrupt process death.
Pin the tested Pi version and fixtures before H2 starts; the event contract and
supported version range are part of the approved baseline.

Primary references verified by Sol on 2026-09-07:
[project move](https://pi.dev/news/2026/5/7/pi-has-a-new-home),
[extension events](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md#events),
[settled events](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md#agent_start--agent_end--agent_settled),
[UI prompt events](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md#ui_prompt_start--ui_prompt_end),
[local extension packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md#local-paths).
The inspected upstream main package declares 0.85.1 and the local CLI reports
0.85.0; source inspection is not a live Fleet/Pi integration demonstration.

The registry and an adapter-author contract form the path to further harnesses.
H3 will assess candidate adapters (Gemini CLI, OpenCode, Qwen Code and GitHub
Copilot CLI) against official lifecycle interfaces, identity, packaging, OS behavior, hooks or
extensions, and capability gaps. Sol found documented extension surfaces in
[Gemini CLI](https://geminicli.com/docs/hooks/reference/),
[OpenCode](https://opencode.ai/docs/plugins/),
[Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/) and
[GitHub Copilot CLI](https://docs.github.com/en/copilot/reference/hooks-reference).
These candidates are a research shortlist, not verified Fleet support or an agreed implementation order. Ask the CTO to prioritize
concrete adapters after the matrix; the generic contract itself is in scope.

## ChatGPT Linux feasibility feature

Primary documentation inspected:
[desktop app](https://learn.chatgpt.com/docs/app) and
[projects and chats](https://learn.chatgpt.com/docs/projects).
They describe the official Linux client and in-app chat navigation. The inspected
pages do not establish a public external API for selecting a specific ChatGPT
conversation. This is an unresolved capability, not evidence of impossibility.

Read-only local inspection found that the installed Linux desktop launcher accepts
URLs and registers a `codex:` scheme handler. This establishes URL dispatch
registration only. It does not establish accepted route shapes, ordinary ChatGPT
chat routing, stable IDs, or Wayland window activation. Host-provided task
navigation tools are session capabilities, not a distributable Fleet API.

C1 should compare documented public routes/CLI integration first, then a scoped
opt-in accessibility approach only if necessary. Do not assume private app
storage or undocumented IPC is a stable public contract. Identify conversation
ID acquisition and lifecycle separately from focus, using explicit user-selected
conversation references if automatic discovery has no supported source.

On the actual official Linux app, record version, distro, desktop/compositor and
Wayland/X11; prove exact conversation selection and correct-window activation
with at least two chats, including duplicate titles, an already-open and a
minimized window, stale IDs and unavailable app. Record limitations separately
for plain ChatGPT chats, Work and Codex tasks. Never claim ChatGPT conversation
support solely from successful Codex task navigation. Do not collect conversation
bodies or publish identifying screenshots as evidence.

Decision owner: Astra recommends; Andre accepts the outcome. If exact focus is
unavailable, return an explicit capability result and a separately labeled
window-only fallback for approval. C2 cannot be dispatched until the mechanism
and acceptance scope are approved. Other harness work proceeds independently.

## Draft work graph and issue package

The approved package is published to GitHub. Feature parents are
[H #20](https://github.com/andre-motta/claude-fleet-monitor/issues/20),
[D #21](https://github.com/andre-motta/claude-fleet-monitor/issues/21),
[C #22](https://github.com/andre-motta/claude-fleet-monitor/issues/22) and
[S #23](https://github.com/andre-motta/claude-fleet-monitor/issues/23).
B0 is an independent baseline bug. B0, C1 and S1 are assigned; other items remain
planned until their dependency revisions and specified gates are satisfied.

| Item / draft title | Owner runtime | Dependencies | Owned areas and outcome | Acceptance |
| --- | --- | --- | --- | --- |
| [B0 #24](https://github.com/andre-motta/claude-fleet-monitor/issues/24): Restore fresh-install MCP startup | Luna xhigh, Sol review | Design gate | Dependency compatibility and new MCP startup regression check; bounded preferred solution is constrain to the compatible major, with migration as a separately assessed alternative | Fresh install, import and MCP tool-list/status smoke with synthetic fleet data; existing suite; available local Python versions plus post-publication CI |
| [H1 #25](https://github.com/andre-motta/claude-fleet-monitor/issues/25): Define extensible harness and focus contracts | Sol high, separate Sol review | Design gate; B0 integrated before combined acceptance | models, registry, discovery, focus compatibility and core consumer boundaries; migrate Claude/Codex without feature loss | Old/new records, identity collisions, multiple same-cwd sessions, stale PID, unknown agents, ambiguous lookup and platform mocks; regression suite |
| [H2 #26](https://github.com/andre-motta/claude-fleet-monitor/issues/26): Add Pi lifecycle integration | Sol high, separate Sol review; Luna fixtures after contract | H1 integrated and verified; Pi payload/lifecycle contract settled | Pi adapter, optional extension assets, CLI install/uninstall and packaging | Synthetic event suite plus live Pi start/turn/tool/error/switch/shutdown, idempotent install and safe uninstall, terminal focus on claimed platforms |
| [H3 #27](https://github.com/andre-motta/claude-fleet-monitor/issues/27): Document harness capabilities and adapter guide | Luna xhigh, Sol review | H2 integrated and verified | Adapter guide, capability matrix, corrected support claims and candidate assessment | Guide validated against Claude/Codex/Pi, truthful partial capabilities and tested package commands; deliver candidate matrix |
| [C1 #28](https://github.com/andre-motta/claude-fleet-monitor/issues/28): Prove ChatGPT Linux conversation focusing | Sol high, separate Sol review | Approval of bounded investigation | Isolated prototype/evidence only, no production focus changes | Exact conversation vs window-only result, stable target acquisition, Linux environment and app version, supported mechanism or evidence of limitation |
| [C2 #29](https://github.com/andre-motta/claude-fleet-monitor/issues/29): Add verified desktop conversation targets | Sol high, separate Sol review | H1 integrated; C1 evidence and mechanism approved | Optional desktop focus backend, configuration and consumer outcome presentation | Live exact-focus evidence for each claimed mode/platform plus unavailable/partial/error regressions; no false success |
| [D1 #30](https://github.com/andre-motta/claude-fleet-monitor/issues/30): Add Fleet to Tongs desktop | Sol high, separate Sol review; Luna assets/docs after host contract | H1 integrated and verified; approved and integrated Tongs desktop API/host | Fleet desktop plugin, packaged frontend assets and host tests; no standalone shell | Acceptance in desktop.md, including clean optional install, legacy TUI and actual desktop interaction |
| [V1 #33](https://github.com/andre-motta/claude-fleet-monitor/issues/33): Validate combined harness release candidate | Astra integration, Sol independent final review | B0, H1, H2, H3; add C2/D1 only when separately ready | Integrated acceptance package, release claims and exact proposed publication | Available local regression matrix, CLI/MCP/TUI and real harness evidence; no unresolved required findings; explicit CTO branch/PR gate, then required CI before merge |

### Expanded shell and terminal validation

Andre requested broad, properly validated shell support with the design approval.
Treat shells, emulators and multiplexers as separate layers. Inventory sh/bash,
zsh, fish, dash, ksh, Nushell, PowerShell and cmd; existing emulators plus Kitty,
WezTerm and other candidates with maintained integration APIs; tmux/zellij/screen;
and WSL/SSH boundaries. This is a candidate inventory, not an added support claim.

- [S1 #31](https://github.com/andre-motta/claude-fleet-monitor/issues/31): Sol high
  investigates and validates available real shells with isolated synthetic events,
  inspects terminal APIs and records versions, observed capabilities and gaps.
- [S2 #32](https://github.com/andre-motta/claude-fleet-monitor/issues/32): implement
  bounded extensions after verified H1/S1 contracts, prioritizing reliable APIs.
  Material new mechanisms return for design acceptance before dependent work.
- Record emitter execution, environment preservation, PID/cwd/TTY, lifecycle,
  exact tab/pane selection, window activation and nested combinations separately.
  Live proof, simulated events, mocked OS tests and untested targets must be
  distinguishable. Unsupported outcomes and operation failures cannot count as
  successful focus. Do not edit users' shell startup files merely to run tests.

Dependencies are acyclic. No dependency is integrated for this initiative yet.
C1 can run alongside H1 after approval. H1 owns shared files until integrated;
H2/C2 changes to CLI/config/focus must be serialized if ownership overlaps.
Desktop contract work belongs to Tongs and is an external prerequisite, not an
assigned or delivered Fleet item. Do not block the Pi candidate on C2 or D1.
After H3, CTO prioritization of further adapters is a separate product decision,
not a condition for completing H3.
Each assignment must record exact base/dependency commits, allowed files,
interfaces, checks, model and branch before execution; details unresolved above
must be settled before dependent work is marked ready.

## Evidence, review and local state

- Original `main` was clean at the repository baseline; `origin/main` remains
  there. Astra fast-forwarded local `main` to reviewed adoption commit
  `f5f17e9e38abab45fedf94cd47f5e61ea9af181c` with normal `git merge --ff-only`.
- Isolated branch `codex/harness-desktop/planning`; documentation-only adoption
  and feature records. Local promotion updated only the reviewed documentation;
  no unrelated checkout changes were present.
- Linux Python 3.14.7 in an isolated temporary virtual environment; editable
  installation of existing `.[dev]` succeeded after network permission.
- Baseline `python -m pytest -q`: **86 passed, 4 skipped** (optional Tongs absent).
  OS behavior is mocked; this is not live harness or focus evidence. Python
  3.10/3.12/3.13 and live macOS/Windows checks were not run for this docs change.
- `claude-fleet --help` passed. `import claude_fleet_monitor.mcp_server` failed
  under MCP 2.1.1 with renamed FastMCP API; B0 records this unmet runtime check.
  Tests passing do not establish a healthy MCP integration.
- No Pi or desktop implementation, installs into user harness settings, live
  focus actions or Tongs modifications performed. No upstream mutations.
- Observed host capacity for this planning session: four agents including Astra.
- Tested adoption revision: `f5f17e9e38abab45fedf94cd47f5e61ea9af181c`.
  Final `python -m pytest -q`: 86 passed, 4 optional Tongs skips. All seven changed
  Markdown files passed relative-link/style checks; committed diff passed
  `git diff HEAD^ HEAD --check`. Working tree matched the committed candidate.
- Independent reviewer: `planning_review`, actual `gpt-5.6-sol` at `high`,
  verdict **APPROVED WITH NOTES** after re-review. Required corrections resolved:
  existing Ghostty documentation, gated optional JavaScript policy change,
  adversarial store acceptance, host-dependent desktop packaging, separate
  post-H3 product priority, CI/publication sequencing and runtime capacity checks.
  Architecture, security, UX and QE were reviewed proportionally to a docs change.
- Feasibility investigator: `harness_feasibility`, actual `gpt-5.6-sol` at `high`.
  Pi evidence is source/local-version inspection, not live integration evidence.
- This evidence-only follow-up records review and local promotion after the
  tested adoption revision; it does not change product code or approved scope.

The adoption artifact is independently reviewable despite the pre-existing MCP
failure. Any feature release must resolve B0 and complete its required evidence;
no check has been silently waived. Adoption is locally integrated. At that handoff the feature graph was planned;
current approved assignments are recorded below.
Resume by inspecting branch/worktree/tracker state and verified dependency
commits. Design approval and scoped issue publication are recorded; proceed with
ready implementation. Code publication remains a separate gate.

## Execution authorization and assignments, 2026-09-07

On 2026-09-07, Andre approved the staged design, authorized GitHub issue
publication and maintenance, and expanded scope to broad shell compatibility
inventory and validation. Concrete additional
terminal implementations follow evidence and the existing architecture. It does
not grant code publication or waive live-platform acceptance.

| Item | Actual agent/runtime | Branch | Verified assignment base | State |
| --- | --- | --- | --- | --- |
| B0 #24 | mcp_repair / gpt-5.6-luna xhigh | codex/harness-desktop/b0 | 229a9d3 | assigned |
| C1 #28 | chatgpt_focus / gpt-5.6-sol high | codex/harness-desktop/c1 | 229a9d3 | assigned investigation |
| S1 #31 | shell_compatibility / gpt-5.6-sol high | codex/harness-desktop/compatibility | 229a9d3 | assigned investigation |

The 14 published GitHub issues have native parent/sub-issue and blocking
relationships plus readable dependency lists; remote links were verified.

Each has an isolated worktree. B0 owns only dependency metadata and new MCP
regression tests; C1 owns its new evidence/prototype; S1 owns its new compatibility
evidence. Astra owns this shared record and issue maintenance. Baseline rerun:
86 passed, 4 optional Tongs skips. No implementation dependency is integrated yet.
