"""MCP server for Claude Fleet Monitor."""

import json

from mcp.server.fastmcp import FastMCP

from claude_fleet_monitor.discovery import cleanup_ended_sessions, read_sessions

mcp = FastMCP("claude-fleet")


@mcp.tool()
def fleet_status() -> str:
    """Get all Claude Code and Codex session statuses."""
    sessions = read_sessions()
    if not sessions:
        return json.dumps({"sessions": [], "summary": "No active sessions"})

    active = sum(1 for s in sessions if s["status"] in ("running", "started"))
    idle = sum(1 for s in sessions if s["status"] == "idle")
    attention = sum(1 for s in sessions if s["needs_attention"])

    return json.dumps(
        {
            "sessions": sessions,
            "summary": {
                "total": len(sessions),
                "active": active,
                "idle": idle,
                "needs_attention": attention,
            },
        },
        indent=2,
    )


@mcp.tool()
def fleet_session(session_id: str) -> str:
    """Get detailed status for a specific session by ID (full or prefix match)."""
    sessions = read_sessions()
    matches = [s for s in sessions if s.get("session_id", "").startswith(session_id)]
    if not matches:
        return json.dumps({"error": f"No session matching '{session_id}'"})
    return json.dumps(matches[0], indent=2)


@mcp.tool()
def fleet_sessions_needing_attention() -> str:
    """Get sessions that are idle for over 2 minutes and likely need user input."""
    sessions = read_sessions()
    attention = [s for s in sessions if s["needs_attention"]]
    if not attention:
        return json.dumps({"message": "All sessions healthy", "sessions": []})
    return json.dumps(
        {
            "message": f"{len(attention)} session(s) may need input",
            "sessions": attention,
        },
        indent=2,
    )


@mcp.tool()
def fleet_focus(query: str) -> str:
    """Focus the terminal running an agent session by repo, session ID, or PID."""
    from claude_fleet_monitor.focus import focus
    import io
    import sys

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = buf_out = io.StringIO()
    sys.stderr = buf_err = io.StringIO()
    try:
        result = focus(query)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    if result:
        return json.dumps(
            {"success": True, "message": buf_out.getvalue().strip()}
        )
    return json.dumps(
        {"success": False, "error": buf_err.getvalue().strip()}
    )


@mcp.tool()
def fleet_cleanup() -> str:
    """Remove status files for ended sessions older than 5 minutes."""
    return json.dumps({"removed": cleanup_ended_sessions()})


def main():
    mcp.run()


if __name__ == "__main__":
    main()
