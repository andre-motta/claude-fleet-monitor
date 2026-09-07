# Fleet Monitor SDLC profile

Fleet Monitor adopts Agent SDLC **0.1.0**, source commit
`4e851d1b8a903aa8bebceea078860a21152ee8e8`. The installed skill's
`references/workflow.md` matches that source revision. This profile records the
project policy so ordinary contributors do not need access to the private skill.
An updated skill does not change an active initiative's pinned workflow.

## Project settings

| Setting | Project value |
| --- | --- |
| Repository and tracker | Public `andre-motta/claude-fleet-monitor` on GitHub; use Issues and PRs, reuse existing scope, native sub-issue/blocking links when available, readable dependencies otherwise |
| Default and integration target | `main`; Astra tests a combined candidate before local promotion |
| Worktrees | One isolated worktree and `codex/<initiative>/<item>` branch per assignment; current planning worktree uses the temporary `fleet-monitor-worktrees/sdlc-planning` directory; record actual paths in local handoffs |
| Runtime | Python >=3.10; CI tests 3.10, 3.12, 3.13 on Ubuntu |
| Setup | `python3 -m venv .venv`, then `.venv/bin/python -m pip install -e ".[dev]"`; Windows uses `.venv/Scripts/python.exe` |
| Focused checks | Relevant pytest modules and `git diff --check` |
| Integrated checks | Full `python -m pytest`; available local Python matrix before publication, CI matrix required after approved PR publication and before merge; include `.[dev,tongs]` when changing Tongs integration |
| Documentation checks | Relative links, command accuracy, policy consistency, and `git diff --check`; no documentation build or lint job currently configured |
| Platforms | Preserve existing Linux, macOS, Windows behavior; use mocked OS tests plus live evidence for any newly claimed terminal/desktop capability |
| Functional evidence | Actual affected CLI/TUI/harness/desktop journeys; record app versions, OS/display server, focus target and observed result; label synthetic fixtures and mocked tests |
| Commit rules | Imperative title under 50 characters, blank line, one-line body explaining why, then trailers; `git commit -s`; Codex co-author records actual model without context size |
| Tracker authority | Read-only discovery and local feature drafts currently authorized; creating/updating public issues requires approval of the concrete issue package |
| Upstream path | CTO-approved review branch push and PR; no approval yet for this initiative; merge, direct push, tags, releases and deployment require their own covered authorization |
| Publication effects | PRs targeting `main` and pushes to `main` run tests; `v*` tag pushes build and publish to PyPI using the `pypi` environment; no Pages workflow found |
| Evidence and initiatives | `docs/work/<initiative>.md`; public-safe evidence only, no private conversation content, credentials or personal absolute paths |

Run commands using the environment's Python. Standard tests do not require live
agents, terminals or display servers. Optional skips must be reported and are
not proof of optional integration. A new runtime dependency requires discussion.

## Roles and authority

Andre is CTO. Astra (`gpt-6-astra`, configured reasoning) leads architecture,
design, writing direction, orchestration and integration. Sol (`gpt-5.6-sol`,
`high`) handles senior work and independent review. Luna (`gpt-5.6-luna`, `xhigh`)
handles bounded work under Sol review. Select those actual runtimes. An author
cannot independently review their own change. Check actual host capacity at dispatch, including the orchestrator; schedule
only ready, disjoint assignments within that capacity.

The 2026-09-07 user request authorizes workflow adoption, local planning and
isolated worktrees. Signed-off local commits for that adoption are authorized.
After design approval, contributors may commit within their assigned scope
without per-commit approval, and only Astra performs validated local integration.
Preserve unrelated edits and occupied default-branch checkouts; retain the tested
candidate if promotion would disrupt an existing checkout.

Major work has two CTO gates: design and upstream acceptance. Present concrete
architecture, dependencies and acceptance criteria at the design gate. Present
exact tested commits, evidence, independent review, limitations and proposed
upstream actions at publication. Run all locally available required checks first.
If CI requires a published branch/PR, request that scoped publication explicitly
with the CI check pending; then require passing CI and acceptance before merge.
Unavailable required checks need explicit scoped CTO waiver before acceptance,
and a CI failure reopens verification rather than implying approval to merge. Changes to approved scope or material design
return to the design gate. No implementation is authorized merely by adopting
this profile. Routine corrections within approved scope proceed autonomously.

Track planned, ready, assigned, review, locally integrated, CTO accepted and
upstream delivered separately. A local commit or open PR does not close an issue.
Before dispatch, verify dependency integration commits. Only Astra maintains
shared tracking. Contributors return base/head revisions, diff and evidence;
independent Sol review must inspect the actual candidate and record required
corrections before integration. Recheck combined changes on integration.

## Reconciled instructions

- The general per-commit approval rule has an explicit exception for adopted,
  approved Agent SDLC work. This adoption and its local documentation commits
  are explicitly authorized; subsequent feature implementation needs design
  approval. DCO and existing message conventions remain mandatory.
- Ordinary fork/PR guidance in CONTRIBUTING remains available. Assigned agents
  use isolated worktrees and the two CTO gates described here.
- Existing process/filesystem boundaries still apply: discovery owns shared
  discovery and session access; the hook writes fleet events, CLI install/uninstall
  owns harness configuration, and terminal APIs own terminal OS integration.
  These explicit responsibilities clarify the overly broad instruction that
  *all* I/O must be in discovery. Existing violations are backlog findings, not
  permission to replicate them.
- Hooks remain fast, with no network or heavy imports. Ordinary imports remain
  module-level except circular or optional dependencies. Cross-platform rules,
  no shell scripts, and hook/discovery writes restricted to FLEET_DIR remain.
- New desktop focus targets and optional Pi extension assets are proposed in
  the initiative, not adopted architectural exceptions yet.

## Active initiative

See [harnesses and desktop](work/harnesses-desktop.md) and the saved
[desktop feature](work/desktop.md). Feature design and public issue publication
remain pending. Tongs is a separate repository with separate authority.
