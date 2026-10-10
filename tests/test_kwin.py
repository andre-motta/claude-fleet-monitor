import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import _kwin, _qdbus, konsole

QDBUS = "/usr/bin/qdbus-qt6"
NODE = shutil.which("node")


def _result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


class FakeKWin:
    """KWin scripting over qdbus; a reporting script may unload itself."""

    def __init__(self, loads=True, runs=True, self_unloads=True):
        self.loads = loads
        self.runs = runs
        self.self_unloads = self_unloads
        self.calls = []
        self.scripts = []
        self.loaded = set()

    def run(self, command, **kwargs):
        assert command[0] == QDBUS
        self.calls.append(command[1:])
        method = command[3]
        if method == "org.freedesktop.DBus.NameHasOwner":
            return _result(0, "true\n")
        if method == "org.kde.kwin.Scripting.loadScript":
            with open(command[4]) as script:
                self.scripts.append((script.read(), command[5], command[4]))
            if not self.loads:
                return _result(0, "-1\n")
            self.loaded.add(command[5])
            return _result(0, "4\n")
        if method == "org.kde.kwin.Script.run":
            if not self.runs:
                return _result(1)
            script, plugin, _ = self.scripts[-1]
            if self.self_unloads and json.dumps(plugin) in script:
                self.loaded.discard(plugin)
            return _result(0)
        if method == "org.kde.kwin.Scripting.isScriptLoaded":
            return _result(0, "true\n" if command[4] in self.loaded else "false\n")
        if method == "org.kde.kwin.Scripting.unloadScript":
            was_loaded = command[4] in self.loaded
            self.loaded.discard(command[4])
            return _result(0, "true\n" if was_loaded else "false\n")
        raise AssertionError(command)

    def methods(self):
        return [call[2] for call in self.calls]


@pytest.fixture
def fake_kwin(monkeypatch):
    def install(**kwargs):
        fake = FakeKWin(**kwargs)
        monkeypatch.setattr(_qdbus.subprocess, "run", fake.run)
        monkeypatch.setattr(_kwin, "REPORT_SECONDS", 0)
        return fake

    return install


def test_reporting_activation_returns_true_when_script_unloads_itself(fake_kwin):
    fake = fake_kwin()

    assert _kwin.activate_owned_window(QDBUS, 500, plugin_prefix="p", report=True)

    script, plugin, path = fake.scripts[0]
    assert plugin.startswith("p-") and len(plugin) == len("p-") + 32
    assert json.dumps(plugin) in script
    assert fake.methods() == [
        "org.kde.kwin.Scripting.loadScript",
        "org.kde.kwin.Script.run",
        "org.kde.kwin.Scripting.isScriptLoaded",
        "org.kde.kwin.Scripting.unloadScript",
    ]
    assert fake.calls[-1][3] == plugin
    assert not os.path.exists(path)


def test_reporting_activation_is_false_while_script_stays_loaded(fake_kwin):
    fake = fake_kwin(self_unloads=False)

    assert not _kwin.activate_owned_window(QDBUS, 500, plugin_prefix="p", report=True)
    assert fake.methods()[-1] == "org.kde.kwin.Scripting.unloadScript"
    assert fake.loaded == set()


def test_report_poll_waits_for_unload(monkeypatch):
    answers = iter(["true", None, "true", "false"])
    monkeypatch.setattr(_kwin, "qdbus_text", lambda executable, args: next(answers))
    monkeypatch.setattr(_kwin, "REPORT_SECONDS", 5)
    monkeypatch.setattr(_kwin, "REPORT_POLL_SECONDS", 0)

    assert _kwin._unloaded_itself(QDBUS, "p-x")


def test_plain_activation_never_polls_and_returns_true(fake_kwin):
    fake = fake_kwin()

    assert _kwin.activate_owned_window(
        QDBUS, 7, plugin_prefix="claude-fleet-focus", titles=["t"]
    )
    assert "org.kde.kwin.Scripting.isScriptLoaded" not in fake.methods()
    assert "callDBus" not in fake.scripts[0][0]
    assert fake.scripts[0][1].startswith("claude-fleet-focus-")


@pytest.mark.parametrize("report", [True, False])
def test_load_failure_raises_and_cleans_up(fake_kwin, report):
    fake = fake_kwin(loads=False)

    with pytest.raises(_qdbus.KWinScriptError, match="^KWin script could not be loaded$"):
        _kwin.activate_owned_window(QDBUS, 500, plugin_prefix="p", report=report)
    assert fake.methods() == [
        "org.kde.kwin.Scripting.loadScript",
        "org.kde.kwin.Scripting.unloadScript",
    ]
    assert fake.calls[-1][3] == fake.scripts[0][1]
    assert not os.path.exists(fake.scripts[0][2])


def test_run_failure_raises_and_cleans_up(fake_kwin):
    fake = fake_kwin(runs=False)

    with pytest.raises(_qdbus.KWinScriptError, match="^KWin script could not be run$"):
        _kwin.activate_owned_window(QDBUS, 500, plugin_prefix="p", report=True)
    assert "org.kde.kwin.Scripting.isScriptLoaded" not in fake.methods()
    assert fake.methods()[-1] == "org.kde.kwin.Scripting.unloadScript"
    assert not os.path.exists(fake.scripts[0][2])


def test_after_run_error_still_unloads(fake_kwin):
    fake = fake_kwin()

    def broken():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        _qdbus.run_kwin_script(QDBUS, "x", "p", after_run=broken)
    assert fake.methods()[-1] == "org.kde.kwin.Scripting.unloadScript"


def test_kwin_available_reads_bus_ownership(monkeypatch):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return _result(0, answer)

    monkeypatch.setattr(_qdbus.subprocess, "run", run)
    answer = "true\n"
    assert _kwin.kwin_available(QDBUS)
    answer = "false\n"
    assert not _kwin.kwin_available(QDBUS)
    assert seen[0][1:] == [
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus.NameHasOwner",
        "org.kde.KWin",
    ]


@pytest.mark.parametrize(
    "title",
    ['a"); callDBus("x"); //', "quote \" and \\", "line\nbreak", "\u2028\u2029"],
)
def test_values_are_embedded_as_json_data(title):
    script = _kwin.activation_script(7, [title], report_plugin='p"); evil(); ("')

    assert f"var titles = {json.dumps([title])};" in script
    assert "var owner = 7;" in script
    assert json.dumps('p"); evil(); ("') in script
    assert script.replace(json.dumps([title]), "").count("callDBus") == 1
    assert script.isascii()


def _run(script, windows):
    harness = (
        "const fakeWindows = " + json.dumps(windows) + ";\n"
        "const calls = [];\n"
        "function callDBus() { calls.push(Array.from(arguments)); }\n"
        "const workspace = {activeWindow: null, windowList: () => fakeWindows};\n"
        + script
        + "\nconst active = workspace.activeWindow;"
        "\nconsole.log(JSON.stringify({active: active && active.id, calls: calls,"
        " minimized: fakeWindows.map((w) => w.minimized)}));"
    )
    result = subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _window(id, pid=500, normal=True, deleted=False, caption="sh"):
    return {"id": id, "pid": pid, "normalWindow": normal, "deleted": deleted,
            "caption": caption, "minimized": True}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize(
    ("windows", "active"),
    [
        ([_window("a")], "a"),
        ([_window("a"), _window("b", pid=501)], "a"),
        ([_window("a"), _window("b", normal=False)], "a"),
        ([_window("a"), _window("b", deleted=True)], "a"),
        ([_window("a"), _window("b")], None),
        ([_window("b", pid=501)], None),
        ([_window("a", normal=False)], None),
        ([{"id": "a", "pid": 500, "caption": "sh", "minimized": True}], None),
        ([{**_window("a"), "pid": "500"}], None),
        ([], None),
    ],
    ids=["one", "other-pid", "non-normal", "deleted", "two", "none", "only-non-normal",
         "no-type-info", "string-pid", "empty"],
)
def test_script_activates_exactly_one_normal_owned_window(windows, active):
    plugin = "claude-fleet-kitty-0123"
    result = _run(_kwin.activation_script(500, report_plugin=plugin), windows)

    assert result["active"] == active
    if active is None:
        assert result["calls"] == []
        assert all(result["minimized"])
    else:
        assert result["calls"] == [[
            "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", plugin
        ]]
        assert result["minimized"][0] is False


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_script_without_report_never_calls_dbus():
    result = _run(_kwin.activation_script(500), [_window("a")])

    assert result["active"] == "a"
    assert result["calls"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_title_filter_keeps_kde_caption_rule():
    windows = [
        _window("a", caption="repo \u2014 Konsole"),
        _window("b", caption="repo-other \u2014 Konsole"),
    ]

    assert _run(_kwin.activation_script(500, ["repo"]), windows)["active"] == "a"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_malicious_plugin_name_stays_data():
    plugin = '"); workspace.activeWindow = fakeWindows[1]; ("'
    windows = [_window("a"), _window("b", pid=501)]

    result = _run(_kwin.activation_script(500, report_plugin=plugin), windows)

    assert result["active"] == "a"
    assert result["calls"][0][-1] == plugin


MARKERS = ["__TITLES__", "__OWNER__", "__NORMAL_ONLY__", "__REPORT__", "__PLUGIN__"]


@pytest.mark.parametrize("marker", MARKERS)
def test_placeholder_names_in_values_stay_literal(marker):
    title = f"x {marker} y"
    plugin = f"p-{marker}"

    script = _kwin.activation_script(7, [title], report_plugin=plugin)

    assert f"var titles = {json.dumps([title])};" in script
    assert "var owner = 7;" in script
    assert "var normalOnly = true;" in script
    assert script.count(json.dumps(plugin)) == 1
    assert script.count("callDBus") == 1
    assert konsole._kwin_activation_script([title], 7).splitlines()[1] == (
        f"var titles = {json.dumps([title])};"
    )


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("marker", MARKERS)
def test_script_matches_marker_titles_literally(marker):
    windows = [
        _window("literal", caption=f"{marker} \u2014 Konsole"),
        _window("rewritten", caption="500 \u2014 Konsole"),
        _window("rewritten-bool", caption="false \u2014 Konsole"),
    ]

    result = _run(_kwin.activation_script(500, [marker], normal_only=False), windows)

    assert result["active"] == "literal"
    assert result["calls"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("report", [True, False])
def test_refused_activation_is_not_reported(report):
    plugin = "claude-fleet-kitty-0123"
    script = _kwin.activation_script(
        500, report_plugin=plugin if report else None
    )
    harness = (
        "const fakeWindows = " + json.dumps([_window("a")]) + ";\n"
        "const calls = [];\n"
        "function callDBus() { calls.push(Array.from(arguments)); }\n"
        "let requested = null;\n"
        "const workspace = {windowList: () => fakeWindows,"
        " get activeWindow() { return null; },"
        " set activeWindow(w) { requested = w; }};\n"
        + script
        + "\nconsole.log(JSON.stringify({requested: requested && requested.id,"
        " calls: calls}));"
    )
    result = subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, timeout=10
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"requested": "a", "calls": []}


def test_report_block_is_absent_without_report_plugin():
    script = _kwin.activation_script(7, ["t"], normal_only=False)

    assert "callDBus" not in script
    assert "workspace.activeWindow === matches[0]" not in script
