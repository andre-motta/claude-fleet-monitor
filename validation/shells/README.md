# Container shell validation

This manual suite runs the existing Python hook entry point through nine real
shell variants in an isolated rootless Podman container:

| Shell | Invocation | Alias or mode recorded |
| --- | --- | --- |
| Bash | `bash -c` | ordinary command mode |
| Dash | `dash -c` | POSIX command mode |
| Zsh | `zsh -c` | command mode |
| Fish | `fish -c` | command mode |
| Ksh | `ksh -c` | command mode |
| Mksh | `mksh -c` | command mode |
| Tcsh | `tcsh -c` | command mode |
| BusyBox ash | `busybox ash -c` | `ash` applet |
| Yash | `yash -c` | command mode |

The image is built from the official `python:3.12-slim-bookworm` image. Build
it when needed with:

```text
podman build -f validation/shells/Containerfile -t localhost/fleet-shell-validation:20260907 .
```

Run the matrix from the repository root:

```text
python3 validation/shells/run.py \
  --image localhost/fleet-shell-validation:20260907 \
  --allow-known-gaps \
  --source-commit 229a9d3c2d935f3fcfeb08a747c7235569180706 \
  --output validation/shells/evidence/baseline.json \
  --markdown validation/shells/evidence/baseline.md
```

`--allow-known-gaps` is required when capturing a historical baseline whose
installer-generated commands are known to fail. The baseline exits zero with
result `partial` and records every failed generated command. Omit this option
for candidate validation. A generated command failure then produces result
`failed` and a nonzero exit status, even if the synthetic lifecycle cases
pass.

## Hosted CI gate

`.github/workflows/shells.yml` runs the strict candidate validation on pull
requests targeting `main` or `feat/**`, and on pushes to `main` or
`feat/harnesses-desktop`. It uses the standard `ubuntu-24.04` runner, builds
the existing `Containerfile` image with rootless Podman, and runs the checked
out `src/` tree without `--allow-known-gaps`. The job has read-only GitHub
contents permission, cancels superseded runs, and fails on an image build or
inspection failure, a missing image, or any validator failure.

Each completed validator run covers nine real shells, 18 lifecycle cases, nine
manual quoted-path controls and 108 installer-generated command checks. The
seven-day artifact always includes setup metadata with the exact checked-out
commit, source tree SHA-256 and image reference. A completed validator run also
adds JSON and Markdown evidence with the image ID and image digest; a build,
image inspection or other setup failure skips the validator and leaves the
available metadata for diagnosis.
The runner uses only Python's standard library and the mounted source tree, so
the job does not install project dependencies or depend on a generated package
version file.
The recorded evidence remains synthetic emitter evidence and does not prove
real agent processes, terminal focus or GUI behavior.

The runner mounts only `src/` and `validation/shells/` read-only. The
container root is read-only, networking is disabled, and the hook store,
temporary cwd, home and generated Python entry point live in an ephemeral
tmpfs. The environment is rebuilt from a small allowlist, so host agent
settings, shell startup files and credentials are not mounted or inherited.

For every shell and both `claude` and `codex`, the runner invokes the existing
hook lifecycle in sequence: `session-start`, `prompt-submit`, `tool-use`,
`permission-request`, `stop` and `session-end`. It reads records by matching
the JSON `session_id` field across the fleet directory, then checks the agent,
cwd, repository name, status, detail and tool content. The payload cwd includes
spaces, Unicode and an apostrophe. Shell version output, image identity,
source commit and source tree hash are recorded in the evidence files.

The executable path probe creates a temporary Python `claude-fleet-hook`
entry point in a directory containing spaces. It creates fresh in-memory
Claude and Codex hook configurations through
`claude_fleet_monitor.cli._install_hooks`, extracts the emitted command for
each tested event, and executes that exact command under every shell. It also
records a manual unquoted control and a correctly quoted control. On the
baseline revision, the generated commands fail because the CLI command builder
does not quote a hook path. Generated failures are never marked as passed.
Generated events for each shell and agent reuse one session ID and run in
order, so each status assertion depends on the preceding lifecycle record.

This is synthetic emitter evidence. It does not validate a real Claude or
Codex process, PID or tty discovery, terminal detection, pane or tab selection,
OS window activation, or the installer’s writes to user configuration. The
container has no host display or terminal, and no network or real agent is
used. Standard pytest remains independent of Podman and this manual suite.
