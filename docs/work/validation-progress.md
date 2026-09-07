# Harness initiative validation progress

This record separates accepted feature-branch changes from delivery to main.
Workflow: Agent SDLC 0.1.0; [profile](../SDLC.md). Shared branch:
`feat/harnesses-desktop`. The final main PR and acceptance are pending.

## Accepted child changes

| Issue | Accepted PR and feature merge | Review and validation |
| --- | --- | --- |
| [G0 #34](https://github.com/andre-motta/claude-fleet-monitor/issues/34) | [#35](https://github.com/andre-motta/claude-fleet-monitor/pull/35), `e1e3c652ab8d7a7a3c4b5e738df307a48d34a054` | Independent Sol high review; fresh editable installation, 86 passed and four optional Tongs skips; hosted Python 3.10/3.12/3.13 passed |
| [B0 #24](https://github.com/andre-motta/claude-fleet-monitor/issues/24) | [#36](https://github.com/andre-motta/claude-fleet-monitor/pull/36), `3cce55b4f29e63e0d86ebc9191cf27551fa28b6d` | Independent Sol high review; fresh installation, 87 passed and four optional Tongs skips; dependency check and real MCP stdio initialization/tool/status passed; hosted Python matrix passed |
| [H1 #25](https://github.com/andre-motta/claude-fleet-monitor/issues/25) | [#37](https://github.com/andre-motta/claude-fleet-monitor/pull/37), `2b8134854f012eb729fcf4eae1d4898082578e5a` | Independent Sol high review; combined Python 3.12 with optional Tongs, 157 passed; real MCP stdio and strict nine-shell matrix passed; hosted Python matrix passed |
| [S1 #31](https://github.com/andre-motta/claude-fleet-monitor/issues/31) | [#38](https://github.com/andre-motta/claude-fleet-monitor/pull/38), `30eba7e129afac33b8c8e83be4da0e733412589e` | Independent Sol high review; strict local matrix passed; actual hosted Python and nine-shell gates passed |
| [C1 #28](https://github.com/andre-motta/claude-fleet-monitor/issues/28) | [#39](https://github.com/andre-motta/claude-fleet-monitor/pull/39), `d72de3bbf142a371ee35ccb38b32ec977eb5e2e6` | Independent Sol high review of the public-safe investigation; unchanged patch after rebase; hosted Python and strict shell gates passed; live exact-focus matrix remains unmet |
| [G0 #34](https://github.com/andre-motta/claude-fleet-monitor/issues/34), follow-up | [#40](https://github.com/andre-motta/claude-fleet-monitor/pull/40), `04c6735badaf97f7dcc4806ad394dc3196c0d70b` | Independent Sol high review; actionlint positive and historical negative checks passed; all five named hosted checks passed |

These issues remain open until the accepted work reaches main. The merged trees
match the reviewed candidates. No tag, release or deployment is covered by these
child merges.

## Foundation evidence and resolved findings

H1 publication candidate `91d1934d0458260b3c24d1cf4623b58f586d3a40` retains the
source tree of independently reviewed `8183db0`. The original exact final H1
source passed 156 Python 3.12 tests with Tongs. Isolated Python 3.10.21 and
3.13.15 each passed 152 tests with four optional Tongs skips. Adding B0's MCP
regression produced the combined 157-test result above; hosted tests cover the
combined publication source on all three Python versions.

The strict local Podman check exercised nine real shells and passed 18/18
synthetic lifecycles, 9/9 quoted-path controls and 108/108 installer-generated
commands. The image ID was
`03bedbc4d684839bbfc65252adffd0e77440ac95a7f7592ba9e49b6358c36ed3`, with manifest
digest `sha256:26d4a3ec515b09b6d0a46711629b4fb67f2e6db979f430407827f21252b4c3d4`.
The container had no network, a read-only source/root filesystem, dropped
capabilities and only temporary writable state. Host configuration was not mounted.

Earlier H1 candidates lost native lifecycle events when exact ancestry was
unavailable and could recreate an unresolved placeholder during concurrent
identity migration. Independent review required corrections and deterministic
regressions before acceptance. Those failures were not waived. Exact final
source now retains unresolved native state, serializes identity migration and
reports focus limitations explicitly.

Combined MCP stdio validation initially failed because its synthetic Claude
record claimed the Python validator's PID. The new exact-process check correctly
rejected that identity. The fixture now explicitly uses an unresolved session;
the product check was retained and the real stdio journey passed afterward.

## Evidence boundaries and dependent work

Shell execution is real, but lifecycle inputs are synthetic. Process/platform and
terminal-focus tests use mocks. MCP validation uses a temporary synthetic fleet
store. None of these checks establish a real harness session, exact live GUI
target selection or OS window activation.

Pi implementation is assigned on verified H1 merge `2b81348` in
`feat/pi-lifecycle`. Its own package, real runtime and terminal evidence remain
required. This foundation record does not claim completed Pi support.

The hosted shell gate was accepted in [PR #38](https://github.com/andre-motta/claude-fleet-monitor/pull/38).
Its initial workflow-file run failed before starting a runner because
`runner.temp` was used at job-environment scope. Correction `6a64515` uses the
runner-provided path inside the steps. Independent review and actionlint 1.7.12
pass; actionlint also reproduces the original error. The corrected
[hosted shell run](https://github.com/andre-motta/claude-fleet-monitor/actions/runs/34138171673)
passed on standard Ubuntu 24.04 in 76 seconds, including a 12-second image build
and 60 seconds of strict execution. Its downloaded artifact verifies all 18/9/108
cases, no gaps or failures, a clean merge checkout and matching source hashes.
The [Python matrix](https://github.com/andre-motta/claude-fleet-monitor/actions/runs/34138171597)
also passed. No paid larger runner was required. Candidate acceptance checks
must verify the expected named jobs; a Python-only green result was insufficient
while the shell workflow failed to register.

[PR #40](https://github.com/andre-motta/claude-fleet-monitor/pull/40) adds a
permanent `workflow-lint` gate using actionlint 1.7.12, with the downloaded
official binary verified against its pinned SHA-256 before execution. It checks
all workflow YAML files. The [lint and Python run](https://github.com/andre-motta/claude-fleet-monitor/actions/runs/34139686487)
and [strict shell run](https://github.com/andre-motta/claude-fleet-monitor/actions/runs/34139686451)
passed on the reviewed candidate. The five current required named checks are
`workflow-lint`, `test (3.10)`, `test (3.12)`, `test (3.13)` and
`shell-validation`; the Pi change must add and pass its own real runtime gate.

ChatGPT's exact conversation-focus mechanism and live two-target matrix remain
gated. [Tongs #17](https://github.com/andre-motta/tongs/issues/17) natively blocks
[Fleet #30](https://github.com/andre-motta/claude-fleet-monitor/issues/30) on the
production desktop host contract. Neither dependency blocks the Pi candidate.
