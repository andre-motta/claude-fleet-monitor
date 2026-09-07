import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import konsole


def _result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


def _executable(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX executable fixtures")
def test_resolve_qdbus_uses_path_priority_and_fallback(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    qdbus = _executable(bin_dir, "qdbus")
    qdbus6 = _executable(bin_dir, "qdbus6")
    qdbus_qt6 = _executable(bin_dir, "qdbus-qt6")
    monkeypatch.setenv("PATH", str(bin_dir))

    assert konsole._resolve_qdbus() == str(qdbus)
    qdbus.unlink()
    assert konsole._resolve_qdbus() == str(qdbus6)
    qdbus6.unlink()
    assert konsole._resolve_qdbus() == str(qdbus_qt6)


def test_missing_qdbus_is_safe_for_all_operations(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: None)
    api = konsole.KonsoleAPI()

    assert api._find_service() is None
    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    assert not api.switch_tab("org.kde.konsole|1|2", {})
    assert not api.raise_window("org.kde.konsole|1|2", {})
    assert not api._raise_by_kwin_title("Konsole")


def test_disappearing_qdbus_is_safe(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    api = konsole.KonsoleAPI()

    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    assert not api.switch_tab("org.kde.konsole|1|2", {})
    assert not api.raise_window("org.kde.konsole|1|2", {})
    assert not api._raise_by_kwin_title("Konsole")


def test_nonzero_qdbus_output_cannot_create_target_or_success(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: _result(
            1, "org.kde.konsole-123\n/Sessions/2\n/Windows/3\n42\n17\n"
        ),
    )
    api = konsole.KonsoleAPI()

    assert api._find_service() is None
    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    assert not api.switch_tab("org.kde.konsole|1|2", {})
    assert not api.raise_window("org.kde.konsole|1|2", {})


def test_qdbus_timeout_cannot_create_target_or_success(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            konsole.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        ),
    )
    api = konsole.KonsoleAPI()

    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    assert not api.switch_tab("org.kde.konsole|1|2", {})
    assert not api.raise_window("org.kde.konsole|1|2", {})
    assert not api._raise_by_kwin_title("Konsole")


def test_find_tab_selects_valid_pid_and_window(monkeypatch):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command == [executable, "org.kde.konsole-123"]:
            return _result(0, "/Sessions/2\n/Windows/7\n")
        if command[-1] == "org.kde.konsole.Session.foregroundProcessId":
            return _result(0, "99\n")
        if command[-1] == "org.kde.konsole.Session.processId":
            return _result(0, "42\n")
        if command[-1] == "org.kde.konsole.Window.sessionList":
            return _result(0, "2\n")
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)
    tab_id = konsole.KonsoleAPI().find_tab(
        42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole-123"}
    )

    assert tab_id == "org.kde.konsole-123|7|2"
    assert all(command[0] == executable for command in calls)


def test_switch_tab_verifies_current_session(monkeypatch):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-2] == "org.kde.konsole.Window.setCurrentSession":
            return _result(0)
        if command[-1] == "org.kde.konsole.Window.currentSession":
            return _result(0, "2\n")
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    assert konsole.KonsoleAPI().switch_tab(
        "org.kde.konsole-123|7|2", {}
    )
    assert len(calls) == 2
    assert all(command[0] == executable for command in calls)


@pytest.mark.parametrize(
    ("returncode", "stdout"), [(0, "99\n"), (1, "2\n")]
)
def test_switch_tab_rejects_stale_or_failed_readback(
    monkeypatch, returncode, stdout
):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)

    def run(command, **kwargs):
        if command[-2] == "org.kde.konsole.Window.setCurrentSession":
            return _result(0)
        if command[-1] == "org.kde.konsole.Window.currentSession":
            return _result(returncode, stdout)
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    assert not konsole.KonsoleAPI().switch_tab(
        "org.kde.konsole-123|7|2", {}
    )


def test_kwin_uses_one_resolved_binary_and_cleans_script(monkeypatch):
    executable = "/usr/bin/qdbus-qt6"
    which_calls = []
    monkeypatch.setattr(
        konsole.shutil,
        "which",
        lambda name: which_calls.append(name) or (
            executable if name == "qdbus-qt6" else None
        ),
    )
    calls = []
    script_paths = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == "1":
            return _result(0, "Konsole\n")
        if command[-2] == "org.kde.kwin.Scripting.loadScript":
            script_paths.append(command[-1])
            assert os.path.exists(command[-1])
            return _result(0, "11\n")
        if command[-1] == "org.kde.kwin.Script.run":
            return _result(0)
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)
    assert not konsole.KonsoleAPI().raise_window(
        "org.kde.konsole-123|7|2", {}
    )

    assert which_calls == ["qdbus", "qdbus6", "qdbus-qt6"]
    assert len(calls) == 3
    assert all(command[0] == executable for command in calls)
    assert script_paths and not os.path.exists(script_paths[0])
