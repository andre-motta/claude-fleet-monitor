"""Failure controls for the isolated tmux validator's process cleanup."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

if sys.platform == "linux":
    _spec = importlib.util.spec_from_file_location(
        "tmux_validation", Path(__file__).parents[1] / "validation" / "tmux.py"
    )
    validator = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(validator)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux process birth tokens")


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("tmux", 5)])
def test_cleanup_terminates_owned_child_when_tmux_shutdown_fails(failure):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        def fail(*args, **kwargs):
            raise failure

        birth = validator.process_identity(process.pid)
        assert birth is not None
        validator.cleanup(fail, {process.pid: birth}, [])
        assert process.wait(timeout=3) != 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)


def test_cleanup_does_not_signal_reused_pid():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        validator.cleanup(lambda *args, **kwargs: None, {process.pid: "different-birth"}, [])
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=3)
