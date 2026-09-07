import asyncio
import json
import time

import anyio
import pytest

import claude_fleet_monitor.discovery as discovery
import claude_fleet_monitor.mcp_server as mcp_server
from mcp.client.session import ClientSession
from tests.conftest import write_session


@pytest.mark.asyncio
async def test_mcp_protocol_lists_tools_and_returns_fleet_status(
    fleet_dir, monkeypatch
):
    """Exercise the MCP initialization, tool discovery, and status call."""
    monkeypatch.setattr(discovery, "discover_processes", lambda: None)
    now = int(time.time())
    write_session(
        fleet_dir,
        "running-session",
        "alpha",
        "/tmp/alpha",
        status="running",
        detail="working",
        ts=now,
    )
    write_session(
        fleet_dir,
        "waiting-session",
        "beta",
        "/tmp/beta",
        status="waiting",
        detail="permission needed",
        ts=now,
    )

    async def protocol_smoke():
        client_to_server_send, client_to_server_receive = (
            anyio.create_memory_object_stream(0)
        )
        server_to_client_send, server_to_client_receive = (
            anyio.create_memory_object_stream(0)
        )

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                mcp_server.mcp._mcp_server.run,
                client_to_server_receive,
                server_to_client_send,
                mcp_server.mcp._mcp_server.create_initialization_options(),
            )
            async with ClientSession(
                server_to_client_receive, client_to_server_send
            ) as session:
                initialization = await session.initialize()
                tools = await session.list_tools()
                status = await session.call_tool("fleet_status")
            task_group.cancel_scope.cancel()

        return initialization, tools, status

    initialization, tools, status = await asyncio.wait_for(
        protocol_smoke(), timeout=5
    )

    assert initialization.serverInfo.name == "claude-fleet"
    assert {tool.name for tool in tools.tools} == {
        "fleet_status",
        "fleet_session",
        "fleet_sessions_needing_attention",
        "fleet_focus",
        "fleet_cleanup",
    }
    assert status.isError is False
    payload = json.loads(status.content[0].text)
    assert payload["summary"] == {
        "total": 2,
        "active": 1,
        "idle": 0,
        "needs_attention": 1,
    }
    assert {session["session_id"] for session in payload["sessions"]} == {
        "running-session",
        "waiting-session",
    }
