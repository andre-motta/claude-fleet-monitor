"""CLI for installing and using the fleet monitor."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


CLAUDE_DIR = Path.home() / ".claude"
CODEX_DIR = Path.home() / ".codex"
FLEET_DIR = Path(os.environ.get("FLEET_DIR", CLAUDE_DIR / "fleet"))
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
CODEX_HOOKS_FILE = CODEX_DIR / "hooks.json"

CLAUDE_HOOK_EVENTS = [
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "prompt-submit"),
    ("PreToolUse", "tool-use"),
    ("Stop", "stop"),
    ("StopFailure", "stop-failure"),
    ("SessionEnd", "session-end"),
    ("PermissionRequest", "permission-request"),
    ("Elicitation", "elicitation"),
]

CODEX_HOOK_EVENTS = [
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "prompt-submit"),
    ("PreToolUse", "tool-use"),
    ("Stop", "stop"),
    ("SessionEnd", "session-end"),
    ("PermissionRequest", "permission-request"),
]


def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def load_settings():
    return load_json(SETTINGS_FILE)


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


def _install_hooks(config, events, hook_cmd, agent):
    hooks = config.setdefault("hooks", {})
    for event, arg in events:
        event_hooks = hooks.setdefault(event, [])
        event_hooks[:] = [h for h in event_hooks if "claude-fleet-hook" not in json.dumps(h)]
        timeout = 3 if event == "SessionEnd" else 5
        hook_group = {
            "hooks": [{
                "type": "command",
                "command": f"{hook_cmd} {arg} --agent {agent}",
                "timeout": timeout,
            }]
        }
        if agent == "codex" and event == "SessionStart":
            hook_group["matcher"] = "startup|resume|clear"
        event_hooks.append(hook_group)


def _remove_hooks(config, events):
    if "hooks" not in config:
        return
    for event, _ in events:
        if event not in config["hooks"]:
            continue
        config["hooks"][event] = [
            hook for hook in config["hooks"][event]
            if "claude-fleet-hook" not in json.dumps(hook)
        ]
        if not config["hooks"][event]:
            del config["hooks"][event]
    if not config["hooks"]:
        del config["hooks"]


def _get_codex_mcp(codex_cmd):
    try:
        result = subprocess.run(
            [codex_cmd, "mcp", "get", "fleet", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _is_fleet_mcp(config):
    transport = config.get("transport", config)
    return (
        transport.get("command") == sys.executable
        and transport.get("args") == ["-m", "claude_fleet_monitor.mcp_server"]
    )


def _install_codex_mcp(codex_cmd):
    existing = _get_codex_mcp(codex_cmd)
    if existing is not None:
        if not _is_fleet_mcp(existing):
            print("  Kept existing Codex MCP server named fleet")
        return
    try:
        result = subprocess.run(
            [codex_cmd, "mcp", "add", "fleet", "--", sys.executable,
             "-m", "claude_fleet_monitor.mcp_server"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"  Could not add Codex MCP server: {error}")
        return
    if result.returncode != 0:
        print(f"  Could not add Codex MCP server: {result.stderr.strip()}")


def _uninstall_codex_mcp(codex_cmd):
    existing = _get_codex_mcp(codex_cmd)
    if existing is None or not _is_fleet_mcp(existing):
        return
    try:
        subprocess.run(
            [codex_cmd, "mcp", "remove", "fleet"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def cmd_install(args):
    FLEET_DIR.mkdir(parents=True, exist_ok=True)

    hook_cmd = shutil.which("claude-fleet-hook") or "claude-fleet-hook"
    python_path = sys.executable

    settings = load_settings()

    _install_hooks(settings, CLAUDE_HOOK_EVENTS, hook_cmd, "claude")

    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    settings["mcpServers"]["fleet"] = {
        "command": python_path,
        "args": ["-m", "claude_fleet_monitor.mcp_server"],
        "env": {},
    }

    save_settings(settings)
    print(f"  Updated {SETTINGS_FILE}")

    codex_hooks = load_json(CODEX_HOOKS_FILE)
    _install_hooks(codex_hooks, CODEX_HOOK_EVENTS, hook_cmd, "codex")
    save_json(CODEX_HOOKS_FILE, codex_hooks)
    print(f"  Updated {CODEX_HOOKS_FILE}")

    codex_cmd = shutil.which("codex")
    if codex_cmd:
        _install_codex_mcp(codex_cmd)
    else:
        print("  Codex CLI not found; skipped Codex MCP registration")

    print()
    print("Claude Fleet Monitor installed for Claude Code and Codex!")
    print()
    print("Usage:")
    print("  claude-fleet monitor          # TUI dashboard")
    print("  claude-fleet focus <repo>     # Focus terminal tab")
    print("  (MCP tools available in Claude Code and Codex sessions)")
    print()
    print("Restart agent sessions to activate hooks. In Codex, review them with /hooks.")


def cmd_uninstall(args):
    # Clean up legacy bash scripts and MCP dir from older versions
    bin_dir = CLAUDE_DIR / "bin"
    mcp_dir = CLAUDE_DIR / "fleet-mcp"
    for name in ("fleet-hook.sh", "fleet-monitor.sh", "fleet-focus.sh"):
        f = bin_dir / name
        if f.exists():
            f.unlink()
            print(f"  Removed legacy {f}")
    if mcp_dir.exists():
        shutil.rmtree(mcp_dir)
        print(f"  Removed legacy {mcp_dir}")

    settings = load_settings()

    _remove_hooks(settings, CLAUDE_HOOK_EVENTS)

    if "mcpServers" in settings and "fleet" in settings["mcpServers"]:
        del settings["mcpServers"]["fleet"]

    save_settings(settings)
    print(f"  Updated {SETTINGS_FILE}")

    codex_hooks = load_json(CODEX_HOOKS_FILE)
    _remove_hooks(codex_hooks, CODEX_HOOK_EVENTS)
    save_json(CODEX_HOOKS_FILE, codex_hooks)
    print(f"  Updated {CODEX_HOOKS_FILE}")

    codex_cmd = shutil.which("codex")
    if codex_cmd:
        _uninstall_codex_mcp(codex_cmd)

    if not args.keep_data and FLEET_DIR.exists():
        shutil.rmtree(FLEET_DIR)
        print(f"  Removed {FLEET_DIR}")

    print()
    print("Claude Fleet Monitor uninstalled from Claude Code and Codex.")


def cmd_monitor(args):
    from claude_fleet_monitor.tui import FleetMonitorApp
    app = FleetMonitorApp(refresh_interval=args.refresh, notify_level=args.notify)
    app.run()


def cmd_focus(args):
    from claude_fleet_monitor.focus import focus
    if not focus(args.query):
        sys.exit(1)


def cmd_status(args):
    from claude_fleet_monitor.discovery import read_sessions
    sessions = read_sessions()

    if not sessions:
        print("No sessions found.")
        return

    sessions.sort(key=lambda s: s.get("ts", 0), reverse=True)
    print(f"{'AGENT':<8} {'REPO':<26} {'STATUS':<12} {'DETAIL':<40} {'AGE':>6}")
    print("-" * 95)
    for s in sessions:
        age = s.get("age_seconds", 0)
        detail = s.get("detail", "").replace("\n", " ").replace("\r", "")[:40]
        age_str = f"{age}s" if age < 60 else f"{age // 60}m" if age < 3600 else f"{age // 3600}h{age % 3600 // 60}m"
        print(
            f"{s.get('agent', 'claude'):<8} "
            f"{s.get('repo', '?'):<26} "
            f"{s.get('status', '?').upper():<12} "
            f"{detail:<40} "
            f"{age_str:>6}"
        )


def main():
    parser = argparse.ArgumentParser(
        prog="claude-fleet",
        description="Fleet monitoring for Claude Code and Codex sessions",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install hooks, scripts, and MCP server")

    p_uninstall = sub.add_parser("uninstall", help="Remove all fleet monitor components")
    p_uninstall.add_argument("--keep-data", action="store_true", help="Keep fleet status data")

    p_monitor = sub.add_parser("monitor", help="Launch TUI dashboard")
    p_monitor.add_argument("--refresh", type=int, default=2, help="Refresh interval in seconds")
    p_monitor.add_argument("--notify", choices=["all", "waiting", "none"], default="all",
                           help="Notification level: all, waiting-only, or none")

    p_focus = sub.add_parser("focus", help="Focus terminal tab for a session")
    p_focus.add_argument("query", help="Repo name, session ID, or PID")

    sub.add_parser("status", help="Print fleet status (no TUI)")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "monitor": cmd_monitor,
        "focus": cmd_focus,
        "status": cmd_status,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
