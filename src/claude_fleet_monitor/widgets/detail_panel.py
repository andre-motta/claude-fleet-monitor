"""Detail panel widget showing expanded session info."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from claude_fleet_monitor.models import FleetSession, format_age
from claude_fleet_monitor.widgets.session_table import STATUS_STYLES


class DetailPanel(Static):
    """Shows full detail for the currently highlighted session."""

    DEFAULT_CSS = """
    DetailPanel {
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: $surface;
        border-top: solid $accent 50%;
        display: none;
    }

    DetailPanel.visible {
        display: block;
    }
    """

    def set_session(self, session: FleetSession | None) -> None:
        if session is None:
            self.update("")
            return

        style = STATUS_STYLES.get(session.status, "bright_black")
        duration = ""
        if session.started:
            dur_secs = session.age_seconds + (session.ts - session.started) if session.ts > session.started else session.age_seconds
            duration = f"  Duration: {format_age(dur_secs)}"

        detail = session.detail.replace("\n", " ").replace("\r", "")

        lines = Text()
        lines.append(session.repo, style="bold")
        lines.append(f"  {session.status.value.upper()}", style=style)
        lines.append(f"  Age: {format_age(session.age_seconds)}")
        lines.append(duration)
        lines.append("\n")
        lines.append(f"Path: {session.cwd}", style="dim")
        lines.append(f"  PID: {session.pid}" if session.pid else "")
        lines.append(f"  Terminal: {session.terminal}" if session.terminal else "")
        if session.tool:
            lines.append(f"  Tool: {session.tool}")
        lines.append("\n")
        if detail:
            lines.append(detail)

        self.update(lines)
