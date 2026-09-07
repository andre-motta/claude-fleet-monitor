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
