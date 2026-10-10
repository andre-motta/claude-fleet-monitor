"""Safety controls for the isolated live zellij validator."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only validator")

if sys.platform == "linux":
    _probe_spec = importlib.util.spec_from_file_location(
        "probe_terminals", ROOT / "validation" / "probe_terminals.py"
    )
    _probe = importlib.util.module_from_spec(_probe_spec)
    _probe_spec.loader.exec_module(_probe)
    sys.modules.setdefault("probe_terminals", _probe)
    _spec = importlib.util.spec_from_file_location(
        "zellij_validation", ROOT / "validation" / "zellij.py"
    )
    validator = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(validator)


@linux_only
def test_validator_requires_zellij(monkeypatch):
    monkeypatch.setattr(validator.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="requires Linux and zellij"):
        validator.validate(write=False)


@linux_only
def test_isolated_env_never_inherits_session_markers(monkeypatch, tmp_path):
    monkeypatch.setenv("ZELLIJ", "0")
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "andre")
    monkeypatch.setenv("ZELLIJ_SOCKET_DIR", "/run/user/1000/zellij")
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")

    env = validator.isolated_env(tmp_path)

    assert "ZELLIJ" not in env and "ZELLIJ_SESSION_NAME" not in env and "TMUX" not in env
    for key in validator.ISOLATION_KEYS:
        assert env[key].startswith(str(tmp_path))


@linux_only
def test_cleanup_terminates_owned_process_and_removes_temp_dir(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        validator, "run", lambda argv, env=None: calls.append((argv, env))
    )
    root = tmp_path / "root"
    root.mkdir()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        tracker = validator.Tracker([str(root)])
        tracker.add(process.pid, "fixture")

        result = validator.cleanup(root, ("fleet-z5-x",), tracker)

        assert process.wait(timeout=3) != 0
        assert result["survivors"] == 0
        assert result["temp_dir_removed"]
        assert [argv[1] for argv, _ in calls] == ["kill-session", "delete-session"]
        assert all(env["ZELLIJ_SOCKET_DIR"] == str(root / "sock") for _, env in calls)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


@linux_only
def test_cleanup_does_not_signal_unowned_process(monkeypatch, tmp_path):
    monkeypatch.setattr(validator, "run", lambda argv, env=None: None)
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        validator.cleanup(tmp_path / "missing", (), validator.Tracker([str(tmp_path)]))
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=3)


@linux_only
@pytest.mark.parametrize("private", ["home", "tmp"])
def test_public_text_flags_private_paths(private):
    value = str(Path.home()) if private == "home" else "/tmp/fleet-zellij-validation-x"

    _, leaks = validator.public_text({"path": value}, lambda text: text)

    assert leaks
