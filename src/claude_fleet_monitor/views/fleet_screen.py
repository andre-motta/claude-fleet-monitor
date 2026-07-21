"""Fleet monitoring screen for use within tongs."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from claude_fleet_monitor.discovery import read_sessions
from claude_fleet_monitor.models import (
    SORT_KEYS,
    FleetSession,
    format_age,
    parse_session,
    sort_sessions,
)
from claude_fleet_monitor.widgets.detail_panel import DetailPanel
from claude_fleet_monitor.widgets.session_table import SessionTable


class FleetScreen(Screen):
    """Fleet monitoring screen that can be pushed within a tongs app."""

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("q", "go_back", "Back", show=False),
        Binding("r", "refresh", "Refresh", show=True, priority=True),
        Binding("slash", "toggle_search", "Search", show=True, key_display="/"),
        Binding("s", "cycle_sort", "Sort", show=True),
        Binding("d", "toggle_detail", "Detail", show=True),
        Binding("n", "next_attention", "Next", show=True),
        Binding("N", "prev_attention", "Prev", show=False),
        Binding("o", "open_cwd", "Open dir", show=True),
        Binding("c", "copy_info", "Copy", show=True),
        Binding("C", "copy_json", "JSON", show=False),
        Binding("1", "filter_status('running')", "Running", show=False),
        Binding("2", "filter_status('idle')", "Idle", show=False),
        Binding("3", "filter_status('waiting')", "Waiting", show=False),
        Binding("4", "filter_status('error')", "Error", show=False),
        Binding("0", "filter_status('')", "All", show=False),
    ]

    def __init__(self, refresh_interval: int = 2, notify_level: str = "all"):
        super().__init__()
        self.refresh_interval = refresh_interval
        self.notify_level = notify_level
        self._all_sessions: list[FleetSession] = []
        self._notified: set[str] = set()
        self._search_query = ""
        self._status_filter = ""
        self._sort_key = "repo"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="fleet-summary")
        yield SessionTable(id="fleet-table")
        yield DetailPanel(id="fleet-detail")
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
        self.app.call_from_thread(self._update_ui, sessions)

    def _update_ui(self, sessions: list[FleetSession]) -> None:
        self._all_sessions = sessions
        self._notify_idle(sessions)
        filtered = self._apply_filter(sessions)
        filtered = sort_sessions(filtered, self._sort_key)
        self._update_summary(filtered)
        table = self.query_one("#fleet-table", SessionTable)
        table.set_sessions(filtered)

    def _apply_filter(self, sessions: list[FleetSession]) -> list[FleetSession]:
        result = sessions
        if self._status_filter:
            result = [s for s in result if s.status.value == self._status_filter]
        if self._search_query:
            q = self._search_query.lower()
            result = [
                s for s in result
                if q in s.repo.lower() or q in s.detail.lower() or q in s.status.value.lower()
            ]
        return result

    def _update_summary(self, sessions: list[FleetSession]) -> None:
        total = len(self._all_sessions)
        active = sum(1 for s in self._all_sessions if s.status.value in ("running", "started"))
        idle = sum(1 for s in self._all_sessions if s.status.value == "idle")
        attention = sum(1 for s in self._all_sessions if s.needs_attention)

        text = Text()
        text.append(f"{total} sessions", style="bold")
        text.append(" | ")
        text.append(f"{active} active", style="green")
        text.append(" | ")
        text.append(f"{idle} idle", style="yellow")
        if attention:
            text.append(" | ")
            text.append(f"{attention} need input", style="bold yellow")

        text.append("  ")
        text.append(f"[sort:{self._sort_key}]", style="dim")
        if self._status_filter:
            text.append(f" [filter:{self._status_filter}]", style="dim cyan")

        shown = len(sessions)
        if shown != total:
            text.append(f"  showing {shown}/{total}", style="dim")

        bar = self.query_one("#fleet-summary", Static)
        bar.update(text)

    def _notify_idle(self, sessions: list[FleetSession]) -> None:
        if self.notify_level == "none":
            return
        if not shutil.which("notify-send"):
            return
        for s in sessions:
            should_notify = s.needs_attention
            if self.notify_level == "waiting":
                should_notify = s.status.value == "waiting"

            if should_notify and s.session_id not in self._notified:
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
                if s.status.value == "waiting":
                    sys.stdout.write("\a")
                    sys.stdout.flush()
            elif not should_notify and s.session_id in self._notified:
                self._notified.discard(s.session_id)

    def _get_selected_session(self) -> FleetSession | None:
        table = self.query_one("#fleet-table", SessionTable)
        sid = table.get_selected_session_id()
        if not sid:
            return None
        return next((s for s in self._all_sessions if s.session_id == sid), None)

    # -- Actions --

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._poll()
        self.notify("Refreshed", timeout=2)

    def action_cycle_sort(self) -> None:
        idx = SORT_KEYS.index(self._sort_key) if self._sort_key in SORT_KEYS else -1
        self._sort_key = SORT_KEYS[(idx + 1) % len(SORT_KEYS)]
        self._update_ui(self._all_sessions)
        self.notify(f"Sort: {self._sort_key}", timeout=2)

    def action_filter_status(self, status: str) -> None:
        if self._status_filter == status:
            self._status_filter = ""
        else:
            self._status_filter = status
        self._update_ui(self._all_sessions)
        label = self._status_filter or "all"
        self.notify(f"Filter: {label}", timeout=2)

    def action_toggle_detail(self) -> None:
        panel = self.query_one("#fleet-detail", DetailPanel)
        if panel.has_class("visible"):
            panel.remove_class("visible")
        else:
            panel.add_class("visible")
            session = self._get_selected_session()
            panel.set_session(session)

    def action_next_attention(self) -> None:
        self._jump_attention(forward=True)

    def action_prev_attention(self) -> None:
        self._jump_attention(forward=False)

    def _jump_attention(self, forward: bool) -> None:
        table = self.query_one("#fleet-table", SessionTable)
        if table.row_count == 0:
            return
        filtered = self._apply_filter(self._all_sessions)
        filtered = sort_sessions(filtered, self._sort_key)
        attention_indices = [i for i, s in enumerate(filtered) if s.needs_attention]
        if not attention_indices:
            self.notify("No sessions need attention", timeout=2)
            return
        current = table.cursor_coordinate.row
        if forward:
            target = next((i for i in attention_indices if i > current), attention_indices[0])
        else:
            target = next((i for i in reversed(attention_indices) if i < current), attention_indices[-1])
        table.move_cursor(row=target)

    def action_open_cwd(self) -> None:
        session = self._get_selected_session()
        if not session or not session.cwd:
            return
        if sys.platform == "darwin":
            cmd = ["open", session.cwd]
        elif sys.platform == "win32":
            cmd = ["explorer", session.cwd]
        else:
            cmd = ["xdg-open", session.cwd]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.notify(f"Opened: {session.cwd}", timeout=2)

    def action_copy_info(self) -> None:
        session = self._get_selected_session()
        if not session:
            return
        self.app.copy_to_clipboard(session.summary_line())
        self.notify("Copied summary", timeout=2)

    def action_copy_json(self) -> None:
        session = self._get_selected_session()
        if not session:
            return
        self.app.copy_to_clipboard(session.to_json())
        self.notify("Copied JSON", timeout=2)

    # -- Events --

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        sid = str(event.row_key.value)
        session = next((s for s in self._all_sessions if s.session_id == sid), None)
        if session:
            self._do_focus(session)
            self.notify(f"Focused: {session.repo}", timeout=2)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        panel = self.query_one("#fleet-detail", DetailPanel)
        if not panel.has_class("visible"):
            return
        if event.row_key is None:
            panel.set_session(None)
            return
        sid = str(event.row_key.value)
        session = next((s for s in self._all_sessions if s.session_id == sid), None)
        panel.set_session(session)

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
            filtered = sort_sessions(filtered, self._sort_key)
            self._update_summary(filtered)
            table = self.query_one("#fleet-table", SessionTable)
            table.set_sessions(filtered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fleet-search":
            self.query_one("#fleet-table", SessionTable).focus()
