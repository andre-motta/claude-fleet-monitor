import subprocess

import pytest

from validation.pi import run_in_tmux


@pytest.mark.parametrize("failed_operation", ["set-option", "respawn-pane"])
def test_tmux_setup_failure_always_stops_server(
    tmp_path, monkeypatch, failed_operation
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if failed_operation in command:
            return subprocess.CompletedProcess(command, 2, "", "setup failed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(run_in_tmux.shutil, "which", lambda command: "/usr/bin/tmux")
    monkeypatch.setattr(run_in_tmux.subprocess, "run", run)

    assert run_in_tmux.run(10) == 2
    assert calls[-1][-1] == "kill-server"
