import json


def _session(harness, native, canonical):
    return {
        "harness_id": harness,
        "session_id": native,
        "canonical_id": canonical,
    }


def test_fleet_session_accepts_canonical_id(monkeypatch):
    from claude_fleet_monitor import mcp_server

    codex = _session("codex", "shared", "fleet:v1:codex:bbb")
    monkeypatch.setattr(mcp_server, "read_sessions", lambda: [codex])
    result = json.loads(mcp_server.fleet_session("fleet:v1:codex:bbb"))
    assert result == codex


def test_fleet_session_rejects_ambiguous_native_id(monkeypatch):
    from claude_fleet_monitor import mcp_server

    sessions = [
        _session("claude", "shared", "fleet:v1:claude:aaa"),
        _session("codex", "shared", "fleet:v1:codex:bbb"),
    ]
    monkeypatch.setattr(mcp_server, "read_sessions", lambda: sessions)
    result = json.loads(mcp_server.fleet_session("shared"))
    assert result["error"] == "Multiple sessions match 'shared'"
    assert {match["canonical_id"] for match in result["matches"]} == {
        "fleet:v1:claude:aaa",
        "fleet:v1:codex:bbb",
    }


def test_fleet_session_preserves_unique_native_prefix(monkeypatch):
    from claude_fleet_monitor import mcp_server

    codex = _session("codex", "native-123", "fleet:v1:codex:bbb")
    monkeypatch.setattr(mcp_server, "read_sessions", lambda: [codex])
    assert json.loads(mcp_server.fleet_session("native-1")) == codex
