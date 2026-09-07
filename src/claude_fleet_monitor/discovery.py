"""Cross-platform process discovery and bounded fleet session storage."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from claude_fleet_monitor.harnesses import ProcessIdentity, get_harness
from claude_fleet_monitor.models import SCHEMA_VERSION, SessionStatus, canonical_session_id

FLEET_DIR = Path(os.environ.get("FLEET_DIR", Path.home() / ".claude" / "fleet"))
MAX_EVENT_BYTES = 64 * 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_ID_LENGTH = 512
MAX_PATH_LENGTH = 4096
MAX_DETAIL_LENGTH = 512
MAX_TOOL_LENGTH = 256
MAX_ENV_ITEMS = 32
MAX_ENV_VALUE_LENGTH = 1024
MAX_FUTURE_SECONDS = 300


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int | None
    name: str
    executable: str
    argv: tuple[str, ...]
    cwd: str | None
    start_token: str


def _split_cmdline(raw: str) -> tuple[str, ...]:
    return tuple(part for part in raw.replace("\0", " ").split() if part)


def get_process_info(pid: int) -> ProcessInfo | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if sys.platform == "linux":
        try:
            proc = Path(f"/proc/{pid}")
            stat_text = (proc / "stat").read_text()
            after_name = stat_text.rsplit(") ", 1)[1].split()
            ppid = int(after_name[1])
            start_token = after_name[19]
            name = (proc / "comm").read_text().strip()
            raw_cmdline = (proc / "cmdline").read_bytes().decode(
                "utf-8", errors="replace"
            )
            argv = tuple(part for part in raw_cmdline.split("\0") if part)
            try:
                executable = os.path.basename(os.readlink(proc / "exe"))
            except OSError:
                executable = os.path.basename(argv[0]) if argv else name
            cwd = os.readlink(proc / "cwd")
        except (OSError, ValueError, IndexError):
            return None
        return ProcessInfo(
            pid=pid,
            ppid=ppid,
            name=name,
            executable=executable,
            argv=argv,
            cwd=cwd,
            start_token=start_token,
        )

    if sys.platform == "darwin":
        try:
            process = subprocess.run(
                ["ps", "-o", "ppid=", "-o", "comm=", "-o", "args=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if process.returncode != 0 or not process.stdout.strip():
                return None
            parts = process.stdout.strip().split(maxsplit=2)
            if len(parts) < 2:
                return None
            ppid = int(parts[0])
            executable_path = parts[1]
            argv = _split_cmdline(parts[2] if len(parts) > 2 else executable_path)
            cwd_result = subprocess.run(
                ["lsof", "-p", str(pid), "-Fn", "-a", "-d", "cwd"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            cwd = next(
                (line[1:] for line in cwd_result.stdout.splitlines() if line.startswith("n")),
                None,
            )
            started = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            return None
        return ProcessInfo(
            pid=pid,
            ppid=ppid,
            name=os.path.basename(executable_path),
            executable=os.path.basename(executable_path),
            argv=argv,
            cwd=cwd,
            start_token=started.stdout.strip(),
        )

    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        parts = line.strip().strip('"').split('\",\"') if line else []
        if len(parts) < 2 or parts[1] != str(pid):
            return None
        return ProcessInfo(
            pid=pid,
            ppid=None,
            name=parts[0],
            executable=parts[0],
            argv=(parts[0],),
            cwd=None,
            start_token="",
        )

    try:
        process = subprocess.run(
            ["ps", "-o", "ppid=", "-o", "comm=", "-o", "args=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0 or not process.stdout.strip():
        return None
    parts = process.stdout.strip().split(maxsplit=2)
    if len(parts) < 2:
        return None
    try:
        ppid = int(parts[0])
    except ValueError:
        return None
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=os.path.basename(parts[1]),
        executable=os.path.basename(parts[1]),
        argv=_split_cmdline(parts[2] if len(parts) > 2 else parts[1]),
        cwd=None,
        start_token="",
    )


def _get_process_info(pid):
    process = get_process_info(int(pid))
    if process is None:
        return None, None
    return process.cwd, " ".join(process.argv)


def process_matches_harness(process: ProcessInfo, harness_id: str) -> bool:
    harness = get_harness(harness_id)
    if harness is None or harness.process_identity is not ProcessIdentity.DISCOVERABLE:
        return False
    identities = {process.name.lower(), process.executable.lower()}
    if process.argv:
        identities.add(os.path.basename(process.argv[0]).lower())
    allowed = {name.lower() for name in harness.process_names}
    return bool(identities & allowed)


def find_ancestor_process(
    harness_id: str, start_pid: int | None = None
) -> ProcessInfo | None:
    current = start_pid if start_pid is not None else os.getppid()
    visited = set()
    while current and current > 1 and current not in visited:
        visited.add(current)
        process = get_process_info(current)
        if process is None:
            return None
        if process_matches_harness(process, harness_id):
            return process
        current = process.ppid or 0
    return None


def resolve_process_identity(
    harness_id: str, supplied_pid: int | None = None
) -> ProcessInfo | None:
    harness = get_harness(harness_id)
    if harness is None:
        return None
    if supplied_pid is None:
        return find_ancestor_process(harness_id)
    process = get_process_info(supplied_pid)
    if process is None:
        return None
    if harness.process_identity is ProcessIdentity.DISCOVERABLE:
        return process if process_matches_harness(process, harness_id) else None
    return process


def resolve_session_process(session: dict) -> ProcessInfo | None:
    try:
        pid = int(session.get("pid", ""))
    except (TypeError, ValueError):
        return None
    process = get_process_info(pid)
    if process is None:
        return None
    harness_id = session.get("harness_id", session.get("agent", "claude"))
    harness = get_harness(harness_id)
    if harness is None:
        return None
    if harness.process_identity is ProcessIdentity.DISCOVERABLE:
        if not process_matches_harness(process, harness_id):
            return None
    expected_start = session.get("process_start", "")
    if expected_start and process.start_token != expected_start:
        return None
    if session.get("instance_id") and not expected_start:
        return None
    return process


def _get_tty(pid):
    if sys.platform != "linux":
        return ""
    try:
        link = os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return ""
    match = re.search(r"pts/\d+", link)
    return match.group() if match else ""


def _find_agent_processes():
    processes = []
    try:
        if sys.platform == "win32":
            for harness_id in ("claude", "codex"):
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {harness_id}.exe", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.strip().splitlines():
                    parts = line.strip().strip('"').split('\",\"')
                    if len(parts) >= 2 and parts[0].lower() == f"{harness_id}.exe":
                        processes.append((harness_id, int(parts[1])))
            return processes
        for harness_id in ("claude", "codex"):
            harness = get_harness(harness_id)
            if harness is None:
                continue
            result = subprocess.run(
                ["pgrep", "-x", harness.process_names[0]],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                processes.extend(
                    (harness_id, int(pid))
                    for pid in result.stdout.strip().splitlines()
                    if pid
                )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return []
    return processes


def _store_available(create: bool = False) -> bool:
    try:
        if create:
            FLEET_DIR.mkdir(parents=True, exist_ok=True)
        return FLEET_DIR.is_dir() and not FLEET_DIR.is_symlink()
    except OSError:
        return False


def _record_path(canonical_id: str) -> Path:
    digest = canonical_id.rsplit(":", 1)[-1]
    return FLEET_DIR / f"fleet-v{SCHEMA_VERSION}-{digest}.json"


def _path_is_regular(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and not path.is_symlink()


def _read_record(path: Path) -> dict | None:
    if not _path_is_regular(path):
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_RECORD_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        return None
    return _validate_record(data)


def _valid_text(value, limit: int, *, allow_empty: bool = True) -> bool:
    if not isinstance(value, str):
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return (
        len(encoded) <= limit
        and (allow_empty or bool(value))
        and "\0" not in value
    )


def _validate_record(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    schema = data.get("schema_version", 0)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema not in (0, SCHEMA_VERSION):
        return None
    session_id = data.get("session_id", "")
    harness_id = data.get("harness_id", data.get("agent", "claude"))
    if not _valid_text(session_id, MAX_ID_LENGTH, allow_empty=False):
        return None
    if not _valid_text(harness_id, 64, allow_empty=False):
        return None
    checks = (
        (data.get("cwd", ""), MAX_PATH_LENGTH),
        (data.get("repo", ""), MAX_ID_LENGTH),
        (data.get("detail", ""), MAX_DETAIL_LENGTH),
        (data.get("tool", ""), MAX_TOOL_LENGTH),
        (str(data.get("pid", "")), 32),
        (data.get("terminal", ""), 64),
        (data.get("instance_id", ""), MAX_ID_LENGTH),
        (data.get("process_start", ""), 128),
        (data.get("canonical_id", ""), 128),
        (data.get("last_event", ""), MAX_ID_LENGTH),
        (data.get("status", "discovered"), 32),
        (data.get("source", "hook"), 32),
        (data.get("record_kind", ""), 32),
    )
    if any(not _valid_text(value, limit) for value, limit in checks):
        return None
    for key in ("ts", "started"):
        value = data.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            return None
    now = int(time.time())
    timestamp = data.get("ts", 0)
    if timestamp is not None and timestamp > now + MAX_FUTURE_SECONDS:
        return None
    sequence = data.get("sequence")
    if sequence is not None and (
        not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0
    ):
        return None
    arrival_sequence = data.get("arrival_sequence")
    if arrival_sequence is not None and (
        not isinstance(arrival_sequence, int)
        or isinstance(arrival_sequence, bool)
        or arrival_sequence < 1
    ):
        return None
    env = data.get("terminal_env", {})
    if not isinstance(env, dict) or len(env) > MAX_ENV_ITEMS:
        return None
    if any(
        not _valid_text(key, 128, allow_empty=False)
        or not _valid_text(value, MAX_ENV_VALUE_LENGTH)
        for key, value in env.items()
    ):
        return None
    normalized = dict(data)
    normalized["agent"] = harness_id
    normalized["harness_id"] = harness_id
    normalized["pid"] = str(data.get("pid", ""))
    normalized["ts"] = data.get("ts") if data.get("ts") is not None else 0
    normalized["status"] = data.get("status", "discovered")
    if normalized["pid"] and (
        not normalized["pid"].isdigit() or int(normalized["pid"]) <= 0
    ):
        return None
    if schema == SCHEMA_VERSION:
        if not normalized.get("instance_id") or not normalized.get("canonical_id"):
            return None
        if get_harness(harness_id) is None:
            return None
        if normalized.get("status") not in {status.value for status in SessionStatus}:
            return None
        target = normalized.get("focus_target", {})
        if target and not isinstance(target, dict):
            return None
        if isinstance(target, dict):
            kind = target.get("kind", "unavailable")
            target_terminal = target.get("terminal", "")
            desktop_target = target.get("desktop_target", "")
            target_env = target.get("terminal_env", {})
            if not isinstance(kind, str) or kind not in {
                "terminal", "desktop", "unavailable"
            }:
                return None
            if not _valid_text(target_terminal, 64):
                return None
            if not _valid_text(desktop_target, MAX_ID_LENGTH):
                return None
            if not isinstance(target_env, dict) or len(target_env) > MAX_ENV_ITEMS:
                return None
            if any(
                not _valid_text(key, 128, allow_empty=False)
                or not _valid_text(value, MAX_ENV_VALUE_LENGTH)
                for key, value in target_env.items()
            ):
                return None
    return normalized


@contextmanager
def _record_lock(canonical_id: str):
    digest = canonical_id.rsplit(":", 1)[-1]
    path = FLEET_DIR / f".fleet-v{SCHEMA_VERSION}-{digest}.lock"
    if path.exists() and not _path_is_regular(path):
        raise OSError("unsafe lock entry")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    locked = False
    try:
        deadline = time.monotonic() + 0.5
        if sys.platform == "win32":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("fleet record lock timed out")
                    time.sleep(0.01)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("fleet record lock timed out")
                    time.sleep(0.01)
        yield
    finally:
        if locked and sys.platform == "win32":
            import msvcrt
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        elif locked:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_record_atomic(path: Path, data: dict) -> None:
    if path.exists() and not _path_is_regular(path):
        raise OSError("unsafe fleet entry")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_RECORD_BYTES:
        raise ValueError("fleet record exceeds size limit")
    descriptor, temp_name = tempfile.mkstemp(
        dir=FLEET_DIR, prefix=".fleet-tmp-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def write_session_record(data: dict) -> bool:
    record = _validate_record(data)
    if record is None or record.get("schema_version") != SCHEMA_VERSION:
        return False
    canonical_id = record.get("canonical_id", "")
    expected = canonical_session_id(
        record["harness_id"], record["session_id"], record.get("instance_id", "")
    )
    if canonical_id != expected or not _store_available(create=True):
        return False
    path = _record_path(canonical_id)
    try:
        with _record_lock(canonical_id):
            existing = _read_record(path) if path.exists() else None
            incoming_sequence = record.get("sequence")
            if existing is not None and (
                existing.get("pid", "") != record.get("pid", "")
                or existing.get("process_start", "")
                != record.get("process_start", "")
            ):
                return False
            if existing is not None and existing.get("sequence") is not None:
                stored_sequence = existing.get("sequence")
                if incoming_sequence is None or incoming_sequence <= stored_sequence:
                    return False
            record["arrival_sequence"] = (
                int(existing.get("arrival_sequence", 0)) + 1 if existing else 1
            )
            _write_record_atomic(path, record)
    except (OSError, ValueError):
        return False
    return True


def read_session_record(
    harness_id: str, session_id: str, instance_id: str
) -> dict | None:
    canonical_id = canonical_session_id(harness_id, session_id, instance_id)
    if not _store_available():
        return None
    return _read_record(_record_path(canonical_id))


def discover_processes():
    if not _store_available(create=True):
        return
    now = int(time.time())
    for harness_id, pid in _find_agent_processes():
        process = get_process_info(pid)
        if process is None or not process.cwd or not process_matches_harness(process, harness_id):
            continue
        instance_id = (
            f"{pid}:{process.start_token}"
            if process.start_token
            else f"{pid}:unavailable"
        )
        session_id = f"proc-{pid}"
        canonical_id = canonical_session_id(harness_id, session_id, instance_id)
        path = _record_path(canonical_id)
        if path.exists():
            continue
        tty = _get_tty(pid)
        write_session_record({
            "schema_version": SCHEMA_VERSION,
            "record_kind": "process",
            "canonical_id": canonical_id,
            "session_id": session_id,
            "instance_id": instance_id,
            "harness_id": harness_id,
            "agent": harness_id,
            "repo": os.path.basename(process.cwd),
            "cwd": process.cwd,
            "pid": str(pid),
            "process_start": process.start_token,
            "status": "discovered",
            "detail": f"PID {pid} {tty}".strip(),
            "ts": now,
            "started": now,
            "source": "process",
            "tool": "",
            "terminal": "",
            "terminal_env": {},
        })


def _is_pid_alive(pid_str):
    try:
        return get_process_info(int(pid_str)) is not None
    except (TypeError, ValueError):
        return False


def _iter_record_paths():
    if not _store_available():
        return []
    try:
        return list(FLEET_DIR.glob("*.json"))
    except OSError:
        return []


def _cleanup_stale_sessions():
    now = int(time.time())
    removed = 0
    for path in _iter_record_paths():
        data = _read_record(path)
        if data is None:
            continue
        status_value = data.get("status", "")
        age = now - data.get("ts", now)
        should_remove = (
            (status_value == "ended" and age > 300)
            or (data.get("pid") and resolve_session_process(data) is None)
            or (not data.get("pid") and age > 600)
        )
        if should_remove:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def cleanup_ended_sessions():
    now = int(time.time())
    removed = 0
    for path in _iter_record_paths():
        data = _read_record(path)
        if (
            data is not None
            and data.get("status") == "ended"
            and now - data.get("ts", now) > 300
        ):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def read_stored_sessions() -> list[dict]:
    records = []
    for path in _iter_record_paths():
        data = _read_record(path)
        if data is not None:
            data["_legacy"] = data.get("schema_version", 0) == 0
            data["_process"] = (
                data.get("record_kind") == "process"
                or data.get("source") == "process"
                or path.name.startswith("proc-")
            )
            if data["_process"] and not data.get("pid"):
                match = re.fullmatch(r"proc-(\d+)", data["session_id"])
                if match:
                    data["pid"] = match.group(1)
            records.append(data)
    return records


def _deduplicate_records(records: list[dict]) -> list[dict]:
    new_native = {
        (record["harness_id"], record["session_id"])
        for record in records
        if not record["_legacy"] and not record["_process"]
    }
    filtered = [
        record
        for record in records
        if not (
            record["_legacy"]
            and not record["_process"]
            and (record["harness_id"], record["session_id"]) in new_native
        )
    ]
    hook_processes = {
        (record["harness_id"], record.get("pid", ""), record.get("process_start", ""))
        for record in filtered
        if not record["_process"] and record.get("pid")
    }
    result = []
    for record in filtered:
        if record["_process"]:
            exact = (
                record["harness_id"],
                record.get("pid", ""),
                record.get("process_start", ""),
            )
            legacy = (record["harness_id"], record.get("pid", ""), "")
            if exact in hook_processes or legacy in hook_processes:
                continue
        result.append(record)
    return result


def read_session_records() -> list[dict]:
    return _deduplicate_records(read_stored_sessions())


def read_sessions():
    discover_processes()
    _cleanup_stale_sessions()
    records = read_session_records()
    now = int(time.time())
    for record in records:
        record.pop("_legacy", None)
        record.pop("_process", None)
        record["age_seconds"] = max(0, now - record.get("ts", now))
        status_value = record.get("status", "")
        record["needs_attention"] = (
            status_value == "waiting"
            or (status_value == "idle" and record["age_seconds"] > 120)
        )
    records.sort(key=lambda record: record.get("repo", ""))
    return records
