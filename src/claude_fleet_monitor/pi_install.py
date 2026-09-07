"""Installation support for the optional Pi extension."""

import json
import os
import re
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path


MINIMUM_PI_VERSION = (0, 84, 4)
PI_CONFIG_NAME = "claude-fleet-monitor.json"
PI_CONFIG_OWNER = "claude-fleet-monitor"
PI_CONFIG_SCHEMA = 1
_MAX_CONFIG_BYTES = 16 * 1024
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\+[^\s]+)?$")


def _absolute_path(value):
    if not isinstance(value, str) or not value or "\0" in value:
        return False
    try:
        if len(value.encode("utf-8")) > 4096:
            return False
    except UnicodeError:
        return False
    return Path(value).is_absolute()


def pi_config_dir() -> Path:
    configured = os.environ.get("PI_CODING_AGENT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".pi" / "agent"


def pi_extension_path() -> Path:
    path = Path(str(files("claude_fleet_monitor").joinpath("pi_extension")))
    return path.resolve(strict=True)


def _read_owned_config(path: Path):
    if path.is_symlink():
        raise ValueError(f"Refusing to replace unrecognized Pi config: {path}")
    if not path.exists():
        return None
    try:
        if not path.is_file() or path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"Refusing to replace unrecognized Pi config: {path}") from error
    if (
        not isinstance(value, dict)
        or value.get("owner") != PI_CONFIG_OWNER
        or value.get("schema_version") != PI_CONFIG_SCHEMA
        or not _absolute_path(value.get("hook_path"))
        or not _absolute_path(value.get("extension_path"))
    ):
        raise ValueError(f"Refusing to replace unrecognized Pi config: {path}")
    managed_paths = value.get("managed_paths")
    if (
        not isinstance(managed_paths, list)
        or len(managed_paths) > 64
        or any(not _absolute_path(item) for item in managed_paths)
        or value["extension_path"] not in managed_paths
    ):
        raise ValueError(f"Refusing to replace unrecognized Pi config: {path}")
    return value


def _save_owned_config(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _isolated_version_environment():
    temporary = tempfile.TemporaryDirectory(prefix="fleet-pi-version-")
    root = Path(temporary.name)
    environment = os.environ.copy()
    environment.update({
        "HOME": str(root),
        "USERPROFILE": str(root),
        "PI_CODING_AGENT_DIR": str(root / "config"),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
    })
    return temporary, environment


def detect_pi_version(pi_command: str):
    temporary, environment = _isolated_version_environment()
    try:
        result = subprocess.run(
            [pi_command, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        temporary.cleanup()
    if result.returncode != 0:
        return None
    match = _VERSION_PATTERN.fullmatch(result.stdout.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _run_pi_package(pi_command: str, operation: str, package_path: Path):
    try:
        return subprocess.run(
            [pi_command, operation, str(package_path), "--no-approve"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"  Could not {operation} Pi extension: {error}")
        return None


def _remove_succeeded(result):
    if result is None:
        return False
    return result.returncode == 0 or "No matching package found" in result.stderr


def install_pi(pi_command: str, hook_command: str) -> bool:
    config_path = pi_config_dir() / PI_CONFIG_NAME
    try:
        previous = _read_owned_config(config_path)
    except ValueError as error:
        print(f"  {error}")
        return False
    version = detect_pi_version(pi_command)
    if version is None:
        print(
            "  Pi version is unrecognized or prerelease; stable Pi 0.84.4 "
            "or newer is required"
        )
        return False
    if version < MINIMUM_PI_VERSION:
        minimum = ".".join(str(part) for part in MINIMUM_PI_VERSION)
        actual = ".".join(str(part) for part in version)
        print(f"  Pi {actual} is unsupported; Pi {minimum} or newer is required")
        return False

    try:
        extension_path = pi_extension_path()
        hook_path = Path(hook_command).expanduser().resolve(strict=True)
    except OSError as error:
        print(f"  Could not resolve Pi extension command: {error}")
        return False

    old_paths = []
    if previous is not None:
        candidates = previous.get("managed_paths", [])
        if isinstance(candidates, list):
            old_paths.extend(item for item in candidates if isinstance(item, str))
        old_extension = previous.get("extension_path")
        if isinstance(old_extension, str):
            old_paths.append(old_extension)
    managed_paths = list(dict.fromkeys([*old_paths, str(extension_path)]))
    config = {
        "schema_version": PI_CONFIG_SCHEMA,
        "owner": PI_CONFIG_OWNER,
        "hook_path": str(hook_path),
        "extension_path": str(extension_path),
        "managed_paths": managed_paths,
    }
    try:
        _save_owned_config(config_path, config)
    except OSError as error:
        print(f"  Could not write Pi extension config: {error}")
        return False

    result = _run_pi_package(pi_command, "install", extension_path)
    if result is None or result.returncode != 0:
        if previous is None:
            try:
                config_path.unlink()
            except OSError:
                pass
        else:
            try:
                _save_owned_config(config_path, previous)
            except OSError:
                pass
        detail = result.stderr.strip() if result is not None else ""
        if detail:
            print(f"  Could not install Pi extension: {detail}")
        return False

    remaining = [str(extension_path)]
    for old_path in dict.fromkeys(old_paths):
        if old_path == str(extension_path):
            continue
        removal = _run_pi_package(pi_command, "remove", Path(old_path))
        if not _remove_succeeded(removal):
            remaining.append(old_path)
            print(f"  Kept previous Pi extension reference for retry: {old_path}")
    config["managed_paths"] = remaining
    try:
        _save_owned_config(config_path, config)
    except OSError as error:
        print(f"  Pi installed, but its Fleet config could not be finalized: {error}")
        return False
    print(f"  Installed Pi extension from {extension_path}")
    return True


def uninstall_pi(pi_command: str | None) -> bool:
    config_path = pi_config_dir() / PI_CONFIG_NAME
    try:
        config = _read_owned_config(config_path)
    except ValueError as error:
        print(f"  {error}")
        return False
    if config is None:
        print("  Pi extension is not managed by Claude Fleet Monitor")
        return True
    if pi_command is None:
        print("  Pi is required to remove its managed extension reference")
        return False

    paths = config.get("managed_paths", [])
    if not isinstance(paths, list):
        paths = []
    extension_path = config.get("extension_path")
    if isinstance(extension_path, str):
        paths.append(extension_path)
    remaining = []
    for value in dict.fromkeys(item for item in paths if isinstance(item, str)):
        result = _run_pi_package(pi_command, "remove", Path(value))
        if not _remove_succeeded(result):
            remaining.append(value)
    if remaining:
        config["managed_paths"] = remaining
        try:
            _save_owned_config(config_path, config)
        except OSError:
            pass
        print("  Could not remove every managed Pi extension reference")
        return False
    try:
        config_path.unlink()
    except OSError as error:
        print(f"  Could not remove Pi extension config: {error}")
        return False
    print("  Removed Pi extension")
    return True
