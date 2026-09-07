# Harness event, identity and focus contract

This document defines the implemented Fleet schema version 1 contract for
built-in harness adapters and downstream H2 work. It is the public boundary
between harness event producers, shared storage, process discovery and focus
backends.

## Registry and compatibility

`claude_fleet_monitor.harnesses` is the built-in registry. A `HarnessSpec`
declares a stable lowercase harness ID, display name, exact process names,
accepted event names, process identity mode and capabilities. Claude Code and
Codex use discoverable process identity. Pi is registered for extension events
and requires an exact emitter PID. Adding metadata to this registry does not by
itself implement or advertise a working integration.

The public `session_id` remains the harness-native conversation ID. Existing
CLI, TUI and MCP output therefore retains it. Schema version 1 adds:

- `harness_id`, also mirrored in the legacy `agent` field;
- `instance_id`, which identifies one running harness instance independently of
  a resumable conversation;
- `canonical_id`, which identifies the harness, native session and running
  instance together;
- `sequence` for producers that provide an explicit monotonic order;
- `process_start` for PID reuse protection where the platform exposes it;
- `focus_target`, a typed terminal, desktop or unavailable target.

Consumers must use `canonical_id` as an internal row or selection key and show
`session_id` to users. A query can match canonical ID, native session ID, repo or
PID. More than one match is ambiguous and must not be guessed.

Legacy JSON files remain readable. An absent `agent` means Claude for legacy
records only. Fleet does not rewrite legacy filenames. When a version 1 record
for the same harness and native session exists, it takes precedence over the
legacy record. Different harnesses with the same native ID remain distinct.

## Normalized extension event

An extension invokes the installed hook entry point as:

```text
claude-fleet-hook fleet-event --agent <harness-id>
```

It writes one UTF-8 JSON object to standard input. The maximum encoded payload
is 64 KiB. Unknown harnesses, unknown event arguments, malformed JSON and
invalid fields are rejected before Fleet creates or updates a record.

The normalized version 1 object is:

```json
{
  "schema_version": 1,
  "event_id": "pi.session-start",
  "session_id": "native-conversation-id",
  "instance_id": "stable-extension-process-token",
  "sequence": 1,
  "pid": 1234,
  "cwd": "/working/directory",
  "status": "started",
  "detail": "session started",
  "tool": ""
}
```

`event_id` must use `<harness-id>.` as its namespace. `session_id` and
`instance_id` are nonempty UTF-8 strings of at most 512 bytes. `cwd` is a
nonempty string of at most 4096 bytes. `pid` is a positive integer and must be
the emitting harness process, not Fleet's child hook process. `sequence` is a
nonnegative integer and is mandatory for emitter-identity adapters such as Pi.
The adapter must keep it strictly increasing for each instance and session
record. Fleet never executes payload fields or accepts a command string.

`status` is one of `started`, `running`, `idle`, `waiting`, `error` or `ended`.
`discovered` is reserved for Fleet process discovery. `detail` is optional and
limited to 512 bytes. `tool` is optional and limited to 256 bytes. `ts` can
provide nonnegative integer epoch seconds; Fleet otherwise uses receipt time.
Timestamps more than five minutes in the future are rejected. The sequence,
rather than the timestamp, decides producer order.

H2 owns Pi lifecycle translation into this normalized event. It must use one
stable random instance token for the lifetime of each Pi extension process and
one serialized monotonic sequence per session record. Prompt nesting, previous
state restoration and session switching remain Pi adapter responsibilities.
The normalized event contains status metadata only. It must not contain message
bodies, arbitrary commands or transcript content.

Installed Claude and Codex hook aliases continue to accept their native hook
payloads. Fleet translates each accepted alias to a namespaced `last_event`,
normalizes status, resolves the exact ancestor process and derives the instance
from PID plus process start identity. On platforms without a readable process
start identity, Fleet creates a random per-session instance token and reuses the
stored token for later events from the same exact PID. Exact focus remains
unavailable there because PID reuse cannot be excluded.

## Store and ordering

Fleet derives the canonical ID from a SHA-256 digest of the length-safe JSON
tuple `[harness_id, session_id, instance_id]`:

```text
fleet:v1:<harness-id>:<64 lowercase hex characters>
```

The filename contains only the schema version and digest. Raw native IDs are
never interpolated into paths. Records are at most 64 KiB. Fleet rejects a
configured fleet directory that is itself a symlink, ignores symlink record
entries and refuses to replace a symlink record or lock entry.

Each canonical record has its own lock file inside the fleet directory. POSIX
uses `flock`; Windows uses `msvcrt.locking`. Under that lock, Fleet rereads the
current record, rejects an explicit sequence that is equal to or below the
stored producer sequence, writes a private temporary file, flushes it and
atomically replaces the record. Readers therefore see the old or new complete
JSON document. A denied or unsafe write leaves the known record intact.

Legacy Claude and Codex hooks do not supply a producer sequence. Fleet serializes
their updates with the same lock and records `arrival_sequence`, so concurrent
writes have a defined local receipt order. That receipt order is not proof of
the producer's original event order. New extension adapters must provide an
explicit sequence.

A running instance change produces a different canonical record even if the
native conversation or PID is reused. Fleet does not deduplicate hook sessions
only because they share a PID or working directory. A discovery placeholder is
suppressed only by a hook record with the same harness and process identity.

## Process identity

`discovery.ProcessInfo` is the shared process abstraction. It contains PID,
parent PID where available, process name, executable basename, argument vector,
working directory and a platform process-start token. Hook ancestry, background
discovery, liveness and focus validation use this abstraction.

Discoverable harness matching compares the exact process name, executable
basename or argument zero against registry names. Harness names appearing in
arbitrary command arguments do not match. Linux reads `/proc`; macOS uses `ps`
and `lsof`; Windows uses a read-only `tasklist` query. Fleet never uses
`os.kill(pid, 0)` on Windows. Windows does not currently expose a parent PID,
working directory or stable start token through this lightweight path, so Fleet
reports operations requiring that evidence as unavailable.

Focus validates the stored PID against both the registered harness identity and
the stored process-start token. An explicit running instance without a matching
start token is not trusted merely because the PID is alive.

## Focus results

`focus.focus_session(query)` and `TerminalAPI.focus_result()` return a
`FocusResult`. `to_dict()` exposes:

- `state`: `complete`, `partial`, `failed`, `unavailable`, `ambiguous` or
  `not-found`;
- `reason`, `backend`, `pid` and `target_found`;
- independent `selection` and `activation` operations, each with `attempted`,
  `succeeded` and `detail`;
- derived `successful` and `complete` booleans.

`complete` requires a located target plus successful tab or pane selection and
successful window activation. `partial` means at least one reported operation
succeeded. Failed subprocess exit codes are false. A found PID alone is not a
focus success.

The legacy `TerminalAPI.focus()` and top-level `focus()` functions return true
when at least one operation succeeds, preserving useful window-only behavior.
CLI exit status uses the same compatibility rule and prints partial focus
explicitly. Rich consumers should use `FocusResult` and must not relabel partial
focus as exact.

The terminal captured by the hook is authoritative. Fleet does not try other
specific terminal backends after it fails. Missing terminal metadata and unknown
captured backends return unavailable. A record explicitly captured as `generic`
can report window activation as partial because the generic backend has no tab
selection capability. Desktop targets remain unavailable until a separately
accepted desktop backend is configured.

Current Ghostty child mapping returns no target when ancestry is unavailable,
Zellij returns no exact pane target, and VTE alone does not identify GNOME
Terminal. These are truthful limitations, not support regressions. Live terminal
evidence remains required before promoting any backend capability claim.
