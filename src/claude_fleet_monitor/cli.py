"""CLI for Claude Fleet Monitor - install, uninstall, monitor, focus."""

import argparse
import json
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path


CLAUDE_DIR = Path.home() / ".claude"
FLEET_DIR = Path(os.environ.get("FLEET_DIR", CLAUDE_DIR / "fleet"))
SETTINGS_FILE = CLAUDE_DIR / "settings.json"

HOOK_EVENTS = [
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "prompt-submit"),
    ("PreToolUse", "tool-use"),
    ("Stop", "stop"),
    ("StopFailure", "stop-failure"),
    ("SessionEnd", "session-end"),
]


def get_script_dir():
    return files("claude_fleet_monitor") / "scripts"


def get_install_paths():
    bin_dir = CLAUDE_DIR / "bin"
    mcp_dir = CLAUDE_DIR / "fleet-mcp"
    return bin_dir, mcp_dir


def load_settings():
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text())
    return {}


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")


def cmd_install(args):
    bin_dir, mcp_dir = get_install_paths()
    bin_dir.mkdir(parents=True, exist_ok=True)
    mcp_dir.mkdir(parents=True, exist_ok=True)
    FLEET_DIR.mkdir(parents=True, exist_ok=True)

    script_dir = get_script_dir()
    for name in ("fleet-hook.sh", "fleet-monitor.sh", "fleet-focus.sh"):
        src = script_dir / name
        dst = bin_dir / name
        dst.write_bytes(src.read_bytes())
        dst.chmod(0o755)
        print(f"  Installed {dst}")

    mcp_src = files("claude_fleet_monitor") / "mcp_server.py"
    mcp_dst = mcp_dir / "server.py"
    mcp_dst.write_bytes(mcp_src.read_bytes())
    print(f"  Installed {mcp_dst}")

    pyproject_src = files("claude_fleet_monitor") / "mcp_pyproject.toml"
    pyproject_dst = mcp_dir / "pyproject.toml"
    pyproject_dst.write_bytes(pyproject_src.read_bytes())
    print(f"  Installed {pyproject_dst}")

    settings = load_settings()

    hook_script = str(bin_dir / "fleet-hook.sh")

    if "hooks" not in settings:
        settings["hooks"] = {}

    for event, arg in HOOK_EVENTS:
        hook_entry = {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{hook_script} {arg}",
                    "timeout": 5,
                }
            ]
        }
        if event not in settings["hooks"]:
            settings["hooks"][event] = []

        already = any(
            hook_script in (h.get("hooks", [{}])[0].get("command", ""))
            for h in settings["hooks"][event]
        )
        if not already:
            settings["hooks"][event].append(hook_entry)

    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    uv_path = shutil.which("uv") or "uv"
    settings["mcpServers"]["fleet"] = {
        "command": uv_path,
        "args": ["run", "--directory", str(mcp_dir), "server.py"],
        "env": {},
    }

    save_settings(settings)
    print(f"  Updated {SETTINGS_FILE}")

    print()
    print("Claude Fleet Monitor installed!")
    print()
    print("Usage:")
    print(f"  {bin_dir}/fleet-monitor.sh        # TUI dashboard")
    print(f"  {bin_dir}/fleet-focus.sh <repo>    # Focus terminal tab")
    print("  (MCP tools available in any Claude session)")
    print()
    print("Restart Claude Code sessions to activate hooks.")


def cmd_uninstall(args):
    bin_dir, mcp_dir = get_install_paths()

    for name in ("fleet-hook.sh", "fleet-monitor.sh", "fleet-focus.sh"):
        f = bin_dir / name
        if f.exists():
            f.unlink()
            print(f"  Removed {f}")

    if mcp_dir.exists():
        shutil.rmtree(mcp_dir)
        print(f"  Removed {mcp_dir}")

    settings = load_settings()

    if "hooks" in settings:
        for event, _ in HOOK_EVENTS:
            if event in settings["hooks"]:
                settings["hooks"][event] = [
                    h
                    for h in settings["hooks"][event]
                    if "fleet-hook.sh" not in json.dumps(h)
                ]
                if not settings["hooks"][event]:
                    del settings["hooks"][event]
        if not settings["hooks"]:
            del settings["hooks"]

    if "mcpServers" in settings and "fleet" in settings["mcpServers"]:
        del settings["mcpServers"]["fleet"]

    save_settings(settings)
    print(f"  Updated {SETTINGS_FILE}")

    if not args.keep_data and FLEET_DIR.exists():
        shutil.rmtree(FLEET_DIR)
        print(f"  Removed {FLEET_DIR}")

    print()
    print("Claude Fleet Monitor uninstalled.")


def cmd_monitor(args):
    bin_dir, _ = get_install_paths()
    script = bin_dir / "fleet-monitor.sh"
    if not script.exists():
        print("Fleet monitor not installed. Run: claude-fleet install", file=sys.stderr)
        sys.exit(1)
    os.execvp(str(script), [str(script), str(args.refresh)])


def cmd_focus(args):
    bin_dir, _ = get_install_paths()
    script = bin_dir / "fleet-focus.sh"
    if not script.exists():
        print("Fleet monitor not installed. Run: claude-fleet install", file=sys.stderr)
        sys.exit(1)
    os.execvp(str(script), [str(script), args.query])


def cmd_status(args):
    if not FLEET_DIR.exists():
        print("No fleet data. Run: claude-fleet install", file=sys.stderr)
        sys.exit(1)

    now = __import__("time").time()
    sessions = []
    for f in FLEET_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            data["age"] = int(now - data.get("ts", now))
            sessions.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    if not sessions:
        print("No sessions found.")
        return

    sessions.sort(key=lambda s: s.get("ts", 0), reverse=True)
    print(f"{'REPO':<26} {'STATUS':<12} {'DETAIL':<40} {'AGE':>6}")
    print("-" * 86)
    for s in sessions:
        age = s["age"]
        age_str = f"{age}s" if age < 60 else f"{age // 60}m" if age < 3600 else f"{age // 3600}h{age % 3600 // 60}m"
        print(
            f"{s.get('repo', '?'):<26} "
            f"{s.get('status', '?').upper():<12} "
            f"{s.get('detail', '')[:40]:<40} "
            f"{age_str:>6}"
        )


def main():
    parser = argparse.ArgumentParser(
        prog="claude-fleet",
        description="Fleet monitoring for Claude Code sessions",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install hooks, scripts, and MCP server")

    p_uninstall = sub.add_parser("uninstall", help="Remove all fleet monitor components")
    p_uninstall.add_argument("--keep-data", action="store_true", help="Keep fleet status data")

    p_monitor = sub.add_parser("monitor", help="Launch TUI dashboard")
    p_monitor.add_argument("--refresh", type=int, default=2, help="Refresh interval in seconds")

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
