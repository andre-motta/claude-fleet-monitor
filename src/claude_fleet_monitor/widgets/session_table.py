"""DataTable widget for fleet sessions."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import DataTable

from claude_fleet_monitor.models import FleetSession, SessionStatus, format_age

STATUS_STYLES = {
    SessionStatus.RUNNING: "green",
    SessionStatus.IDLE: "yellow",
    SessionStatus.WAITING: "yellow",
    SessionStatus.STARTED: "cyan",
    SessionStatus.ERROR: "red",
    SessionStatus.ENDED: "bright_black",
    SessionStatus.DISCOVERED: "magenta",
}

STATUS_ICONS = {
    SessionStatus.RUNNING: "*",
    SessionStatus.IDLE: "=",
    SessionStatus.WAITING: "?",
    SessionStatus.STARTED: ">",
    SessionStatus.ERROR: "x",
    SessionStatus.ENDED: "-",
    SessionStatus.DISCOVERED: "+",
}

TERMINAL_ABBREV = {
    "konsole": "KDE",
    "tmux": "tmx",
    "zellij": "zel",
    "iterm2": "iTm",
    "macos_terminal": "mac",
    "gnome": "GTK",
    "windows_terminal": "win",
    "generic": "gen",
}


def _age_style(session: FleetSession) -> str:
    if session.status in (SessionStatus.RUNNING, SessionStatus.STARTED):
        return "green dim"
    if session.age_seconds > 600:
        return "red"
    if session.age_seconds > 120:
        return "yellow"
    return "dim"


class SessionTable(DataTable):
    """Fleet session table with status-colored rows."""

    def on_mount(self) -> None:
        self.add_column("!", key="attention", width=2)
        self.add_column("", key="icon", width=2)
        self.add_column("Repo", key="repo", width=24)
        self.add_column("Status", key="status", width=12)
        self.add_column("Term", key="terminal", width=5)
        self.add_column("Detail", key="detail")
        self.add_column("Age", key="age", width=8)
        self.cursor_type = "row"
        self.zebra_stripes = True

    def set_sessions(self, sessions: list[FleetSession]) -> None:
        current_key = None
        if self.row_count > 0:
            try:
                current_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
            except Exception:
                pass

        self.clear()
        restore_row = None

        for i, s in enumerate(sessions):
            style = STATUS_STYLES.get(s.status, "bright_black")
            icon = Text(STATUS_ICONS.get(s.status, "?"), style=style)
            attention = Text("!", style="bold yellow blink") if s.needs_attention else Text(" ")
            status = Text(s.status.value.upper(), style=style)
            detail = s.detail.replace("\n", " ").replace("\r", "")
            if len(detail) > 60:
                detail = detail[:57] + "..."
            term = TERMINAL_ABBREV.get(s.terminal, s.terminal[:3] if s.terminal else "")

            self.add_row(
                attention,
                icon,
                Text(s.repo[:23], style="bold"),
                status,
                Text(term, style="dim"),
                Text(detail),
                Text(format_age(s.age_seconds), style=_age_style(s)),
                key=s.session_id,
            )
            if current_key and s.session_id == current_key.value:
                restore_row = i

        if restore_row is not None:
            self.move_cursor(row=restore_row)

    def get_selected_session_id(self) -> str | None:
        if self.row_count == 0:
            return None
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return cell_key.row_key.value
        except Exception:
            return None
