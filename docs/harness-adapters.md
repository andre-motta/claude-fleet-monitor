# Harness adapter guide

This guide describes the adapter boundary implemented by Fleet. It is a
contributor contract for the built-in Claude Code, Codex and Pi integrations;
it is not an arbitrary plugin loader. The [support matrix](../README.md#harness-support)
is the public capability summary. The detailed rules are in the implemented
[event, identity and focus contract](work/harness-contract.md).

## Start at the registry

The built-in [harness registry](../src/claude_fleet_monitor/harnesses.py)
declares a stable lowercase ID, display name, exact process names, accepted
events, process identity mode and capabilities. The current entries are:

| ID | Harness | Accepted producer events | Identity mode | Declared capabilities |
| --- | --- | --- | --- | --- |
| `claude` | Claude Code | Native hook aliases translated by Fleet | Discoverable process identity | Hooks, process discovery, terminal focus |
| `codex` | Codex | Native hook aliases translated by Fleet | Discoverable process identity | Hooks, process discovery, terminal focus |
| `pi` | Pi | `fleet-event` from the packaged extension | Emitter supplied PID and instance | Extension events, exact PID input |

An identifier is accepted only when it is registered and its event is in that
entry's allowlist. For example, this is the current normalized event command:

```text
claude-fleet-hook fleet-event --agent pi
```

Changing `pi` to a proposed ID does not make that harness supported. A future
adapter must change the registry and its producer or hook translation code,
then add the corresponding tests. Command examples for a future ID are
contributor scaffolding until that code exists.

The implementation boundary is deliberately small:

- [harnesses.py](../src/claude_fleet_monitor/harnesses.py) owns the registry
  and allowlists.
- [hook.py](../src/claude_fleet_monitor/hook.py) parses native and normalized
  events, applies bounds and writes lifecycle updates.
- [models.py](../src/claude_fleet_monitor/models.py) defines schema-facing
  statuses, identity fields and structured focus results.
- [discovery.py](../src/claude_fleet_monitor/discovery.py) owns process
  evidence, canonical storage, locking, atomic writes and safe reads.
- [focus.py](../src/claude_fleet_monitor/focus.py) resolves a session and
  delegates its captured target to the selected terminal backend.

## Event contract

Every producer must map its native events to the finite Fleet lifecycle:
`started`, `running`, `idle`, `waiting`, `error` and `ended`. `discovered` is
reserved for process discovery and must not be emitted as a lifecycle event.

The installed native aliases currently map as follows:

| Fleet event | Fleet state | Detail policy |
| --- | --- | --- |
| `session-start` | `started` | Fixed `session started` detail |
| `prompt-submit` | `running` | Fixed `processing prompt` detail |
| `tool-use` | `running` | Tool name only, bounded and optional |
| `permission-request` | `waiting` | Tool name only, bounded and optional |
| `stop` | `idle` | A short bounded summary, if supplied by the native hook |
| `stop-failure` | `error` | Fixed `turn failed (API error)` detail |
| `elicitation` | `waiting` | Fixed `waiting for user input` detail |
| `session-end` | `ended` | Fixed `session closed` detail |

The normalized `fleet-event` payload is a JSON object with schema version 1:

```json
{
  "schema_version": 1,
  "event_id": "pi.session-start",
  "session_id": "native-conversation-id",
  "instance_id": "extension-process-token",
  "sequence": 1,
  "pid": 1234,
  "cwd": "/working/directory",
  "status": "started",
  "detail": "session started",
  "tool": ""
}
```

The example is valid for the registered Pi emitter. It is contributor
scaffolding for any new ID until that ID is registered. `event_id` must be
namespaced as `<harness-id>.<event-name>`. Fleet does not execute payload
fields or accept a command string.

The parser enforces these bounds before a record is created or updated:

- the complete JSON input and each stored record are at most 64 KiB;
- native and instance IDs are nonempty UTF-8 strings of at most 512 bytes;
- `cwd` is nonempty and at most 4096 bytes;
- `detail` is at most 512 bytes and `tool` is at most 256 bytes;
- `pid` is a positive integer, `sequence` is a nonnegative integer and future
  timestamps are limited to five minutes;
- terminal environment maps are finite and each key and value is bounded.

Malformed JSON, NUL-containing text, invalid types, unknown harnesses,
unknown normalized statuses and unsupported events are rejected without
corrupting an existing record. Native aliases do not trust producer-supplied
PID or sequence fields. A new adapter must preserve these bounds and must
never put raw native IDs in a path or shell command.

## Identity and ordering

Keep three identities separate:

1. `session_id` is the harness-native conversation ID and may survive a
   resume, reload or process change.
2. `instance_id` identifies one running harness instance. Pi uses one random
   extension-process token; discoverable native adapters derive identity from
   process evidence and a process-start token where the platform exposes one.
3. `canonical_id` is Fleet's internal key, derived from the tuple
   `[harness_id, session_id, instance_id]` using SHA-256. It has the form
   `fleet:v1:<harness-id>:<64 lowercase hex characters>`.

Discoverable adapters must match the exact registered process name,
executable basename or argument zero. A harness name appearing in arbitrary
arguments is not process evidence for those adapters. Emitter adapters must
have their bridge supply the running process PID and a stable instance token.
For an emitter, `resolve_process_identity` retrieves `ProcessInfo` for that
PID without checking the process name. The packaged Pi bridge supplies its own
`process.pid`, while the stored process-start token is used later for stale or
PID-reuse checks. The normalized emitter endpoint therefore does not
authenticate an arbitrary supplied PID as belonging to the named harness.

An emitter sequence is mandatory and must increase strictly for each instance
and session record. Under the record lock Fleet rereads the current sequence
and rejects an equal or older event. Native aliases have no producer sequence,
so Fleet serializes them and records a local `arrival_sequence`; that ordering
is only receipt order. A producer with parallel callbacks must serialize its
own delivery or supply an ordering that survives retries, session switching
and process reload.

If process ancestry cannot be resolved, Fleet stores an explicit unresolved
record with the `unresolved` instance marker and unavailable focus. A later
identified event is written before the placeholder is removed. An adapter must
not invent a PID, merge different harnesses that share a native ID, or revive
an unresolved placeholder after a successful identity migration.

## Storage, privacy and fail-open behavior

All writes go through [discovery.py](../src/claude_fleet_monitor/discovery.py).
The configured Fleet directory cannot be a symlink. Symlink record and lock
entries are ignored or rejected, depending on the operation. Each canonical
record has its own lock; writes use a private temporary file, flush and an
atomic replacement, so readers observe a complete old or new document. A
denied or unsafe write leaves the last valid record intact.

An adapter sends status metadata only. The normalized payload has no prompt,
transcript, assistant message, tool argument, tool result, provider response
or arbitrary command field. Details and tool names must be deliberately
bounded. A native hook may receive richer input from its harness, but the
translation boundary must discard fields Fleet does not need.

Delivery is best effort. A rejected event or unavailable Fleet directory must
not block the harness's own turn. The Pi bridge has a bounded queue and
bounded send and shutdown waits; it drops intermediate events when necessary
and keeps the final shutdown attempt bounded. Future bridges must retain this
fail-open rule, avoid network calls and avoid importing the TUI, MCP or desktop
runtimes into the hook path.

## Installer and package ownership

The [CLI installer](../src/claude_fleet_monitor/cli.py) owns Claude Code and
Codex hook configuration and the Fleet MCP registration. The default command
configures those two harnesses. Pi is explicit opt-in:

```bash
claude-fleet install --agent pi
```

`--agent all` selects all three. A new adapter needs an explicit CLI selection,
an upgrade path and an uninstall path. It must preserve unrelated settings and
must not silently convert an existing user-owned configuration.

Pi's [installer](../src/claude_fleet_monitor/pi_install.py) records an ownership
marker, exact absolute hook and extension paths, and all managed paths. It
installs the new package path before removing old owned references; failed old
removals remain recorded for retry. It refuses an unowned config, removes only
paths recorded as Fleet-owned and leaves unrelated extensions in place. A new
adapter must define equivalent ownership and migration behavior before its
install command is advertised.

The packaged Pi bridge is a dependency-free JavaScript extension described by
its [package manifest](../src/claude_fleet_monitor/pi_extension/package.json).
It is installed through Pi's package command, and its hook executable is the
packaged `claude-fleet-hook`. Optional JavaScript is currently an approved Pi
exception to the Python core rule. Do not add an npm or runtime dependency to
the core solely to add a candidate adapter. Pi lifecycle installation does not
register an MCP server.

## Focus and consumer behavior

The [focus service](../src/claude_fleet_monitor/focus.py) uses the target
captured by the producer. It does not guess another terminal backend after a
failure. `FocusResult` reports independent target selection and window
activation operations with `complete`, `partial`, `failed`, `unavailable`,
`ambiguous` and `not-found` outcomes.

`complete` requires a located target, successful pane or tab selection and
successful window activation. `partial` means at least one operation
succeeded. A running PID or a successful subprocess exit without proof of the
intended target is not exact focus. Desktop conversation targets remain
unavailable until a separately accepted desktop backend exists. The legacy
boolean API returns true when one operation succeeds, so rich consumers must
use the structured result when exactness matters.

An adapter's acceptance evidence must label these separately:

- lifecycle records written by a synthetic payload;
- a real harness process and its process identity;
- terminal selection of an exact pane or tab;
- activation of the parent desktop window;
- MCP consumer access to Fleet records; and
- native MCP registration in the harness itself.

The current [shell suite](../validation/shells/README.md) proves real shell
quoting and hook invocation with synthetic events in rootless Podman. The
[Pi suite](../validation/pi/README.md) proves a real Pi process, synthetic
localhost provider, lifecycle transitions and exact tmux pane selection in an
isolated server. Platform-specific process and focus unit tests use mocks.
None of those facts establish live Claude or Codex process discovery or a
desktop GUI result.

## Acceptance checklist for a new adapter

Before calling an adapter supported, contributors should provide:

1. A registry entry with a stable ID, exact event allowlist, identity mode and
   declared capabilities.
2. Native-to-Fleet mappings for start, active work, tools, permission or user
   waits, successful completion, failure, resume or reload and shutdown. Each
   unknown or unsupported event must be harmless.
3. A versioned payload parser with tests for bounds, malformed input, hostile
   IDs, NULs, out-of-order delivery, duplicate delivery, concurrent delivery
   and a write failure.
4. Tests proving native session identity, running instance identity, PID and
   process-start handling, canonical IDs, same-native-ID collisions and
   session switching. A process name in an arbitrary argument is not enough.
5. Storage tests for symlinks, path traversal, lock contention, atomic
   visibility and legacy records, plus proof that payload fields cannot escape
   the Fleet directory.
6. Fail-open timing and shutdown tests that do not block the harness or import
   heavy Fleet consumers.
7. Installer tests for clean install, idempotence, virtual-environment or
   package-path migration, partial cleanup, ownership conflicts and safe
   uninstall. Include package assets in the built distribution.
8. Focus tests for exact selection, selection-only partial success,
   activation-only partial success, unavailable targets, stale PIDs and
   ambiguous queries. Then run a real harness and terminal where the adapter
   claims support.
9. Evidence that records runtime versions, OS and terminal context and states
   whether each result is live, synthetic, mocked or untested. A hook fixture
   cannot establish a real agent process or GUI result.

## Candidate integrations

The following are research candidates, not implemented Fleet adapters. Their
documented extension surfaces are useful starting points, but the registry,
normalized event boundary, identity evidence and acceptance checklist still
apply. Implementation order requires CTO prioritization.

### Gemini CLI

[Gemini CLI hooks reference](https://geminicli.com/docs/hooks/reference/) documents
JSON command hooks configured in `settings.json`. Hooks receive common
`session_id`, `transcript_path`, `cwd`, `hook_event_name` and `timestamp` fields
on standard input. The reference lists `SessionStart`, `SessionEnd`,
`BeforeAgent`, `AfterAgent`, `BeforeTool`, `AfterTool`, `Notification` and
other events. Hook output on standard output is protocol JSON; logs belong on
standard error. Exit code 2 can block an action, while other nonzero codes are
warnings. A Fleet observer would need to preserve that protocol and keep
delivery fail-open.

Before implementation, verify the installed version's payloads and whether a
hook can establish the live Gemini process PID, process-start token, cwd and
terminal environment rather than only its child command context. Confirm
which events mean waiting, completion and failure: the documented
`Notification` hook is observability-only for tool permissions and cannot
grant them. Measure hook wait behavior, parallel or sequential ordering,
resume and clear semantics, malformed-output behavior and version drift. Run
the real CLI through a real terminal and test exact focus separately from
synthetic hook delivery.

### OpenCode

[OpenCode plugins](https://opencode.ai/docs/plugins/) documents JavaScript and
TypeScript plugins loaded from project or global plugin directories or from
npm configuration. The plugin context includes project, directory, worktree,
client and shell access. Documented events include `session.created`,
`session.deleted`, `session.error`, `session.idle`, `session.status`,
`session.updated`, `permission.asked`, `permission.replied` and
`tool.execute.before` or `tool.execute.after`. Plugin hooks run in sequence
according to the documented load order.

The key open question is execution placement. OpenCode can expose a client,
server or desktop surface, and a server process is not automatically the
terminal pane containing the user client. Verify the event payload's stable
session ID, process or server identity, client PID, cwd and terminal
environment before assigning a Fleet instance. Define waiting, idle and error
mapping, async failure and ordering behavior, supported OpenCode versions,
plugin dependency ownership and uninstall migration. Validate a real local
interactive process and an exact terminal target; do not infer focus from a
server event or MCP availability.

### Qwen Code

[Qwen Code hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/)
documents command, prompt and other hook types. Its event surface includes
`SessionStart`, `SessionEnd`, `SessionDelete`, `UserPromptSubmit`, tool events,
`Stop`, `StopFailure`, `Notification`, `PermissionRequest`,
`PermissionDenied`, compaction and subagent events. The documented execution
rules default to parallel hooks, support `sequential: true`, and allow command
hooks to run asynchronously. Async hooks cannot return a decision because the
operation has already occurred.

An adapter must verify the exact Qwen version and payload identity fields,
including session and cwd, and establish PID and process-start evidence. Do
not assume that similar event names imply the Claude schema. Decide how
permission requests, stop failures, session deletion, retries and subagents
map to one Fleet record. Test parallel, sequential and async delivery for
ordering, duplicate events and fail-open behavior. Keep tool inputs and prompt
content out of Fleet records, then validate the real Qwen process, terminal
selection and any client/server mode separately.

### GitHub Copilot CLI

[GitHub Copilot hooks](https://docs.github.com/en/copilot/reference/hooks-reference)
documents CLI hook configuration in both camelCase and VS Code-compatible
PascalCase forms. The payloads expose fields such as `sessionId` or
`session_id`, `cwd`, timestamps and tool or stop details. The documented event
surface includes `sessionStart`, `sessionEnd`, `userPromptSubmitted`,
`preToolUse`, `postToolUse`, `postToolUseFailure`, `agentStop`,
`subagentStart`, `subagentStop`, `errorOccurred`, notifications and
permission requests. The CLI supports direct executable arguments for command
hooks, which avoids shell interpretation; an adapter should use that form.

Copilot CLI and Copilot cloud-agent behavior must be assessed separately. The
cloud agent is noninteractive, has different notification and permission
behavior and has no local terminal pane to focus. Verify versioned payloads,
session resume and end reasons, PID and process-start evidence, direct-command
failure and timeout semantics, permission wait behavior and `agentStop`
continuation behavior. Test camelCase and PascalCase inputs without trusting
transcript or tool arguments. Run a real local CLI session through a real
terminal before making any process or focus claim; record cloud behavior as a
separate capability if it is ever implemented.
