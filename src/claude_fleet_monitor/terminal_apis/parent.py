"""Activate the terminal emulator hosting a multiplexer client.

Each parent follows its own protocol. Parents that activate before selecting,
cannot select, or only confirm selection after activation run their own
focus_result. Every other parent keeps the strict order in which a failed
selection never raises the window.
"""

from dataclasses import dataclass

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


@dataclass(frozen=True)
class ParentActivation:
    """Outcome of routing activation through a parent terminal.

    activated means a parent window was raised; confirmed means the parent's
    full protocol succeeded, including tab selection when it supports one.
    Callers must stop trying other parents once activated is True, since a
    second parent would raise a second window.
    """

    activated: bool = False
    confirmed: bool = False
    detail: str = ""

    def __bool__(self) -> bool:
        return self.confirmed


def _name(parent) -> str:
    return getattr(parent, "name", "unknown")


def _not_activated(parent) -> ParentActivation:
    return ParentActivation(detail=f"parent terminal {_name(parent)} did not activate")


def _activate(parent: TerminalAPI, client_pid: int) -> ParentActivation:
    selection_supported = getattr(parent, "selection_supported", True)
    if (
        getattr(parent, "activation_before_selection", False)
        or not selection_supported
        or getattr(parent, "deferred_selection_readback", False)
    ):
        result = parent.focus_result(client_pid, {})
        if not result.activation.succeeded:
            return _not_activated(parent)
        if result.selection.succeeded or not selection_supported:
            return ParentActivation(
                True, True, f"parent terminal {_name(parent)} activated"
            )
        return ParentActivation(
            True,
            False,
            f"parent terminal {_name(parent)} raised its window but could not "
            "confirm the tab",
        )
    parent_tab = parent.find_tab(client_pid, {})
    if not parent_tab or not parent.switch_tab(parent_tab, {}):
        return _not_activated(parent)
    find_target = getattr(parent, "find_activation_target", None)
    target = (
        find_target(client_pid, {}, parent_tab) if find_target else parent_tab
    )
    if not target or not parent.raise_window(target, {}):
        return _not_activated(parent)
    return ParentActivation(True, True, f"parent terminal {_name(parent)} activated")


def activate_parent(parent: TerminalAPI | None, client_pid: int) -> ParentActivation:
    """Activate the parent window and report what was verifiably achieved."""
    if parent is None:
        return ParentActivation(detail="no parent terminal emulator found")
    if not getattr(parent, "activation_supported", True):
        return ParentActivation(
            detail=(
                f"parent terminal {_name(parent)} does not support window "
                "activation"
            )
        )
    try:
        return _activate(parent, client_pid)
    except Exception:
        return _not_activated(parent)
