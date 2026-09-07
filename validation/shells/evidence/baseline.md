# Shell validation evidence

Result: **partial**
Run type: `live-container-synthetic-emitter`
Generated: `2026-09-07T13:55:24.072953+00:00`

## Reproduction metadata

- Source commit: `229a9d3c2d935f3fcfeb08a747c7235569180706`
- Source tree SHA-256: `ad91326b827cea9bceede2ba66d5cb3119137b47d50faf3514553bbec16be278`
- Mounted source hash matches: `True`
- Image reference: `localhost/fleet-shell-validation:20260907`
- Image ID: `03bedbc4d684839bbfc65252adffd0e77440ac95a7f7592ba9e49b6358c36ed3`
- Image digest: `sha256:26d4a3ec515b09b6d0a46711629b4fb67f2e6db979f430407827f21252b4c3d4`
- Container network: `none`
- Allow known gaps: `True`
- Read-only source mount: `/workspace/src:ro`
- Read-only validation mount: `/validation:ro`
- Writable path: `/tmp/fleet-work:tmpfs`
- Installer builder: `claude_fleet_monitor.cli._install_hooks`
- Installer config written: `False`

## Shell matrix

| Shell | Binary mode | Alias | Version | Available | Version source |
| --- | --- | --- | --- | --- | --- |
| Bash | `['bash'] -c` | ordinary command mode | `GNU bash, version 5.2.15(1)-release (x86_64-pc-linux-gnu)` | `True` | version command |
| Dash | `['dash'] -c` | POSIX command mode | `0.5.12-2` | `True` | dpkg-query package metadata |
| Zsh | `['zsh'] -c` | command mode | `zsh 5.9 (x86_64-debian-linux-gnu)` | `True` | version command |
| Fish | `['fish'] -c` | command mode | `fish, version 3.6.0` | `True` | version command |
| Ksh | `['ksh'] -c` | command mode | `version         sh (AT&T Research) 93u+m/1.0.4 2022-10-22` | `True` | version command |
| Mksh | `['mksh'] -c` | command mode | `@(#)MIRBSD KSH R59 2023/04/29 +Debian` | `True` | KSH_VERSION |
| Tcsh | `['tcsh'] -c` | command mode | `tcsh 6.24.07 (Astron) 2022-12-21 (x86_64-unknown-linux) options wide,nls,dl,al,kan,sm,rh,nd,color,filec` | `True` | version command |
| BusyBox ash | `['busybox', 'ash'] -c` | ash applet | `BusyBox v1.35.0 (Debian 1:1.35.0-4+deb12u1+b1) multi-call binary.` | `True` | version command |
| Yash | `['yash'] -c` | command mode | `Yet another shell, version 2.52` | `True` | version command |

## Lifecycle results

18/18 cases passed. Each case covered `session-start`, `prompt-submit`, `tool-use`, `permission-request`, `stop` and `session-end` for one agent. Records were selected by their JSON `session_id` value.

| Shell | Agent | Result |
| --- | --- | --- |
| bash | claude | `passed` |
| bash | codex | `passed` |
| dash | claude | `passed` |
| dash | codex | `passed` |
| zsh | claude | `passed` |
| zsh | codex | `passed` |
| fish | claude | `passed` |
| fish | codex | `passed` |
| ksh | claude | `passed` |
| ksh | codex | `passed` |
| mksh | claude | `passed` |
| mksh | codex | `passed` |
| tcsh | claude | `passed` |
| tcsh | codex | `passed` |
| busybox-ash | claude | `passed` |
| busybox-ash | codex | `passed` |
| yash | claude | `passed` |
| yash | codex | `passed` |

## Executable path probe

Manual quoted controls passed for 9/9 shells. Installer-generated commands passed for 0/108. The manual unquoted control is expected to fail for the baseline path with spaces; generated-command failures are acceptance failures unless `--allow-known-gaps` is explicitly supplied.

| Shell | Manual unquoted return code | Manual quoted | Installer-generated commands | Classification |
| --- | ---: | --- | ---: | --- |
| bash | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| dash | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| zsh | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| fish | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| ksh | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| mksh | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| tcsh | `1` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| busybox-ash | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |
| yash | `127` | `True` | `0/12` | installer-generated-command-path-quoting-gap |

## Known gaps

- 108 installer-generated commands failed at the baseline revision because the emitted hook path is unquoted. These failures are recorded individually in the JSON evidence.

## Limitations

- Synthetic stdin payloads do not establish real Claude or Codex process behavior.
- Container execution cannot validate PID, tty, terminal detection, pane or tab selection, or OS window activation.
- The installer configuration files are not mounted or modified; the temporary Python entry point exercises the hook argument contract.
- The unquoted executable path control records the current CLI hook path quoting gap; installer-generated command results are reported separately and are required to pass for a clean result.
