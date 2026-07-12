import json
import pytest


@pytest.fixture
def fleet_dir(tmp_path, monkeypatch):
    d = tmp_path / "fleet"
    d.mkdir()
    monkeypatch.setenv("FLEET_DIR", str(d))
    import claude_fleet_monitor.discovery as discovery
    import claude_fleet_monitor.hook as hook
    import claude_fleet_monitor.focus as focus_mod
    monkeypatch.setattr(discovery, "FLEET_DIR", d)
    monkeypatch.setattr(hook, "FLEET_DIR", d)
    monkeypatch.setattr(focus_mod, "FLEET_DIR", d)
    return d


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    f.write_text("{}")
    import claude_fleet_monitor.cli as cli
    monkeypatch.setattr(cli, "SETTINGS_FILE", f)
    monkeypatch.setattr(cli, "CLAUDE_DIR", tmp_path)
    monkeypatch.setattr(cli, "FLEET_DIR", tmp_path / "fleet")
    return f


def write_session(fleet_dir, session_id, repo, cwd, status="started",
                  detail="", pid="", ts=None, source=None):
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
    filename = f"{session_id}.json"
    (fleet_dir / filename).write_text(json.dumps(data))
    return data
