import subprocess

import pytest

from claude_fleet_monitor.terminal_apis import zellij
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.terminator import TerminatorAPI
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI

ZELLIJ_ENV = {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": "session"}
DETECT_PARENT = "claude_fleet_monitor.terminal_apis.tmux._detect_parent_terminal"


class WindowParent(TerminalAPI):
    name = "window-only"
    selection_supported = False

    def __init__(self, activate=True):
        self.activate = activate
        self.calls = []

    @staticmethod
    def detect():
        return False

    @staticmethod
    def capture_env():
        return {}

    def find_tab(self, pid, env):
        return None

    def find_activation_target(self, pid, env, tab_id):
        self.calls.append(("target", pid))
        return "window"

    def switch_tab(self, tab_id, env):
        pytest.fail("selection is unsupported")

    def raise_window(self, tab_id, env):
        self.calls.append(("raise", tab_id))
        return self.activate


@pytest.fixture(autouse=True)
def forbid_fallbacks(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("zellij focus must not start a process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(
        GenericAPI,
        "__init__",
        lambda self: pytest.fail("GenericAPI must not be constructed"),
    )


def test_zellij_parent_activation_is_truthful(monkeypatch):
    parent = WindowParent()
    monkeypatch.setattr(DETECT_PARENT, lambda pid: parent)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "partial"
    assert not result.selection.attempted
    assert result.activation.succeeded
    assert parent.calls == [("target", 101), ("raise", "window")]


def test_zellij_failed_parent_activation_is_not_success(monkeypatch):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: WindowParent(activate=False))

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert result.activation.attempted
    assert not result.activation.succeeded


def test_zellij_without_parent_reports_activation_detail(monkeypatch):
    monkeypatch.setattr(DETECT_PARENT, lambda pid: None)

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "no parent terminal emulator found for zellij"
    )


def test_zellij_in_terminator_reports_unsupported_parent(monkeypatch):
    for method in ("find_tab", "switch_tab", "raise_window", "focus_result"):
        monkeypatch.setattr(
            TerminatorAPI,
            method,
            lambda *args, **kwargs: pytest.fail("Terminator cannot focus"),
        )
    monkeypatch.setattr(DETECT_PARENT, lambda pid: TerminatorAPI())

    result = ZellijAPI().focus_result(101, dict(ZELLIJ_ENV))

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "parent terminal terminator does not support window activation"
    )


def test_zellij_raise_window_rejects_non_numeric_target(monkeypatch):
    monkeypatch.setattr(
        DETECT_PARENT, lambda pid: pytest.fail("no parent lookup for bad target")
    )

    assert not ZellijAPI().raise_window("not-a-pid", dict(ZELLIJ_ENV))


def test_zellij_without_env_has_no_activation_target(monkeypatch):
    monkeypatch.setattr(
        DETECT_PARENT, lambda pid: pytest.fail("no parent lookup without zellij env")
    )

    result = ZellijAPI().focus_result(101, {})

    assert result.state == "failed"
    assert not result.target_found
    assert not result.activation.attempted


def test_zellij_switch_tab_makes_no_subprocess_call():
    assert not ZellijAPI().switch_tab("1", dict(ZELLIJ_ENV))


def test_zellij_module_has_no_fallback_or_subprocess_imports():
    assert "GenericAPI" not in vars(zellij)
    assert "subprocess" not in vars(zellij)
