"""Activate the terminal emulator hosting a multiplexer client.

Each parent follows its own protocol. Parents that activate before selecting,
cannot select, or only confirm selection after activation run their own
focus_result. Every other parent keeps the strict order in which a failed
selection never raises the window.
"""

from claude_fleet_monitor.terminal_apis.base import TerminalAPI


def _activate(parent: TerminalAPI, client_pid: int) -> bool:
    if not getattr(parent, "activation_supported", True):
        return False
    selection_supported = getattr(parent, "selection_supported", True)
    if (
        getattr(parent, "activation_before_selection", False)
        or not selection_supported
        or getattr(parent, "deferred_selection_readback", False)
    ):
        result = parent.focus_result(client_pid, {})
        return bool(
            result.activation.succeeded
            and (result.selection.succeeded or not selection_supported)
        )
    parent_tab = parent.find_tab(client_pid, {})
    if not parent_tab or not parent.switch_tab(parent_tab, {}):
        return False
    find_target = getattr(parent, "find_activation_target", None)
    target = (
        find_target(client_pid, {}, parent_tab) if find_target else parent_tab
    )
    return bool(target and parent.raise_window(target, {}))


def activate_parent(parent: TerminalAPI | None, client_pid: int) -> bool:
    """Return True only when the parent window is verifiably activated."""
    if parent is None:
        return False
    try:
        return _activate(parent, client_pid)
    except Exception:
        return False
