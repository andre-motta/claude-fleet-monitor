"""Opt-in cleaner for terminal markers leaked from the test runner's terminal.

Not autouse and not in conftest: tmux, Pi and validator tests need a real TMUX.
"""

import os

TERMINAL_MARKERS = (
    "TMUX",
    "TMUX_PANE",
    "STY",
    "WINDOW",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
    "VTE_VERSION",
    "GNOME_TERMINAL_SERVICE",
    "GNOME_TERMINAL_SCREEN",
    "ITERM_SESSION_ID",
    "WT_SESSION",
    "WINDOWID",
)
TERMINAL_MARKER_PREFIXES = (
    "ZELLIJ",
    "KONSOLE_",
    "GHOSTTY_",
    "TERMINATOR_",
    "KITTY_",
    "WEZTERM_",
)


def clear_terminal_markers(monkeypatch) -> None:
    for name in TERMINAL_MARKERS:
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):
        if name.startswith(TERMINAL_MARKER_PREFIXES):
            monkeypatch.delenv(name, raising=False)
