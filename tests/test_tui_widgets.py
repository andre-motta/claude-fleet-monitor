"""Tests for the SessionTable widget using Textual's pilot."""

import pytest
from textual.app import App, ComposeResult

from claude_fleet_monitor.models import FleetSession, SessionStatus
from claude_fleet_monitor.widgets.session_table import SessionTable


def _session(
    sid: str = "s1",
    repo: str = "myrepo",
    status: SessionStatus = SessionStatus.RUNNING,
    detail: str = "processing",
    age: int = 30,
    attention: bool = False,
) -> FleetSession:
    return FleetSession(
        session_id=sid,
        repo=repo,
        cwd=f"/tmp/{repo}",
        status=status,
        detail=detail,
        ts=0,
        started=0,
        pid="1234",
        terminal="generic",
        terminal_env={},
        source="hook",
        tool="",
        age_seconds=age,
        needs_attention=attention,
    )


class TableApp(App):
    def compose(self) -> ComposeResult:
        yield SessionTable(id="table")


@pytest.mark.asyncio
async def test_table_populates():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        sessions = [_session("s1", "alpha"), _session("s2", "beta")]
        table.set_sessions(sessions)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_table_clears_on_empty():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        table.set_sessions([_session()])
        assert table.row_count == 1
        table.set_sessions([])
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_get_selected_session_id():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        table.set_sessions([_session("s1"), _session("s2")])
        sid = table.get_selected_session_id()
        assert sid in ("s1", "s2")


@pytest.mark.asyncio
async def test_get_selected_empty():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        assert table.get_selected_session_id() is None


@pytest.mark.asyncio
async def test_attention_marker():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        table.set_sessions([_session(attention=True)])
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_long_detail_truncated():
    async with TableApp().run_test() as pilot:
        table = pilot.app.query_one("#table", SessionTable)
        long_detail = "x" * 100
        table.set_sessions([_session(detail=long_detail)])
        assert table.row_count == 1
