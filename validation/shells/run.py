"""Run the isolated multi-shell hook validation matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import uuid


MARKER = "FLEET_SHELL_VALIDATION_JSON="
DEFAULT_IMAGE = "localhost/fleet-shell-validation:20260907"
SOURCE_MOUNT = Path("/workspace/src")
WORK_DIR = Path("/tmp/fleet-work")
FLEET_DIR = WORK_DIR / "fleet"
FIXTURE_CWD = WORK_DIR / "cwd with spaces" / "Δ repo's fixture"

SHELLS = (
    {
        "id": "bash",
        "label": "Bash",
        "argv": ["bash"],
        "mode": "-c",
        "alias": "POSIX command mode",
        "version": ["bash", "--version"],
    },
    {
        "id": "dash",
        "label": "Dash",
        "argv": ["dash"],
        "mode": "-c",
        "alias": "POSIX command mode",
        "version": ["dash", "-V"],
        "fallback_version": ["dpkg-query", "-W", "-f=${Version}", "dash"],
        "fallback_source": "dpkg-query package metadata",
    },
    {
        "id": "zsh",
        "label": "Zsh",
        "argv": ["zsh"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["zsh", "--version"],
    },
    {
        "id": "fish",
        "label": "Fish",
        "argv": ["fish"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["fish", "--version"],
    },
    {
        "id": "ksh",
        "label": "Ksh",
        "argv": ["ksh"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["ksh", "--version"],
        "fallback_version": ["ksh", "-c", "echo $KSH_VERSION"],
        "fallback_source": "KSH_VERSION",
    },
    {
        "id": "mksh",
        "label": "Mksh",
        "argv": ["mksh"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["mksh", "-V"],
        "fallback_version": ["mksh", "-c", "echo $KSH_VERSION"],
        "fallback_source": "KSH_VERSION",
    },
    {
        "id": "tcsh",
        "label": "Tcsh",
        "argv": ["tcsh"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["tcsh", "--version"],
    },
    {
        "id": "busybox-ash",
        "label": "BusyBox ash",
        "argv": ["busybox", "ash"],
        "mode": "-c",
        "alias": "ash applet",
        "version": ["busybox"],
    },
    {
        "id": "yash",
        "label": "Yash",
        "argv": ["yash"],
        "mode": "-c",
        "alias": "command mode",
        "version": ["yash", "--version"],
    },
)

EVENTS = (
    "session-start",
    "prompt-submit",
    "tool-use",
    "permission-request",
    "stop",
    "session-end",
)


def _first_line(value: str) -> str:
    for line in value.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in (".pyc", ".pyo")
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _git_metadata(source_dir: Path) -> dict[str, object]:
    repo_dir = source_dir.parent if source_dir.name == "src" else source_dir
    commit = "unknown"
    dirty = None
    try:
        commit_result = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if commit_result.returncode == 0:
            commit = commit_result.stdout.strip()
        status_result = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain", "--", "src"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        dirty = bool(status_result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "mount": "src",
        "commit": commit,
        "tree_sha256": _tree_hash(source_dir),
        "dirty": dirty,
    }


def _inspect_image(podman: str, image: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            [podman, "image", "inspect", image, "--format", "{{.Id}}\\t{{.Digest}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"reference": image, "id": "unknown", "digest": "unknown"}
    fields = result.stdout.strip().split("\t", 1)
    return {
        "reference": image,
        "id": fields[0] if fields and fields[0] else "unknown",
        "digest": fields[1] if len(fields) > 1 and fields[1] else "unknown",
    }


def _clean_env() -> dict[str, str]:
    return {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": str(WORK_DIR / "home"),
        "TMPDIR": str(WORK_DIR / "tmp"),
        "FLEET_DIR": str(FLEET_DIR),
        "PYTHONPATH": str(SOURCE_MOUNT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "XDG_CONFIG_HOME": str(WORK_DIR / "config"),
        "XDG_CACHE_HOME": str(WORK_DIR / "cache"),
        "XDG_DATA_HOME": str(WORK_DIR / "data"),
    }


def _shell_path(spec: dict[str, object]) -> str | None:
    return shutil.which(str(spec["argv"][0]))


def _shell_command(spec: dict[str, object], command: str) -> list[str]:
    return [*spec["argv"], str(spec["mode"]), command]


def _run_shell(
    spec: dict[str, object],
    command: str,
    payload: dict[str, object] | None,
    env: dict[str, str],
    cwd: Path,
) -> dict[str, object]:
    try:
        result = subprocess.run(
            _shell_command(spec, command),
            input=(
                json.dumps(payload, ensure_ascii=False) if payload is not None else ""
            ),
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd),
            check=False,
            timeout=20,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()[:500],
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
        }


def _matching_records(fleet_dir: Path, session_id: str) -> list[dict[str, object]]:
    records = []
    for path in fleet_dir.rglob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("session_id") == session_id:
            records.append(record)
    return records


def _record_view(record: dict[str, object] | None) -> dict[str, object]:
    if record is None:
        return {}
    return {
        key: record.get(key)
        for key in (
            "session_id",
            "agent",
            "cwd",
            "repo",
            "status",
            "detail",
            "tool",
            "terminal",
            "terminal_env",
            "pid",
        )
    }


def _expected_payload(event: str, session_id: str, agent: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": session_id,
        "cwd": str(FIXTURE_CWD),
    }
    if event in ("tool-use", "permission-request"):
        payload["tool_name"] = "Read"
    if event == "stop":
        payload["last_assistant_message"] = (
            f"stop ✓ {session_id}\nwith a second line"
        )
    return payload


def _expected_fields(event: str, payload: dict[str, object], agent: str) -> dict[str, object]:
    details = {
        "session-start": "session started",
        "prompt-submit": "processing prompt",
        "tool-use": "using Read",
        "permission-request": "permission needed: Read",
        "session-end": "session closed",
    }
    if event == "stop":
        details["stop"] = str(payload["last_assistant_message"]).replace("\n", " ")
    expected: dict[str, object] = {
        "session_id": payload["session_id"],
        "agent": agent,
        "cwd": payload["cwd"],
        "repo": FIXTURE_CWD.name,
        "status": {
            "session-start": "started",
            "prompt-submit": "running",
            "tool-use": "running",
            "permission-request": "waiting",
            "stop": "idle",
            "session-end": "ended",
        }[event],
        "detail": details[event],
    }
    if event in ("tool-use", "permission-request"):
        expected["tool"] = "Read"
    if event in ("stop", "session-end"):
        expected["tool"] = ""
    return expected


def _check_record(
    event: str,
    payload: dict[str, object],
    agent: str,
    records: list[dict[str, object]],
) -> tuple[bool, list[str], dict[str, object] | None]:
    if len(records) != 1:
        return (
            False,
            [f"expected one record matched by session_id, found {len(records)}"],
            records[0] if records else None,
        )
    record = records[0]
    mismatches = [
        f"{key}: expected {expected!r}, observed {record.get(key)!r}"
        for key, expected in _expected_fields(event, payload, agent).items()
        if record.get(key) != expected
    ]
    return not mismatches, mismatches, record


def _lifecycle_case(
    spec: dict[str, object],
    agent: str,
    wrapper: Path,
    env: dict[str, str],
    token: str,
) -> dict[str, object]:
    session_id = f"shell-{token}-{spec['id']}-{agent}"
    command_prefix = shlex.quote(str(wrapper))
    case: dict[str, object] = {
        "shell": spec["id"],
        "agent": agent,
        "session_id": session_id,
        "cwd": str(FIXTURE_CWD),
        "command_prefix": command_prefix,
        "steps": [],
        "passed": True,
    }
    for event in EVENTS:
        payload = _expected_payload(event, session_id, agent)
        command = f"exec {command_prefix} {event} --agent {agent}"
        process = _run_shell(spec, command, payload, env, FIXTURE_CWD)
        records = _matching_records(FLEET_DIR, session_id)
        process_ok = process["returncode"] == 0
        record_ok, mismatches, record = _check_record(
            event, payload, agent, records
        ) if process_ok else (
            False,
            ["shell command exited nonzero"],
            records[0] if records else None,
        )
        step = {
            "event": event,
            "invocation": _shell_command(spec, command),
            "returncode": process["returncode"],
            "matched_records": len(records),
            "passed": process_ok and record_ok,
            "observed": _record_view(record),
        }
        if process["stderr"]:
            step["stderr"] = process["stderr"]
        if mismatches:
            step["mismatches"] = mismatches
        case["steps"].append(step)
        if not step["passed"]:
            case["passed"] = False
    return case


def _probe_versions(
    spec: dict[str, object],
    env: dict[str, str],
    cwd: Path,
) -> dict[str, object]:
    path = _shell_path(spec)
    result: dict[str, object] = {
        "id": spec["id"],
        "label": spec["label"],
        "argv": spec["argv"],
        "mode": spec["mode"],
        "alias": spec["alias"],
        "path": path or "",
        "available": False,
        "version": "",
        "version_source": "",
        "version_returncode": None,
    }
    if path is None:
        result["error"] = "executable not found"
        return result
    availability = _run_shell(spec, "exit 0", None, env, cwd)
    result["available"] = availability["returncode"] == 0
    if not result["available"]:
        result["error"] = availability["stderr"] or "shell command mode failed"
    try:
        version_process = subprocess.run(
            spec["version"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd),
            check=False,
            timeout=10,
        )
        version = _first_line(version_process.stdout + "\n" + version_process.stderr)
        version_returncode = version_process.returncode
        if spec["id"] == "mksh" and version_process.returncode != 0:
            version = ""
    except (OSError, subprocess.TimeoutExpired) as error:
        version = ""
        version_returncode = None
        result["version_error"] = f"{type(error).__name__}: {error}"
    result["version_returncode"] = version_returncode
    result["version_source"] = "version command"
    if not version and spec.get("fallback_version"):
        fallback = subprocess.run(
            spec["fallback_version"],
            input="",
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd),
            check=False,
            timeout=10,
        )
        version = _first_line(fallback.stdout + "\n" + fallback.stderr)
        result["version_returncode"] = fallback.returncode
        result["version_source"] = spec["fallback_source"]
    result["version"] = version or "unavailable"
    if not version:
        result["version_error"] = "version probe returned no text"
    return result


def _write_wrapper(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from types import ModuleType\n"
        "package = ModuleType('claude_fleet_monitor')\n"
        "package.__path__ = ['/workspace/src/claude_fleet_monitor']\n"
        "sys.modules['claude_fleet_monitor'] = package\n"
        "from claude_fleet_monitor.hook import main\n"
        "main()\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _path_probe(
    spec: dict[str, object],
    wrapper: Path,
    env: dict[str, str],
    token: str,
) -> dict[str, object]:
    spaced_wrapper = WORK_DIR / "hook bin" / "claude-fleet-hook"
    spaced_wrapper.parent.mkdir(parents=True, exist_ok=True)
    _write_wrapper(spaced_wrapper)
    unquoted_session = f"path-unquoted-{token}-{spec['id']}"
    quoted_session = f"path-quoted-{token}-{spec['id']}"
    unquoted_command = (
        f"exec {spaced_wrapper} session-start --agent claude"
    )
    quoted_command = (
        f"exec {shlex.quote(str(spaced_wrapper))} session-start --agent claude"
    )
    unquoted = _run_shell(
        spec,
        unquoted_command,
        _expected_payload("session-start", unquoted_session, "claude")
        | {"session_id": unquoted_session},
        env,
        FIXTURE_CWD,
    )
    quoted = _run_shell(
        spec,
        quoted_command,
        _expected_payload("session-start", quoted_session, "claude")
        | {"session_id": quoted_session},
        env,
        FIXTURE_CWD,
    )
    quoted_records = _matching_records(FLEET_DIR, quoted_session)
    quoted_ok, quoted_mismatches, quoted_record = _check_record(
        "session-start",
        _expected_payload("session-start", quoted_session, "claude")
        | {"session_id": quoted_session},
        "claude",
        quoted_records,
    ) if quoted["returncode"] == 0 else (
        False,
        ["quoted command exited nonzero"],
        quoted_records[0] if quoted_records else None,
    )
    unquoted_failed = unquoted["returncode"] not in (0, None)
    probe = {
        "shell": spec["id"],
        "configured_command_form": "<path with spaces> session-start --agent claude",
        "unquoted": {
            "returncode": unquoted["returncode"],
            "observed_failure": unquoted_failed,
            "stderr": unquoted["stderr"],
            "expected": "failure with current unquoted CLI command construction",
        },
        "quoted": {
            "returncode": quoted["returncode"],
            "matched_records": len(quoted_records),
            "passed": quoted_ok,
            "observed": _record_view(quoted_record),
        },
        "passed": unquoted_failed and quoted_ok,
        "classification": "known-cli-hook-path-quoting-gap",
    }
    if quoted_mismatches:
        probe["quoted"]["mismatches"] = quoted_mismatches
    if not unquoted_failed:
        probe["unquoted"]["unexpected"] = True
    return probe


def _run_inside(args: argparse.Namespace) -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "tmp").mkdir(exist_ok=True)
    (WORK_DIR / "home").mkdir(exist_ok=True)
    (WORK_DIR / "config").mkdir(exist_ok=True)
    (WORK_DIR / "cache").mkdir(exist_ok=True)
    (WORK_DIR / "data").mkdir(exist_ok=True)
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_CWD.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    token = uuid.uuid4().hex[:10]
    source_hash = _tree_hash(SOURCE_MOUNT)
    source_matches = source_hash == args.source_tree_sha256
    wrapper = WORK_DIR / "hook-bin" / "claude-fleet-hook"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    _write_wrapper(wrapper)

    shell_records = []
    lifecycle_cases = []
    path_probes = []
    for spec in SHELLS:
        shell_record = _probe_versions(spec, env, FIXTURE_CWD)
        shell_records.append(shell_record)
        if shell_record["available"]:
            for agent in ("claude", "codex"):
                lifecycle_cases.append(
                    _lifecycle_case(spec, agent, wrapper, env, token)
                )
            path_probes.append(_path_probe(spec, wrapper, env, token))

    lifecycle_failures = [
        case for case in lifecycle_cases if not case["passed"]
    ]
    path_failures = [probe for probe in path_probes if not probe["passed"]]
    missing_shells = [
        shell["id"] for shell in shell_records if not shell["available"]
    ]
    hard_failures = [
        *(["source mount hash mismatch"] if not source_matches else []),
        *[f"missing shell: {shell}" for shell in missing_shells],
        *[
            f"lifecycle failure: {case['shell']}/{case['agent']}"
            for case in lifecycle_failures
        ],
        *[
            f"path probe failure: {probe['shell']}"
            for probe in path_failures
        ],
    ]
    result = "passed" if not hard_failures else "failed"
    evidence = {
        "schema_version": 1,
        "result": result,
        "run_type": "live-container-synthetic-emitter",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "mount": "src",
            "commit": args.source_commit,
            "tree_sha256": args.source_tree_sha256,
            "container_tree_sha256": source_hash,
            "mount_hash_matches": source_matches,
        },
        "container": {
            "image_reference": args.image,
            "network": "none",
            "root_read_only": True,
            "source_mount": "/workspace/src:ro",
            "validation_mount": "/validation:ro",
            "writable_mount": "/tmp/fleet-work:tmpfs",
            "agent_settings_mounted": False,
            "host_environment_inherited": False,
        },
        "fixture": {
            "cwd": str(FIXTURE_CWD),
            "cwd_features": ["spaces", "Unicode", "apostrophe"],
            "agents": ["claude", "codex"],
            "events": list(EVENTS),
            "record_matching": "JSON session_id field, filename-independent",
        },
        "shells": shell_records,
        "lifecycle_cases": lifecycle_cases,
        "path_probes": path_probes,
        "summary": {
            "shells_expected": len(SHELLS),
            "shells_available": len(SHELLS) - len(missing_shells),
            "lifecycle_cases": len(lifecycle_cases),
            "lifecycle_cases_passed": len(lifecycle_cases) - len(lifecycle_failures),
            "path_probes": len(path_probes),
            "path_probes_passed": len(path_probes) - len(path_failures),
            "hard_failures": hard_failures,
        },
        "limitations": [
            "Synthetic stdin payloads do not establish real Claude or Codex process behavior.",
            "Container execution cannot validate PID, tty, terminal detection, pane or tab selection, or OS window activation.",
            "The installer configuration files are not mounted or modified; the temporary Python entry point exercises the hook argument contract.",
            "The unquoted executable path probe records the current CLI hook path quoting gap as a known failure.",
        ],
    }
    print(MARKER + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
    return 0 if result == "passed" else 1


def _markdown(evidence: dict[str, object]) -> str:
    summary = evidence.get("summary", {})
    source = evidence.get("source", {})
    container = evidence.get("container", {})
    lifecycle_cases = evidence.get("lifecycle_cases", [])
    path_probes = evidence.get("path_probes", [])
    lifecycle_passed = summary.get(
        "lifecycle_cases_passed",
        sum(1 for case in lifecycle_cases if case.get("passed")),
    )
    path_passed = summary.get(
        "path_probes_passed",
        sum(1 for probe in path_probes if probe.get("passed")),
    )
    lines = [
        "# Shell validation evidence",
        "",
        f"Result: **{evidence['result']}**",
        f"Run type: `{evidence['run_type']}`",
        f"Generated: `{evidence['generated_at_utc']}`",
        "",
        "## Reproduction metadata",
        "",
        f"- Source commit: `{source.get('commit', 'unknown')}`",
        f"- Source tree SHA-256: `{source.get('tree_sha256', 'unknown')}`",
        f"- Mounted source hash matches: `{source.get('mount_hash_matches', 'unknown')}`",
        f"- Image reference: `{container.get('image_reference', 'unknown')}`",
        f"- Image ID: `{container.get('image_id', 'unknown')}`",
        f"- Image digest: `{container.get('image_digest', 'unknown')}`",
        f"- Container network: `{container.get('network', 'unknown')}`",
        f"- Read-only source mount: `{container.get('source_mount', 'unknown')}`",
        f"- Read-only validation mount: `{container.get('validation_mount', 'unknown')}`",
        f"- Writable path: `{container.get('writable_mount', 'unknown')}`",
        "",
        "## Shell matrix",
        "",
        "| Shell | Binary mode | Alias | Version | Available | Version source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for shell in evidence.get("shells", []):
        lines.append(
            f"| {shell['label']} | `{shell['argv']} {shell['mode']}` | {shell['alias']} | "
            f"`{shell['version']}` | `{shell['available']}` | {shell['version_source']} |"
        )
    lines.extend(
        [
            "",
            "## Lifecycle results",
            "",
            f"{lifecycle_passed}/{summary.get('lifecycle_cases', len(lifecycle_cases))} cases passed. Each case covered `session-start`, `prompt-submit`, `tool-use`, `permission-request`, `stop` and `session-end` for one agent. Records were selected by their JSON `session_id` value.",
            "",
            "| Shell | Agent | Result |",
            "| --- | --- | --- |",
        ]
    )
    for case in lifecycle_cases:
        lines.append(
            f"| {case['shell']} | {case['agent']} | `{'passed' if case['passed'] else 'failed'}` |"
        )
    lines.extend(
        [
            "",
            "## Executable path probe",
            "",
            f"{path_passed}/{summary.get('path_probes', len(path_probes))} probes observed the expected unquoted path failure and a passing quoted path. The unquoted form is the current CLI command construction gap for an executable directory containing spaces.",
            "",
            "| Shell | Unquoted return code | Unquoted failed | Quoted passed | Classification |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for probe in path_probes:
        lines.append(
            f"| {probe['shell']} | `{probe['unquoted']['returncode']}` | "
            f"`{probe['unquoted']['observed_failure']}` | `{probe['quoted']['passed']}` | "
            f"{probe['classification']} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in evidence.get("limitations", []))
    if summary.get("hard_failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in summary["hard_failures"])
    lines.append("")
    return "\n".join(lines)


def _run_host(args: argparse.Namespace) -> int:
    source_dir = Path(args.source_dir).resolve()
    validation_dir = Path(__file__).resolve().parent
    if not source_dir.is_dir():
        raise SystemExit(f"source directory does not exist: {source_dir}")
    source = _git_metadata(source_dir)
    image = _inspect_image(args.podman, args.image)
    command = [
        args.podman,
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--security-opt=label=disable",
        "--tmpfs",
        "/tmp/fleet-work:rw,size=64m",
        "--env",
        "HOME=/tmp/fleet-work/home",
        "--env",
        "TMPDIR=/tmp/fleet-work/tmp",
        "--env",
        "FLEET_DIR=/tmp/fleet-work/fleet",
        "--env",
        "PYTHONPATH=/workspace/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--env",
        "LANG=C.UTF-8",
        "--env",
        "LC_ALL=C.UTF-8",
        "--env",
        "XDG_CONFIG_HOME=/tmp/fleet-work/config",
        "--env",
        "XDG_CACHE_HOME=/tmp/fleet-work/cache",
        "--env",
        "XDG_DATA_HOME=/tmp/fleet-work/data",
        "--volume",
        f"{source_dir}:/workspace/src:ro",
        "--volume",
        f"{validation_dir}:/validation:ro",
        image["reference"],
        "python3",
        "/validation/run.py",
        "--inside",
        "--image",
        image["reference"],
        "--source-commit",
        str(source["commit"]),
        "--source-tree-sha256",
        str(source["tree_sha256"]),
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=args.timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        evidence = {
            "schema_version": 1,
            "result": "failed",
            "run_type": "container-launch-failure",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "container": {
                "image_reference": image["reference"],
                "image_id": image["id"],
                "image_digest": image["digest"],
            },
            "summary": {"hard_failures": [f"container launch: {error}"]},
        }
    else:
        evidence = None
        for line in reversed(process.stdout.splitlines()):
            if line.startswith(MARKER):
                evidence = json.loads(line[len(MARKER):])
                break
        if evidence is None:
            evidence = {
                "schema_version": 1,
                "result": "failed",
                "run_type": "container-no-evidence",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "container": {
                    "image_reference": image["reference"],
                    "image_id": image["id"],
                    "image_digest": image["digest"],
                },
                "summary": {
                    "hard_failures": [
                        f"container exited without evidence (return code {process.returncode})"
                    ]
                },
            }
        evidence["container"]["image_id"] = image["id"]
        evidence["container"]["image_digest"] = image["digest"]
        evidence["container"]["runner_returncode"] = process.returncode
        evidence["source"]["dirty"] = source["dirty"]
    output = Path(args.output)
    markdown = Path(args.markdown) if args.markdown else output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown.write_text(_markdown(evidence), encoding="utf-8")
    print(
        f"{evidence['result']}: {output} ({markdown}); "
        f"source {evidence.get('source', {}).get('commit', 'unknown')}; "
        f"image {image['id']} {image['digest']}"
    )
    return 0 if evidence["result"] == "passed" else 1


def _parser() -> argparse.ArgumentParser:
    script_dir = Path(__file__).resolve().parent
    repo_source = script_dir.parent.parent / "src"
    default_source = repo_source if repo_source.is_dir() else SOURCE_MOUNT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--podman", default="podman")
    parser.add_argument("--source-dir", default=str(default_source))
    parser.add_argument(
        "--output",
        default=str(script_dir / "evidence" / "latest.json"),
    )
    parser.add_argument("--markdown", default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-commit", default="unknown", help=argparse.SUPPRESS)
    parser.add_argument("--source-tree-sha256", default="", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.inside:
        return _run_inside(args)
    return _run_host(args)


if __name__ == "__main__":
    sys.exit(main())
