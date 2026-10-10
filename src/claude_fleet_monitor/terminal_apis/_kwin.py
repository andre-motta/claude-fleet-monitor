"""Activate the single KWin window owned by one process.

Values reach the script only as JSON literals. A reporting script unloads its
own plugin after activating, which is the only result KWin lets a caller
observe; the unload is visible through isScriptLoaded.
"""

import json
import time
import uuid

from claude_fleet_monitor.terminal_apis._qdbus import qdbus_text, run_kwin_script

REPORT_SECONDS = 0.5
REPORT_POLL_SECONDS = 0.02
_SCRIPT = """
var titles = __TITLES__;
var owner = __OWNER__;
var normalOnly = __NORMAL_ONLY__;
var matches = [];
var windows = workspace.windowList();
for (var i = 0; i < windows.length; i++) {
    var candidate = windows[i];
    if (candidate.pid !== owner) {
        continue;
    }
    if (normalOnly && (candidate.normalWindow !== true || candidate.deleted === true)) {
        continue;
    }
    if (titles === null) {
        matches.push(candidate);
        continue;
    }
    for (var j = 0; j < titles.length; j++) {
        var rest = candidate.caption.slice(titles[j].length);
        var suffix = /^( \\u2014 [^\\u2014]+)?( <\\d+>)?$/;
        if (candidate.caption.indexOf(titles[j]) === 0 && suffix.test(rest)) {
            matches.push(candidate);
            break;
        }
    }
}
if (matches.length === 1) {
    matches[0].minimized = false;
    workspace.activeWindow = matches[0];
__REPORT__}
"""
_REPORT = (
    '    callDBus("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",'
    ' "unloadScript", __PLUGIN__);\n'
)


def activation_script(
    owner_pid: int,
    titles: list[str] | None = None,
    *,
    normal_only: bool = True,
    report_plugin: str | None = None,
) -> str:
    """Build the script; a caption must equal a title plus KDE suffixes."""
    report = ""
    if report_plugin is not None:
        report = _REPORT.replace("__PLUGIN__", json.dumps(report_plugin))
    return (
        _SCRIPT.replace("__TITLES__", json.dumps(titles))
        .replace("__OWNER__", json.dumps(owner_pid))
        .replace("__NORMAL_ONLY__", json.dumps(normal_only))
        .replace("__REPORT__", report)
    )


def kwin_available(executable: str) -> bool:
    return qdbus_text(
        executable,
        [
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.NameHasOwner",
            "org.kde.KWin",
        ],
    ) == "true"


def _unloaded_itself(executable: str, plugin: str) -> bool:
    deadline = time.monotonic() + REPORT_SECONDS
    while True:
        loaded = qdbus_text(
            executable,
            [
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.isScriptLoaded",
                plugin,
            ],
        )
        if loaded == "false":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(REPORT_POLL_SECONDS)


def activate_owned_window(
    executable: str,
    owner_pid: int,
    *,
    plugin_prefix: str,
    titles: list[str] | None = None,
    normal_only: bool = True,
    report: bool = False,
) -> bool:
    """Activate the one window of owner_pid matching titles, if exactly one.

    Raises KWinScriptError when the script cannot be loaded or run. With
    report, returns whether KWin confirmed it found and activated exactly one
    window; otherwise returns True once the script ran.
    """
    if not report:
        script = activation_script(owner_pid, titles, normal_only=normal_only)
        run_kwin_script(executable, script, plugin_prefix)
        return True
    plugin = f"{plugin_prefix}-{uuid.uuid4().hex}"
    script = activation_script(
        owner_pid, titles, normal_only=normal_only, report_plugin=plugin
    )
    return bool(
        run_kwin_script(
            executable,
            script,
            plugin_prefix,
            plugin=plugin,
            after_run=lambda: _unloaded_itself(executable, plugin),
        )
    )
