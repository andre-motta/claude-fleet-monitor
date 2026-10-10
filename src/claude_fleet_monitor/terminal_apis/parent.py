"""Activate the terminal emulator hosting a multiplexer client.

Each parent follows its own protocol. Parents that activate before selecting,
cannot select, or only confirm selection after activation run their own
focus_result. Every other parent keeps the strict order in which a failed
selection never raises the window.
"""

from dataclasses import dataclass

from claude_fleet_monitor.terminal_apis.base import TerminalAPI

MAX_DETAIL_CHARS = 120
_GENERIC_DETAILS = {"window activation", "tab or pane selection"}


@dataclass(frozen=True)
class ParentActivation:
    """Outcome of routing activation through a parent terminal.

    activated means a parent window may have been raised: activation
    succeeded or a raise request was sent. confirmed means the parent's full
    protocol succeeded, including tab selection when it supports one. Callers
    must stop trying other parents once activated is True, since another
    parent could raise a second window.
    """

    activated: bool = False
    confirmed: bool = False
    detail: str = ""

    def __bool__(self) -> bool:
        return self.confirmed


def parent_activation_supported(parent) -> bool:
    """Whether parent can activate from a multiplexer client pid alone."""
    return bool(
        getattr(
            parent,
            "parent_activation_supported",
            getattr(parent, "activation_supported", True),
        )
    )


def _name(parent) -> str:
    return getattr(parent, "name", "unknown")


def unsupported_detail(parent) -> str:
    """Explain why parent cannot activate a window."""
    if _name(parent) == "generic":
        return "parent terminal emulator has no Fleet adapter"
    return _describe(parent, "does not support window activation")


def _describe(parent, summary: str, detail: str = "") -> str:
    text = f"parent terminal {_name(parent)} {summary}"
    detail = " ".join(str(detail).split())
    if not detail or detail in _GENERIC_DETAILS:
        return text
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 3] + "..."
    return f"{text} ({detail})"


def _confirmed(parent) -> ParentActivation:
    return ParentActivation(True, True, _describe(parent, "activated"))


def _unconfirmed(parent, detail: str) -> ParentActivation:
    return ParentActivation(
        True,
        False,
        _describe(
            parent, "may have raised its window but could not confirm it", detail
        ),
    )


def _not_activated(parent, detail: str = "") -> ParentActivation:
    return ParentActivation(detail=_describe(parent, "did not activate", detail))


def _delegate(parent: TerminalAPI, client_pid: int) -> ParentActivation:
    selection_supported = getattr(parent, "selection_supported", True)
    try:
        parent.raise_requested = False
        result = parent.focus_result(client_pid, {})
    except Exception as error:
        if getattr(parent, "raise_requested", False):
            return _unconfirmed(parent, str(error))
        return _not_activated(parent, str(error))
    if result.activation.succeeded:
        if result.selection.succeeded or not selection_supported:
            return _confirmed(parent)
        return ParentActivation(
            True,
            False,
            _describe(
                parent,
                "raised its window but could not confirm the tab",
                result.selection.detail,
            ),
        )
    if getattr(parent, "raise_requested", False):
        return _unconfirmed(parent, result.activation.detail)
    return _not_activated(parent, result.activation.detail)


def _strict(parent: TerminalAPI, client_pid: int) -> ParentActivation:
    requested = False
    try:
        parent_tab = parent.find_tab(client_pid, {})
        if not parent_tab:
            return _not_activated(parent, "tab was not found")
        if not parent.switch_tab(parent_tab, {}):
            return _not_activated(parent, "tab selection failed")
        find_target = getattr(parent, "find_activation_target", None)
        target = (
            find_target(client_pid, {}, parent_tab) if find_target else parent_tab
        )
        if not target:
            return _not_activated(parent, "window activation target was not found")
        requested = True
        if parent.raise_window(target, {}):
            return _confirmed(parent)
        return _unconfirmed(parent, "window activation was not confirmed")
    except Exception as error:
        if requested:
            return _unconfirmed(parent, str(error))
        return _not_activated(parent, str(error))


def activate_parent(parent: TerminalAPI | None, client_pid: int) -> ParentActivation:
    """Activate the parent window and report what was verifiably achieved."""
    if parent is None:
        return ParentActivation(detail="no parent terminal emulator found")
    if not parent_activation_supported(parent):
        return ParentActivation(detail=unsupported_detail(parent))
    if (
        getattr(parent, "activation_before_selection", False)
        or not getattr(parent, "selection_supported", True)
        or getattr(parent, "deferred_selection_readback", False)
    ):
        return _delegate(parent, client_pid)
    return _strict(parent, client_pid)
