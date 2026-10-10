import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from claude_fleet_monitor.focus import focus_notification
from claude_fleet_monitor.terminal_apis import konsole
from claude_fleet_monitor.terminal_apis.base import TerminalAPI
from tests.konsole_fakes import fake_konsole, qdbus_result

StepError = konsole.KonsoleFocusError
STALE_SELECTION = (
    r"^tab 2 selection not confirmed \(Konsole reports tab 5;"
    r" readback may be stale until activation\)$"
)


def _executable(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.mark.skipif(os.name == "nt", reason="uses POSIX executable fixtures")
def test_resolve_qdbus_uses_path_priority_and_fallback(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    qdbus = _executable(bin_dir, "qdbus")
    qdbus6 = _executable(bin_dir, "qdbus6")
    qdbus_qt6 = _executable(bin_dir, "qdbus-qt6")
    monkeypatch.setenv("PATH", str(bin_dir))

    assert konsole._resolve_qdbus() == str(qdbus)
    qdbus.unlink()
    assert konsole._resolve_qdbus() == str(qdbus6)
    qdbus6.unlink()
    assert konsole._resolve_qdbus() == str(qdbus_qt6)


def test_missing_qdbus_is_safe_for_all_operations(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: None)
    api = konsole.KonsoleAPI()

    assert api._find_service() is None
    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    with pytest.raises(StepError, match="^qdbus is not available$"):
        api.switch_tab("org.kde.konsole|1|2", {})
    with pytest.raises(StepError, match="^qdbus is not available$"):
        api.raise_window("org.kde.konsole|1|2", {})
    assert not api.verify_selection("org.kde.konsole|1|2", {})
    assert api.focus_result(42, {}).state == "failed"


def _assert_steps_fail_safely(api):
    with pytest.raises(StepError, match="^Konsole could not select tab 2$"):
        api.switch_tab("org.kde.konsole|1|2", {})
    with pytest.raises(StepError, match="^Konsole tab 2 title could not be read$"):
        api.raise_window("org.kde.konsole|1|2", {})


def test_disappearing_qdbus_is_safe(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    api = konsole.KonsoleAPI()

    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    _assert_steps_fail_safely(api)
    with pytest.raises(StepError, match="^KWin script could not be loaded$"):
        konsole._activate_by_kwin_caption(["Konsole"], 7, "/bin/qdbus-qt6")


def test_nonzero_qdbus_output_cannot_create_target_or_success(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: qdbus_result(
            1, "org.kde.konsole-123\n/Sessions/2\n/Windows/3\n42\n17\n"
        ),
    )
    api = konsole.KonsoleAPI()

    assert api._find_service() is None
    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    _assert_steps_fail_safely(api)


def test_qdbus_timeout_cannot_create_target_or_success(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: "/bin/qdbus-qt6")
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            konsole.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        ),
    )
    api = konsole.KonsoleAPI()

    assert api.find_tab(42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole"}) is None
    _assert_steps_fail_safely(api)
    with pytest.raises(StepError, match="^KWin script could not be loaded$"):
        konsole._activate_by_kwin_caption(["Konsole"], 7, "/bin/qdbus-qt6")


def test_find_tab_selects_valid_pid_and_window(monkeypatch):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command == [executable, "org.kde.konsole-123"]:
            return qdbus_result(0, "/Sessions/2\n/Windows/7\n")
        if command[-1] == "org.kde.konsole.Session.foregroundProcessId":
            return qdbus_result(0, "99\n")
        if command[-1] == "org.kde.konsole.Session.processId":
            return qdbus_result(0, "42\n")
        if command[-1] == "org.kde.konsole.Window.sessionList":
            return qdbus_result(0, "2\n")
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)
    tab_id = konsole.KonsoleAPI().find_tab(
        42, {"KONSOLE_DBUS_SERVICE": "org.kde.konsole-123"}
    )

    assert tab_id == "org.kde.konsole-123|7|2"
    assert all(command[0] == executable for command in calls)


def test_switch_tab_verifies_current_session(monkeypatch):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-2] == "org.kde.konsole.Window.setCurrentSession":
            return qdbus_result(0)
        if command[-1] == "org.kde.konsole.Window.currentSession":
            return qdbus_result(0, "2\n")
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    assert konsole.KonsoleAPI().switch_tab(
        "org.kde.konsole-123|7|2", {}
    )
    assert len(calls) == 2
    assert all(command[0] == executable for command in calls)


@pytest.mark.parametrize(
    ("returncode", "stdout", "detail"),
    [
        (
            0,
            "99\n",
            r"^tab 2 selection not confirmed \(Konsole reports tab 99;"
            r" readback may be stale until activation\)$",
        ),
        (0, "\n", "^Konsole did not report tab 2 as current$"),
        (1, "2\n", "^Konsole current tab could not be read$"),
    ],
)
def test_switch_tab_rejects_stale_or_failed_readback(
    monkeypatch, returncode, stdout, detail
):
    executable = "/usr/bin/qdbus-qt6"
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)

    def run(command, **kwargs):
        if command[-2] == "org.kde.konsole.Window.setCurrentSession":
            return qdbus_result(0)
        if command[-1] == "org.kde.konsole.Window.currentSession":
            return qdbus_result(returncode, stdout)
        raise AssertionError(command)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    with pytest.raises(StepError, match=detail):
        konsole.KonsoleAPI().switch_tab("org.kde.konsole-123|7|2", {})


def _script_titles(script):
    line = next(
        line for line in script.splitlines() if line.startswith("var titles")
    )
    return json.loads(line.removeprefix("var titles = ").rstrip(";"))


def test_inactive_window_selection_is_verified_after_activation(monkeypatch):
    fake = fake_konsole(monkeypatch)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "complete"
    assert (
        result.selection.detail
        == "tab or pane selection verified after activation"
    )
    assert result.activation.succeeded
    script, plugin, path = fake.scripts[0]
    assert _script_titles(script) == ["title 2", "title 5"]
    assert "var owner = 4242;" in script
    assert fake.unloaded == [plugin]
    assert not os.path.exists(path)


def test_active_window_selects_directly(monkeypatch):
    fake = fake_konsole(monkeypatch, active=True)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "complete"
    assert result.selection.detail == "tab or pane selection"
    assert _script_titles(fake.scripts[0][0]) == ["title 2"]


def test_inactive_window_stale_readback_still_reaches_verification(
    monkeypatch,
):
    fake = fake_konsole(monkeypatch)
    api = konsole.KonsoleAPI()

    with pytest.raises(StepError, match=STALE_SELECTION):
        api.switch_tab("svc|7|2", {})
    fake.visible = "5"

    result = api.focus_result(42, {})

    assert result.state == "complete"
    assert result.selection.attempted and result.selection.succeeded
    assert focus_notification(result, "repo") == ("Focused: repo", "information")


def test_konsole_declares_deferred_selection_readback():
    assert TerminalAPI.deferred_selection_readback is False
    assert konsole.KonsoleAPI.deferred_selection_readback is True


def test_unobserved_activation_reports_failure(monkeypatch):
    fake = fake_konsole(monkeypatch)
    fake.activates = False

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "failed"
    assert result.selection.attempted and not result.selection.succeeded
    assert result.activation.attempted and not result.activation.succeeded
    assert result.selection.detail == (
        "tab 2 selection not confirmed (Konsole reports tab 5;"
        " readback may be stale until activation)"
    )
    assert (
        result.activation.detail
        == "no unique Konsole window matched the tab title (0 found)"
    )
    assert fake.unloaded == [fake.scripts[0][1]]
    assert focus_notification(result, "repo") == (
        "Focus Failed: repo: terminal focus operations failed"
        " (selection: tab 2 selection not confirmed (Konsole reports tab 5;"
        " readbac...;"
        " activation: no unique Konsole window matched the tab title (0 found))",
        "error",
    )


def test_inactive_titled_window_names_activation_timeout(monkeypatch):
    fake = fake_konsole(monkeypatch)
    fake.focused = "2"
    fake.activates = False

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "partial"
    assert result.selection.succeeded
    assert result.activation.detail == "window did not become active within 0s"
    assert focus_notification(result, "repo") == (
        "Partially focused: repo (selection: ok;"
        " activation: window did not become active within 0s)",
        "warning",
    )


def test_active_window_with_other_tab_names_current_tab(monkeypatch):
    fake = fake_konsole(monkeypatch)
    original = fake.run

    def run(command, **kwargs):
        args = command[1:]
        if args[2:] == ["org.kde.konsole.Window.currentSession"]:
            return qdbus_result(0, "5\n")
        if args[2:] == ["org.qtproject.Qt.QWidget.windowTitle"]:
            return qdbus_result(0, "title 2\n")
        return original(command, **kwargs)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "failed"
    assert result.activation.detail == "Konsole reports tab 5 current, not 2"


def test_failed_kwin_run_is_named_and_cleaned_up(monkeypatch):
    fake = fake_konsole(monkeypatch)
    fake.runs = False

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "failed"
    assert result.activation.detail == "KWin script could not be run"
    assert fake.unloaded == [fake.scripts[0][1]]
    assert not os.path.exists(fake.scripts[0][2])


def test_failed_kwin_load_is_named_in_focus_result(monkeypatch):
    fake = fake_konsole(monkeypatch)
    original = fake.run

    def run(command, **kwargs):
        if command[3:4] == ["org.kde.kwin.Scripting.loadScript"]:
            return qdbus_result(0, "-1\n")
        return original(command, **kwargs)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "failed"
    assert result.activation.detail == "KWin script could not be loaded"


def test_unreadable_tab_title_is_named(monkeypatch):
    fake = fake_konsole(monkeypatch, active=True)
    original = fake.run

    def run(command, **kwargs):
        if command[-2:] == ["org.kde.konsole.Session.title", "1"]:
            return qdbus_result(1)
        return original(command, **kwargs)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "partial"
    assert result.activation.detail == "Konsole tab 2 title could not be read"
    assert not fake.scripts


def test_missing_owner_pid_never_loads_kwin_script(monkeypatch):
    fake = fake_konsole(monkeypatch)
    original = fake.run

    def run(command, **kwargs):
        if command[-2:] == [
            "org.freedesktop.DBus.GetConnectionUnixProcessID",
            "svc",
        ]:
            return qdbus_result(1)
        return original(command, **kwargs)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    with pytest.raises(StepError, match="owner process could not be read"):
        konsole.KonsoleAPI().raise_window("svc|7|2", {})
    assert not fake.scripts


@pytest.mark.parametrize(
    "title",
    [
        "a\\'); callDBus('x'); //",
        'quote " and \\',
        "line\nbreak",
        "</script> ",
    ],
)
def test_kwin_script_embeds_titles_as_data(monkeypatch, title):
    executable = "/usr/bin/qdbus-qt6"
    scripts = []

    def run(command, **kwargs):
        if command[3] == "org.kde.kwin.Scripting.loadScript":
            scripts.append(open(command[4]).read())
            return qdbus_result(0, "3\n")
        return qdbus_result(0)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    assert konsole._activate_by_kwin_caption([title], 7, executable)
    assert _script_titles(scripts[0]) == [title]
    assert "callDBus" not in scripts[0].replace(json.dumps(title), "")


def test_failed_kwin_load_reports_no_activation(monkeypatch):
    monkeypatch.setattr(
        konsole.subprocess, "run", lambda command, **kwargs: qdbus_result(0, "-1\n")
    )

    with pytest.raises(StepError, match="^KWin script could not be loaded$"):
        konsole._activate_by_kwin_caption(["t"], 7, "/usr/bin/qdbus-qt6")


NODE = shutil.which("node")


def _run_kwin_script(titles, windows):
    script = konsole._kwin_activation_script(titles, 7)
    harness = (
        "const fakeWindows = " + json.dumps(windows) + ";\n"
        "const workspace = {activeWindow: null, windowList: () => fakeWindows};\n"
        + script
        + "\nconst active = workspace.activeWindow;"
        "\nconsole.log(JSON.stringify(active && active.caption));"
    )
    result = subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("titles", "captions", "activated"),
    [
        (
            ["repo : claude"],
            ["repo : claude \u2014 Konsole", "repo : claude-fleet \u2014 Konsole"],
            "repo : claude \u2014 Konsole",
        ),
        (["t"], ["t \u2014 Konsole <2>"], "t \u2014 Konsole <2>"),
        (["a"], ["a \u2014 b \u2014 Konsole"], None),
        (["t"], ["t \u2014 Konsole", "t \u2014 Konsole <2>"], None),
        (["t"], ["t2 \u2014 Konsole"], None),
    ],
)
def test_kwin_script_activates_only_one_exact_caption(
    titles, captions, activated
):
    windows = [
        {"pid": 7, "caption": caption, "minimized": True} for caption in captions
    ]
    windows.append({"pid": 8, "caption": titles[0], "minimized": False})

    assert _run_kwin_script(titles, windows) == activated


def test_other_active_window_with_same_title_is_not_activation(monkeypatch):
    fake = fake_konsole(monkeypatch)
    fake.focused = "2"
    fake.activates = False
    original = fake.run

    def run(command, **kwargs):
        args = command[1:]
        if args == ["svc"]:
            return qdbus_result(0, "/konsole/MainWindow_1\n/konsole/MainWindow_2\n")
        if args[2:] == ["org.qtproject.Qt.QWidget.windowTitle"]:
            return qdbus_result(0, "title 2\n")
        if args[2:] == ["org.qtproject.Qt.QWidget.isActiveWindow"]:
            active = args[1] == "/konsole/MainWindow_2"
            return qdbus_result(0, "true\n" if active else "false\n")
        return original(command, **kwargs)

    monkeypatch.setattr(konsole.subprocess, "run", run)

    result = konsole.KonsoleAPI().focus_result(42, {})

    assert result.state == "partial"
    assert result.selection.succeeded
    assert not result.activation.succeeded
    assert (
        result.activation.detail
        == "no unique Konsole window matched the tab title (2 found)"
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_kwin_script_runs_malicious_title_as_data():
    title = "x\\'); workspace.activeWindow = fakeWindows[0]; //"
    windows = [{"pid": 7, "caption": "other \u2014 Konsole", "minimized": True}]

    assert _run_kwin_script([title], windows) is None


def test_failed_kwin_load_cleans_up(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return qdbus_result(0, "-1\n")

    monkeypatch.setattr(konsole.subprocess, "run", run)

    with pytest.raises(StepError):
        konsole._activate_by_kwin_caption(["t"], 7, "/usr/bin/qdbus-qt6")
    path = calls[0][4]
    assert calls[-1][3:] == ["org.kde.kwin.Scripting.unloadScript", calls[0][5]]
    assert not os.path.exists(path)
