"""Shared qdbus resolution, calls and one-shot KWin scripts."""

import contextlib
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable

QDBUS_CANDIDATES = ("qdbus", "qdbus6", "qdbus-qt6")


class KWinScriptError(RuntimeError):
    """A KWin script could not be loaded or run; the message is the detail."""


def resolve_qdbus() -> str | None:
    for candidate in QDBUS_CANDIDATES:
        try:
            executable = shutil.which(candidate)
        except OSError:
            continue
        if executable:
            return executable
    return None


def run_qdbus(
    executable: str | None,
    arguments: list[str],
    *,
    timeout: float,
    text: bool,
) -> subprocess.CompletedProcess | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *arguments],
            capture_output=True,
            text=text,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result


def qdbus_text(executable: str, arguments: list[str]) -> str | None:
    result = run_qdbus(executable, arguments, timeout=2, text=True)
    if result is None:
        return None
    return (result.stdout or "").strip()


def is_number(value: str | None) -> bool:
    return bool(value) and value.isascii() and value.isdigit()


def bus_owner_pid(executable: str, service: str) -> int | None:
    owner = qdbus_text(
        executable,
        [
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.GetConnectionUnixProcessID",
            service,
        ],
    )
    return int(owner) if is_number(owner) else None


def run_kwin_script(
    executable: str,
    script: str,
    plugin_prefix: str,
    *,
    plugin: str | None = None,
    after_run: Callable[[], object] | None = None,
) -> object:
    """Load, run and always unload script under a unique KWin plugin name.

    KWin offers no result channel, so returning only means the script ran;
    callers must confirm any effect independently. after_run runs before the
    unload and its value is returned.
    """
    if plugin is None:
        plugin = f"{plugin_prefix}-{uuid.uuid4().hex}"
    descriptor, path = tempfile.mkstemp(suffix=".js")
    try:
        try:
            script_file = os.fdopen(descriptor, "w")
        except BaseException:
            os.close(descriptor)
            raise
        with script_file:
            script_file.write(script)
        loaded = qdbus_text(
            executable,
            [
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                path,
                plugin,
            ],
        )
        if not is_number(loaded):
            raise KWinScriptError("KWin script could not be loaded")
        ran = run_qdbus(
            executable,
            [
                "org.kde.KWin",
                f"/Scripting/Script{loaded}",
                "org.kde.kwin.Script.run",
            ],
            timeout=5,
            text=False,
        )
        if ran is None:
            raise KWinScriptError("KWin script could not be run")
        return after_run() if after_run is not None else None
    finally:
        run_qdbus(
            executable,
            [
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.unloadScript",
                plugin,
            ],
            timeout=5,
            text=False,
        )
        with contextlib.suppress(OSError):
            os.unlink(path)
