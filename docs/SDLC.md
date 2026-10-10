# Fleet Monitor SDLC profile

Fleet Monitor adopts Agent SDLC **0.2.4**. Andre approved migrating from the
earlier 0.1.0 baseline on 2026-10-09; the terminal focus initiative (#32, #47)
is the first to run under 0.2.4. An installed skill update does not change an
active initiative until a migration is agreed again.

## Project settings

| Setting | Project value |
| --- | --- |
| Repository and tracker | Public `andre-motta/claude-fleet-monitor`; GitHub Issues and PRs, native sub-issue/blocking links plus readable dependencies |
| Default branch | `main`; merging into it is Andre's acceptance gate |
| Feature integration | One local integration branch per initiative, owned by the orchestrator; current: `feat/terminal-focus-2` |
| Worktrees | One isolated worktree and branch per work item, outside the repository checkout; removed once integrated |
| Runtime | Python >=3.10; CI matrix 3.10, 3.12, 3.13 on Ubuntu 24.04 |
| Setup | `python3 -m venv .venv`, then `.venv/bin/python -m pip install -e ".[dev]"`; Windows uses `.venv/Scripts/python.exe` |
| Focused checks | Relevant pytest modules, applicable functional checks and `git diff --check` |
| Integrated checks | Full pytest and available local Python matrix; `.[dev,tongs]` when changing Tongs integration; actual affected CLI/MCP/harness journeys |
| Hosted gates | Workflow semantic lint, Python matrix with headless TUI journey, strict Podman shell validation and real Pi lifecycle/tmux validation on PRs into `main` and `feat/**`, plus pushes to `main` |
| Documentation checks | Relative links, command accuracy, policy consistency and `git diff --check` |
| Platforms | Preserve Linux/macOS/Windows behavior using platform mocks; require live evidence for newly claimed terminal or desktop capabilities |
| Commit rules | Imperative title under 50 characters, blank line, one-line why body, issue reference and trailers; `git commit -s`; `Co-Authored-By` naming the actual Claude model without context-size annotation |
| Tracker authority | Maintain the initiative's issues, links and public-safe progress |
| Publication authority | Per initiative, as Andre states it. Current: one combined PR from the integration branch into `main` after review and acceptance |
| Reserved CTO gate | Design approval, final acceptance and merge into `main`; direct main pushes, tags, releases and deployments require covered authorization |
| Publication effects | `main` and PR CI as above; `v*` tags publish to PyPI using the `pypi` environment; no Pages workflow found |
| Evidence | Public-safe records under `docs/work/` and validation artifacts; no private conversation content, credentials or personal absolute paths |

Use the environment's Python. Standard tests must not require live agents,
terminals or display servers. Report optional skips separately. Container shell
execution, mocked OS behavior and live desktop focus are distinct evidence.
A new runtime dependency still requires discussion.

## Roles and authority

Andre is CTO. A Claude Code orchestrator session owns framing, design
synthesis, orchestration, tracking and local integration. Work items are built
by `sdlc-engineer` agents and independently reviewed by `sdlc-reviewer` agents;
both inherit the session model unless a stage has a concrete reason to
override it. Authors never review their own work. Review depth follows the item
risk tier: low merges on green checks, standard gets one review, high gets
review plus delta re-review of corrections.

Signed-off local commits in worktrees and local integration are autonomous.
Pushing, opening PRs, merging upstream, tags, releases and tracker writes each
need authorization covering that action; opening a PR never implies merging it.
The final PR into `main` presents tested commits, independent review,
functional evidence and any unmet checks. Required checks that cannot run
remain unmet unless Andre explicitly waives that scope. A failed check is not
permission to merge or weaken the gate.

## State and integration

Track planned, in progress, review, locally integrated, CTO accepted and
delivered to `main` separately. Keep issues open until `main` contains the
accepted work. Confirm the item head, review verdict, resolved findings and
applicable checks before each integration, and run checks on the merged tree
before committing the merge. Re-test combined changes after conflicts or
dependency updates. Preserve dirty checkouts and unrelated user work. Record
failed checks as well as successful reruns, and label synthetic, mocked and
live evidence explicitly.

## Reconciled instructions

- The general per-commit approval rule allows autonomous signed-off local
  commits within an approved initiative. DCO and message conventions remain.
- Existing fork/PR guidance remains available to ordinary contributors; agents
  use the assigned worktree, independent review and initiative gates.
- Discovery owns shared discovery/session access; hooks emit fleet events;
  CLI install/uninstall owns harness configuration; terminal APIs own terminal
  OS integration. Existing violations do not justify duplicating them.
- Hooks stay fast, with no network or heavy imports. Ordinary imports remain
  module-level except optional/circular cases. No shell scripts; hook/discovery
  writes stay within FLEET_DIR.
- Hook-time terminal capture reads the environment only, with one exception
  Andre approved on 2026-10-10 (#52): on Linux, a bounded (64 steps),
  cycle-safe, never-raising walk of the hook's ancestors that reads only
  `/proc/<pid>/stat` (comm and ppid). It never reads `/proc/<pid>/environ` or
  `cmdline`, starts no subprocess and uses no D-Bus; any failure falls back to
  env detection. Other platforms stay env-only.
- The approved design permits a small dependency-free optional Pi JavaScript
  extension packaged with the Python distribution. The core remains Python.
  Concrete ChatGPT desktop routing still requires accepted C1 evidence.

## Initiatives

- Active: terminal focus, finishing #32 and implementing #47 on
  `feat/terminal-focus-2`, delivered as one combined PR to `main`. See
  [terminal focus](work/terminal-focus.md).
- Historical: [harnesses and desktop](work/harnesses-desktop.md), delivered
  under 0.1.0 with Codex roles and a child-PR feature branch. Its remaining
  desktop items (#21, #22, #28, #29, #30) keep their recorded research and
  design gates; the saved [desktop feature](work/desktop.md) still applies.
