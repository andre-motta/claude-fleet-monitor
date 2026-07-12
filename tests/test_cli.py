import json


def test_install_creates_hooks(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    from claude_fleet_monitor.cli import cmd_install
    cmd_install(None)
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]
    assert "Stop" in settings["hooks"]
    assert "PermissionRequest" in settings["hooks"]
    assert "Elicitation" in settings["hooks"]


def test_install_creates_mcp_server(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    from claude_fleet_monitor.cli import cmd_install
    cmd_install(None)
    settings = json.loads(settings_file.read_text())
    assert "mcpServers" in settings
    assert "fleet" in settings["mcpServers"]
    assert settings["mcpServers"]["fleet"]["args"] == ["-m", "claude_fleet_monitor.mcp_server"]


def test_install_idempotent(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    from claude_fleet_monitor.cli import cmd_install
    cmd_install(None)
    cmd_install(None)
    settings = json.loads(settings_file.read_text())
    for event_hooks in settings["hooks"].values():
        fleet_hooks = [h for h in event_hooks if "claude-fleet-hook" in json.dumps(h)]
        assert len(fleet_hooks) == 1


def test_install_preserves_existing_hooks(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    settings_file.write_text(json.dumps({
        "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "other-hook"}]}]}
    }))
    from claude_fleet_monitor.cli import cmd_install
    cmd_install(None)
    settings = json.loads(settings_file.read_text())
    commands = [h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]]
    assert "other-hook" in commands
    assert any("claude-fleet-hook" in c for c in commands)


def test_uninstall_removes_hooks(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    from claude_fleet_monitor.cli import cmd_install, cmd_uninstall
    cmd_install(None)

    class Args:
        keep_data = True
    cmd_uninstall(Args())
    settings = json.loads(settings_file.read_text())
    assert "hooks" not in settings or not settings["hooks"]
    assert "fleet" not in settings.get("mcpServers", {})


def test_uninstall_preserves_other_hooks(settings_file, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: f"/usr/bin/{x}")
    settings_file.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"hooks": [{"type": "command", "command": "other-hook"}]},
            {"hooks": [{"type": "command", "command": "claude-fleet-hook tool-use"}]},
        ]}
    }))
    from claude_fleet_monitor.cli import cmd_uninstall

    class Args:
        keep_data = True
    cmd_uninstall(Args())
    settings = json.loads(settings_file.read_text())
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert "other-hook" in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
