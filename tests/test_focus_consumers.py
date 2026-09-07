from types import SimpleNamespace

import pytest

from claude_fleet_monitor.models import FocusOperation, FocusResult


def _result(state):
    if state == "complete":
        operation = FocusOperation(True, True, "ok")
        return FocusResult(
            state=state,
            reason="done",
            target_found=True,
            selection=operation,
            activation=operation,
        )
    if state == "partial":
        return FocusResult(
            state=state,
            reason="window only",
            target_found=True,
            selection=FocusOperation.unavailable("unsupported"),
            activation=FocusOperation(True, True, "ok"),
        )
    return FocusResult(state=state, reason="no safe target")


@pytest.mark.parametrize(
    ("state", "message", "severity"),
    [
        ("complete", "Focused: repo", "information"),
        ("partial", "Partially focused: repo", "warning"),
        ("unavailable", "Focus Unavailable: repo: no safe target", "error"),
    ],
)
@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("claude_fleet_monitor.tui", "FleetMonitorApp"),
        ("claude_fleet_monitor.views.fleet_screen", "FleetScreen"),
    ],
)
def test_focus_consumer_notifies_completed_result(
    module_name, class_name, state, message, severity
):
    module = __import__(module_name, fromlist=[class_name])
    consumer_class = getattr(module, class_name)
    notifications = []
    consumer = SimpleNamespace(
        notify=lambda text, **kwargs: notifications.append((text, kwargs))
    )
    consumer_class._notify_focus_result(consumer, "repo", _result(state))
    assert notifications == [(message, {"severity": severity, "timeout": 3})]


class _ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("claude_fleet_monitor.tui", "FleetMonitorApp"),
        ("claude_fleet_monitor.views.fleet_screen", "FleetScreen"),
    ],
)
def test_focus_consumer_dispatches_worker_result_to_ui_thread(
    monkeypatch, module_name, class_name
):
    module = __import__(module_name, fromlist=[class_name])
    consumer_class = getattr(module, class_name)
    expected = _result("partial")
    callbacks = []

    def dispatch(callback, *args):
        callbacks.append((callback, args))

    consumer = SimpleNamespace(
        _notify_focus_result=lambda *args: None,
        call_from_thread=dispatch,
        app=SimpleNamespace(call_from_thread=dispatch),
    )
    monkeypatch.setattr(module, "focus_session", lambda identity: expected)
    monkeypatch.setattr(module.threading, "Thread", _ImmediateThread)
    session = SimpleNamespace(identity="canonical", repo="repo")
    consumer_class._do_focus(consumer, session)
    assert callbacks == [
        (consumer._notify_focus_result, ("repo", expected))
    ]
