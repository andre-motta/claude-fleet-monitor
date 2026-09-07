import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.mark.skipif(
    importlib.util.find_spec("hatchling") is None,
    reason="hatchling is unavailable for the wheel packaging check",
)
def test_wheel_contains_loadable_pi_extension(tmp_path):
    root = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel", str(root),
            "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheel_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_CLAUDE_FLEET_MONITOR": "0.0.0",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert "claude_fleet_monitor/pi_extension/package.json" in names
        assert (
            "claude_fleet_monitor/pi_extension/extensions/fleet-monitor.js"
            in names
        )
        extracted = tmp_path / "extracted"
        archive.extractall(extracted)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from claude_fleet_monitor.pi_install import pi_extension_path; "
            "print(pi_extension_path())",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(extracted)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).is_relative_to(extracted)
