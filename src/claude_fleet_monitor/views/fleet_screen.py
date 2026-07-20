"""Fleet monitoring screen for use within tongs."""

from __future__ import annotations

import shutil
import subprocess
import threading

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from claude_fleet_monitor.discovery import read_sessions
from claude_fleet_monitor.models import FleetSession, parse_session, format_age
from claude_fleet_monitor.widgets.session_table import SessionTable


class FleetScreen(Screen):
    """Fleet monitoring screen that can be pushed within a tongs app."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("q", "go_back", "Back", show=False),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("slash", "toggle_search", "Search", show=True, key_display="/"),
    ]

    def __init__(self, refresh_interval: int = 2):
        super().__init__()
        self.refresh_interval = refresh_interval
        self._all_sessions: list[FleetSession] = []
        self._notified: set[str] = set()
        self._search_query = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="fleet-summary")
        yield SessionTable(id="fleet-table")
        yield Input(placeholder="Filter by repo or detail...", id="fleet-search")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "Fleet Monitor"
        self._timer = self.set_interval(self.refresh_interval, self._poll)
        self._poll()

    def on_unmount(self) -> None:
        if hasattr(self, "_timer"):
            self._timer.stop()

    @work(thread=True, group="fleet-poll")
    def _poll(self) -> None:
        raw = read_sessions()
        sessions = [parse_session(s) for s in raw]
        self.call_from_thread(self._update_ui, sessions)

    def _update_ui(self, sessions: list[FleetSession]) -> None:
        self._all_sessions = sessions
        self._notify_idle(sessions)
        filtered = self._apply_filter(sessions)
        self._update_summary(filtered)
        table = self.query_one("#fleet-table", SessionTable)
        table.set_sessions(filtered)

    def _apply_filter(self, sessions: list[FleetSession]) -> list[FleetSession]:
        if not self._search_query:
            return sessions
        q = self._search_query.lower()
        return [
            s for s in sessions
            if q in s.repo.lower() or q in s.detail.lower() or q in s.status.value.lower()
        ]

    def _update_summary(self, sessions: list[FleetSession]) -> None:
        active = sum(1 for s in sessions if s.status.value in ("running", "started"))
        idle = sum(1 for s in sessions if s.status.value == "idle")
        attention = sum(1 for s in sessions if s.needs_attention)
        text = f"{len(sessions)} sessions | {active} active | {idle} idle"
        if attention:
            text += f" | {attention} need input"
        bar = self.query_one("#fleet-summary", Static)
        bar.update(text)

    def _notify_idle(self, sessions: list[FleetSession]) -> None:
        if not shutil.which("notify-send"):
            return
        for s in sessions:
            if s.needs_attention and s.session_id not in self._notified:
                self._notified.add(s.session_id)
                subprocess.Popen(
                    [
                        "notify-send",
                        "-u", "normal",
                        "-a", "Claude Fleet",
                        "Session needs input",
                        f"{s.repo} idle for {format_age(s.age_seconds)}",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif not s.needs_attention and s.session_id in self._notified:
                self._notified.discard(s.session_id)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._poll()
        self.notify("Refreshed", timeout=2)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        sid = str(event.row_key.value)
        session = next((s for s in self._all_sessions if s.session_id == sid), None)
        if session:
            self._do_focus(session)
            self.notify(f"Focused: {session.repo}", timeout=2)

    def _do_focus(self, session: FleetSession) -> None:
        from claude_fleet_monitor.focus import focus

        def _run():
            try:
                focus(session.session_id)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def action_toggle_search(self) -> None:
        search_input = self.query_one("#fleet-search", Input)
        if search_input.display:
            search_input.display = False
            search_input.value = ""
            self._search_query = ""
            self._update_ui(self._all_sessions)
            self.query_one("#fleet-table", SessionTable).focus()
        else:
            search_input.display = True
            search_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "fleet-search":
            self._search_query = event.value
            filtered = self._apply_filter(self._all_sessions)
            self._update_summary(filtered)
            table = self.query_one("#fleet-table", SessionTable)
            table.set_sessions(filtered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fleet-search":
            self.query_one("#fleet-table", SessionTable).focus()
