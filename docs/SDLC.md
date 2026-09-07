# Fleet Monitor SDLC profile

Fleet Monitor adopts Agent SDLC **0.1.0**, source commit
`4e851d1b8a903aa8bebceea078860a21152ee8e8`. The installed workflow matches that
revision. Active work retains this baseline; an installed skill update does not
change the initiative. The project-specific publication authority below records
Andre's subsequent instructions for this initiative.

## Project settings

| Setting | Project value |
| --- | --- |
| Repository and tracker | Public `andre-motta/claude-fleet-monitor`; GitHub Issues and PRs, native sub-issue/blocking links plus readable dependencies |
| Default branch | `main`; final integration remains subject to CTO acceptance |
| Feature integration | `feat/harnesses-desktop`, owned by Astra |
| Worktrees | One isolated worktree and `feat/<sub-feature>` branch per assignment; preserve earlier `codex/` worktrees as historical candidates until migrated |
| Runtime | Python >=3.10; CI matrix 3.10, 3.12, 3.13 on Ubuntu 24.04 |
| Setup | `python3 -m venv .venv`, then `.venv/bin/python -m pip install -e ".[dev]"`; Windows uses `.venv/Scripts/python.exe` |
| Focused checks | Relevant pytest modules, applicable functional checks and `git diff --check` |
| Integrated checks | Full pytest and available local Python matrix; `.[dev,tongs]` when changing Tongs integration; actual affected CLI/MCP/harness journeys |
| Hosted gates | Workflow semantic lint, Python matrix and strict Podman shell validation on PRs into `main` and `feat/**`, plus pushes to `main` and the feature integration branch |
| Documentation checks | Relative links, command accuracy, policy consistency and `git diff --check` |
| Platforms | Preserve Linux/macOS/Windows behavior using platform mocks; require live evidence for newly claimed terminal or desktop capabilities |
| Commit rules | Imperative title under 50 characters, blank line, one-line why body, issue reference and trailers; `git commit -s`; actual Codex model co-author without context-size annotation |
| Tracker authority | Publish and maintain this initiative's issues, links and public-safe progress |
| Publication authority | Reviewed, locally passing issue branches may be pushed and opened as child PRs into `feat/harnesses-desktop`; Astra may merge them after required CI passes; final validated PR into `main` is authorized |
| Reserved CTO gate | Final merge into `main`; direct main pushes, tags, releases and deployments require covered authorization |
| Publication effects | Feature and main CI as above; `v*` tags publish to PyPI using the `pypi` environment; no Pages workflow found |
| Evidence | Public-safe records under `docs/work/` and validation artifacts; no private conversation content, credentials or personal absolute paths |

Use the environment's Python. Standard tests must not require live agents,
terminals or display servers. Report optional skips separately. Container shell
execution, mocked OS behavior and live desktop focus are distinct evidence.
A new runtime dependency still requires discussion.

## Roles and authority

Andre is CTO. Astra (`gpt-6-astra`, configured reasoning) owns architecture,
design, orchestration, shared tracking and integration. Sol (`gpt-5.6-sol`,
`high`) handles senior implementation and independent review. Luna
(`gpt-5.6-luna`, `xhigh`) handles bounded work under independent Sol review.
Select these actual runtimes and respect available concurrency. Authors cannot
independently approve their own changes.

The initial request authorized adoption, isolated worktrees and signed-off local
commits. The staged harness design, MCP repair, optional Pi bridge, ChatGPT Linux
investigation and broader shell validation were subsequently approved. Concrete
ChatGPT focus mechanisms and the Tongs desktop host retain their specified
research/design gates. Tongs remains a separate repository with separate authority.

Andre then authorized issue-by-issue upstream submissions and the feature-branch
PR model. This explicitly extends the baseline skill's default publication rule:
contributors may push their assigned `feat/` branch and open a PR into the named
feature branch after Astra confirms readiness. Astra owns child PR merge decisions
and may merge after independent review, local checks and required hosted checks
pass. Contributors do not merge shared branches or publish outside that scope.

Publish one ready issue evolution at a time. Link commits and PRs to the issue;
keep dependent publication queued until its predecessor is accepted into the
feature branch. Local engineering may continue on independently ready work in
isolated worktrees. Bootstrap #34 establishes this gate before the first product
repair, #24. Preserve existing historical candidates and verify exact dependency
commits when preparing each child branch.

The final PR into `main` follows combined validation, including the new test gates.
Its creation is authorized, but merging it remains Andre's acceptance gate.
Present tested commits, independent review, functional evidence and any unmet
checks. Changed candidates require affected verification again. Required checks
that cannot run remain unmet unless Andre explicitly waives that scope. A failed
check is not permission to merge or weaken the gate.

## State and integration

Track planned, ready, assigned, review, locally integrated, feature integrated,
CTO accepted and delivered to `main` separately. A child PR merged into the feature
branch is not delivery to `main`. Keep issues open until their intended delivery
target contains the accepted work; record feature integration commits meanwhile.

Only Astra integrates and maintains shared tracking. Confirm author base/head,
independent Sol verdict, resolved findings and applicable checks before each
integration. Re-test combined changes after conflicts or dependency updates.
Preserve dirty checkouts and unrelated user work. Record failed checks as well
as successful reruns, and identify synthetic, mocked and live evidence explicitly.

## Reconciled instructions

- The general per-commit approval rule allows autonomous signed-off local commits
  for this adopted and approved initiative. DCO and message conventions remain.
- The user's later `feat/` branch instruction takes precedence over the earlier
  `codex/` assignment convention. Historical worktrees need not be discarded.
- The baseline skill's default contributor publication restriction is narrowed
  by the explicit child-PR authority above. Main acceptance remains reserved.
- Existing fork/PR guidance remains available to ordinary contributors; agents
  use the assigned worktree, independent review and issue gates.
- Discovery owns shared discovery/session access; hooks emit fleet events;
  CLI install/uninstall owns harness configuration; terminal APIs own terminal
  OS integration. Existing violations do not justify duplicating them.
- Hooks stay fast, with no network or heavy imports. Ordinary imports remain
  module-level except optional/circular cases. No shell scripts; hook/discovery
  writes stay within FLEET_DIR.
- The approved design permits a small dependency-free optional Pi JavaScript
  extension packaged with the Python distribution. The core remains Python.
  Concrete ChatGPT desktop routing still requires accepted C1 evidence.

## Active initiative

See [harnesses and desktop](work/harnesses-desktop.md) and the saved
[desktop feature](work/desktop.md). Publication follows the issue-level feature
branch gates above; pending desktop decisions do not block the Pi candidate.
