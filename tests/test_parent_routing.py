import pytest

from claude_fleet_monitor.terminal_apis import parent as parent_routing
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from claude_fleet_monitor.terminal_apis.generic import GenericAPI
from claude_fleet_monitor.terminal_apis.parent import (
    ParentActivation,
    activate_parent,
)
from claude_fleet_monitor.terminal_apis.terminator import TerminatorAPI


class RecordingParent(TerminalAPI):
    name = "recording"

    def __init__(self, select=True, activate=True, verify=False, target="tab"):
        self.calls = []
        self.select = select
        self.activate = activate
        self.verify = verify
        self.target = target

    @staticmethod
    def detect():
        return False

    @staticmethod
    def capture_env():
        return {}

    def find_tab(self, pid, terminal_env):
        self.calls.append(("find", pid, terminal_env))
        return self.target

    def find_activation_target(self, pid, terminal_env, tab_id):
        self.calls.append(("target", pid, tab_id))
        return f"window-for-{tab_id}" if tab_id else "window"

    def switch_tab(self, tab_id, terminal_env):
        self.calls.append(("select", tab_id))
        return self.select

    def raise_window(self, tab_id, terminal_env):
        self.calls.append(("raise", tab_id))
        return self.activate

    def verify_selection(self, tab_id, terminal_env):
        self.calls.append(("verify", tab_id))
        return self.verify

    def prepare_selection_after_activation(self):
        self.calls.append(("prepare",))


class DeferredParent(RecordingParent):
    deferred_selection_readback = True


class ActivationFirstParent(RecordingParent):
    activation_before_selection = True


class SelectionUnsupportedParent(RecordingParent):
    selection_supported = False


def _operations(parent):
    return [call[0] for call in parent.calls]


def test_deferred_parent_with_stale_readback_is_raised_then_verified():
    parent = DeferredParent(select=False, verify=True)

    assert activate_parent(parent, 200)
    assert _operations(parent) == ["find", "target", "select", "raise", "verify"]
    assert parent.calls[0] == ("find", 200, {})


def test_deferred_parent_with_failed_verification_is_not_success():
    parent = DeferredParent(select=False, verify=False)

    assert not activate_parent(parent, 200)
    assert _operations(parent) == ["find", "target", "select", "raise", "verify"]


def test_deferred_parent_with_failed_activation_is_not_success():
    parent = DeferredParent(select=True, activate=False)

    assert not activate_parent(parent, 200)
    assert "verify" not in _operations(parent)


def test_strict_parent_with_failed_selection_is_never_raised():
    parent = RecordingParent(select=False, verify=True)

    assert not activate_parent(parent, 200)
    assert _operations(parent) == ["find", "select"]


def test_strict_parent_without_tab_is_never_raised():
    parent = RecordingParent(target=None)

    assert not activate_parent(parent, 200)
    assert _operations(parent) == ["find"]


def test_strict_parent_selects_then_raises_activation_target():
    parent = RecordingParent()

    assert activate_parent(parent, 200)
    assert parent.calls == [
        ("find", 200, {}),
        ("select", "tab"),
        ("target", 200, "tab"),
        ("raise", "window-for-tab"),
    ]


def test_strict_parent_with_failed_raise_is_not_success():
    assert not activate_parent(RecordingParent(activate=False), 200)


def test_activation_first_parent_is_activated_before_selection():
    parent = ActivationFirstParent()

    assert activate_parent(parent, 200)
    assert _operations(parent) == ["find", "target", "raise", "prepare", "select"]


def test_activation_first_parent_requires_selection():
    parent = ActivationFirstParent(select=False)

    assert not activate_parent(parent, 200)


def test_activation_first_parent_skips_selection_when_activation_fails():
    parent = ActivationFirstParent(activate=False)

    assert not activate_parent(parent, 200)
    assert "select" not in _operations(parent)


def test_selection_unsupported_parent_raises_without_selecting():
    parent = SelectionUnsupportedParent(target=None)

    assert activate_parent(parent, 200)
    assert _operations(parent) == ["find", "target", "raise"]
    assert ("raise", "window") in parent.calls


def test_selection_unsupported_parent_with_failed_activation_is_not_success():
    parent = SelectionUnsupportedParent(target=None, activate=False)

    assert not activate_parent(parent, 200)


def test_activation_unsupported_parent_makes_no_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("an activation-unsupported parent must not be called")

    for method in (
        "find_tab",
        "find_activation_target",
        "switch_tab",
        "raise_window",
        "focus_result",
    ):
        monkeypatch.setattr(TerminatorAPI, method, forbidden)

    assert not activate_parent(TerminatorAPI(), 200)


def test_missing_parent_is_not_success():
    assert not activate_parent(None, 200)


@pytest.mark.parametrize(
    ("parent_class", "method"),
    [
        (RecordingParent, "find_tab"),
        (RecordingParent, "switch_tab"),
        (RecordingParent, "find_activation_target"),
        (RecordingParent, "raise_window"),
        (DeferredParent, "switch_tab"),
        (DeferredParent, "raise_window"),
        (ActivationFirstParent, "raise_window"),
        (ActivationFirstParent, "switch_tab"),
        (SelectionUnsupportedParent, "find_activation_target"),
        (SelectionUnsupportedParent, "raise_window"),
    ],
)
def test_parent_exception_is_not_success(monkeypatch, parent_class, method):
    def explode(*args, **kwargs):
        raise RuntimeError("parent failed")

    parent = parent_class()
    monkeypatch.setattr(parent, method, explode)

    assert not activate_parent(parent, 200)


def test_focus_result_exception_is_not_success(monkeypatch):
    parent = DeferredParent()
    monkeypatch.setattr(
        parent,
        "focus_result",
        lambda *args: (_ for _ in ()).throw(RuntimeError("parent failed")),
    )

    assert not activate_parent(parent, 200)


def test_duck_typed_strict_parent_raises_its_tab():
    calls = []

    class Parent:
        selection_supported = True

        def find_tab(self, pid, env):
            calls.append(("find", pid))
            return "tab"

        def switch_tab(self, tab_id, env):
            calls.append(("select", tab_id))
            return True

        def raise_window(self, tab_id, env):
            calls.append(("raise", tab_id))
            return True

    assert activate_parent(Parent(), 200)
    assert calls == [("find", 200), ("select", "tab"), ("raise", "tab")]


def test_routing_never_constructs_generic_api(monkeypatch):
    monkeypatch.setattr(
        GenericAPI,
        "__init__",
        lambda self: pytest.fail("GenericAPI must not be constructed"),
    )

    for parent in (
        None,
        RecordingParent(select=False),
        DeferredParent(activate=False),
        SelectionUnsupportedParent(activate=False),
    ):
        assert not activate_parent(parent, 200)
    assert "GenericAPI" not in vars(parent_routing)


def test_deferred_parent_with_unconfirmed_tab_reports_activation():
    outcome = activate_parent(DeferredParent(select=False, verify=False), 200)

    assert outcome == ParentActivation(
        activated=True,
        confirmed=False,
        detail="parent terminal recording raised its window but could not "
        "confirm the tab",
    )
    assert not outcome


def test_activation_first_parent_with_failed_selection_reports_activation():
    outcome = activate_parent(ActivationFirstParent(select=False), 200)

    assert outcome.activated
    assert not outcome.confirmed


@pytest.mark.parametrize(
    "parent",
    [
        DeferredParent(select=False, verify=True),
        ActivationFirstParent(),
        SelectionUnsupportedParent(target=None),
        RecordingParent(),
    ],
)
def test_complete_parent_protocol_is_activated_and_confirmed(parent):
    outcome = activate_parent(parent, 200)

    assert outcome.activated
    assert outcome.confirmed
    assert outcome.detail == "parent terminal recording activated"


@pytest.mark.parametrize(
    "parent",
    [
        RecordingParent(select=False),
        RecordingParent(target=None),
        RecordingParent(activate=False),
        DeferredParent(activate=False),
        ActivationFirstParent(activate=False),
        SelectionUnsupportedParent(target=None, activate=False),
    ],
)
def test_parent_without_raised_window_is_not_activated(parent):
    assert activate_parent(parent, 200) == ParentActivation(
        detail="parent terminal recording did not activate"
    )


def test_strict_parent_exception_after_selection_is_not_activated(monkeypatch):
    parent = RecordingParent()
    monkeypatch.setattr(
        parent,
        "raise_window",
        lambda *args: (_ for _ in ()).throw(RuntimeError("parent failed")),
    )

    outcome = activate_parent(parent, 200)

    assert not outcome.activated
    assert outcome.detail == "parent terminal recording did not activate"


def test_missing_and_unsupported_parents_report_their_reason():
    assert activate_parent(None, 200).detail == (
        "no parent terminal emulator found"
    )
    assert activate_parent(TerminatorAPI(), 200) == ParentActivation(
        detail="parent terminal terminator does not support window activation"
    )
