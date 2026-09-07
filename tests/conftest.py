import json
import pytest


@pytest.fixture
def fleet_dir(tmp_path, monkeypatch):
    d = tmp_path / "fleet"
    d.mkdir()
    monkeypatch.setenv("FLEET_DIR", str(d))
    import claude_fleet_monitor.discovery as discovery
    monkeypatch.setattr(discovery, "FLEET_DIR", d)
    return d


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    f.write_text("{}")
    import claude_fleet_monitor.cli as cli
    monkeypatch.setattr(cli, "SETTINGS_FILE", f)
    monkeypatch.setattr(cli, "CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(cli, "CODEX_DIR", tmp_path / "codex")
    monkeypatch.setattr(cli, "CODEX_HOOKS_FILE", tmp_path / "codex" / "hooks.json")
    monkeypatch.setattr(cli, "FLEET_DIR", tmp_path / "fleet")
    monkeypatch.setattr(cli, "_install_codex_mcp", lambda command: None)
    monkeypatch.setattr(cli, "_uninstall_codex_mcp", lambda command: None)
    return f


def write_session(fleet_dir, session_id, repo, cwd, status="started",
                  detail="", pid="", ts=None, source=None, agent=None):
    import time
    if ts is None:
        ts = int(time.time())
    data = {
        "session_id": session_id,
        "repo": repo,
        "cwd": cwd,
        "pid": pid,
        "status": status,
        "detail": detail,
        "ts": ts,
        "started": ts,
    }
    if source:
        data["source"] = source
    if agent:
        data["agent"] = agent
    filename = f"{session_id}.json"
    (fleet_dir / filename).write_text(json.dumps(data))
    return data
