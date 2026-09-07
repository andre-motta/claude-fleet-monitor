"""Exercise the real Textual app with synthetic temporary session records."""

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input

from claude_fleet_monitor import discovery
from claude_fleet_monitor.tui import FleetMonitorApp
from claude_fleet_monitor.widgets.detail_panel import DetailPanel
from claude_fleet_monitor.widgets.session_table import SessionTable


async def validate():
    with tempfile.TemporaryDirectory(prefix="fleet-tui-validation-") as directory:
        root = Path(directory)
        for agent, status in (("claude", "running"), ("codex", "idle"), ("pi", "waiting")):
            (root / f"{agent}.json").write_text(json.dumps({
                "session_id": f"synthetic-{agent}",
                "agent": agent,
                "repo": f"fixture-{agent}",
                "cwd": str(root),
                "pid": "",
                "status": status,
                "detail": "synthetic UI fixture",
                "ts": int(time.time()),
            }))
        with patch.object(discovery, "FLEET_DIR", root), patch.object(
            discovery, "_find_agent_processes", return_value=[]
        ):
            app = FleetMonitorApp(refresh_interval=60, notify_level="none")
            async with app.run_test(size=(120, 35)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                table = app.query_one(SessionTable)
                assert table.row_count == 3
                await pilot.press("3")
                assert table.row_count == 1
                assert app._get_selected_session().agent == "pi"
                await pilot.press("d")
                panel = app.query_one(DetailPanel)
                assert panel.has_class("visible")
                rendered = str(panel.render())
                assert all(value in rendered for value in (
                    "pi", "fixture-pi", "WAITING", "synthetic UI fixture",
                ))
                await pilot.press("0", "slash")
                search = app.query_one("#search-input", Input)
                search.value = "codex"
                await pilot.pause()
                assert table.row_count == 1
                assert app._get_selected_session().agent == "codex"
                await pilot.press("escape")
                assert table.row_count == 3
                await pilot.press("n")
                assert app._get_selected_session().agent == "pi"
                await pilot.press("q")
                assert not app.is_running
    print("PASS: headless Textual app load, status/search filters, details, attention and quit")


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        asyncio.run(validate())
    else:
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--inside"],
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            print("TUI validation timed out after 30 seconds", file=sys.stderr)
            raise SystemExit(124)
        raise SystemExit(result.returncode)
