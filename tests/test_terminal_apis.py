import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_fleet_monitor import discovery
from claude_fleet_monitor.terminal_apis import (
    TERMINALS,
    _env,
    capture_terminal_info,
    detect_terminal,
    get_terminal_api,
    konsole,
)
from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI
from tests.terminal_env import clear_terminal_markers

REPO_ROOT = Path(__file__).resolve().parents[1]

ADAPTER_MARKERS = {
    "tmux": {"TMUX": "/tmp/tmux-1000/default,12345,0"},
    "zellij": {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": "fleet"},
    "konsole": {
        "KONSOLE_VERSION": "260402",
        "KONSOLE_DBUS_SERVICE": "org.kde.konsole-12345",
        "KONSOLE_DBUS_SESSION": "/Sessions/3",
        "KONSOLE_DBUS_WINDOW": "/Windows/1",
    },
    "ghostty": {
        "TERM_PROGRAM": "ghostty",
        "GHOSTTY_BIN_DIR": "/usr/bin",
        "GHOSTTY_RESOURCES_DIR": "/usr/share/ghostty",
    },
    "iterm2": {"ITERM_SESSION_ID": "w0t0p0:12345"},
    "macos_terminal": {"TERM_PROGRAM": "Apple_Terminal"},
    "gnome": {
        "VTE_VERSION": "7200",
        "GNOME_TERMINAL_SERVICE": ":1.2",
        "GNOME_TERMINAL_SCREEN": "/org/gnome/Terminal/screen/1",
    },
    "terminator": {
        "TERMINATOR_UUID": "urn:uuid:00000000-0000-4000-8000-000000000000",
        "TERMINATOR_DBUS_NAME": "net.tenshu.Terminator2abc",
        "TERMINATOR_DBUS_PATH": "/net/tenshu/Terminator2",
    },
    "windows_terminal": {"WT_SESSION": "some-guid"},
    "generic": {},
}


def _set_markers(monkeypatch, markers):
    clear_terminal_markers(monkeypatch)
    for name, value in markers.items():
        monkeypatch.setenv(name, value)


def test_detect_konsole(monkeypatch):
    _set_markers(monkeypatch, {"KONSOLE_VERSION": "260402"})
    assert detect_terminal().name == "konsole"


def test_detect_tmux(monkeypatch):
    _set_markers(monkeypatch, {"TMUX": "/tmp/tmux-1000/default,12345,0"})
    assert detect_terminal().name == "tmux"


def test_detect_tmux_over_konsole(monkeypatch):
    _set_markers(
        monkeypatch,
        {"TMUX": "/tmp/tmux-1000/default,12345,0", "KONSOLE_VERSION": "260402"},
    )
    assert detect_terminal().name == "tmux"


def test_detect_zellij(monkeypatch):
    _set_markers(monkeypatch, {"ZELLIJ": "1"})
    assert detect_terminal().name == "zellij"


def test_detect_iterm2(monkeypatch):
    _set_markers(monkeypatch, {"ITERM_SESSION_ID": "w0t0p0:12345"})
    assert detect_terminal().name == "iterm2"


def test_detect_macos_terminal(monkeypatch):
    _set_markers(monkeypatch, {"TERM_PROGRAM": "Apple_Terminal"})
    assert detect_terminal().name == "macos_terminal"


def test_detect_ghostty(monkeypatch):
    _set_markers(monkeypatch, {"TERM_PROGRAM": "ghostty"})
    assert detect_terminal().name == "ghostty"


def test_detect_ghostty_capture_env(monkeypatch):
    _set_markers(
        monkeypatch, {"TERM_PROGRAM": "ghostty", "GHOSTTY_BIN_DIR": "/usr/bin"}
    )
    info = capture_terminal_info()
    assert info["terminal"] == "ghostty"
    assert info["terminal_env"]["GHOSTTY_BIN_DIR"] == "/usr/bin"


def test_detect_gnome(monkeypatch):
    _set_markers(
        monkeypatch, {"VTE_VERSION": "7200", "GNOME_TERMINAL_SERVICE": ":1.2"}
    )
    assert detect_terminal().name == "gnome"


def test_vte_alone_does_not_claim_gnome_terminal(monkeypatch):
    _set_markers(monkeypatch, {"VTE_VERSION": "7200"})
    assert detect_terminal().name == "generic"


def test_ghostty_missing_ancestry_is_not_a_tab(monkeypatch):
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.ghostty._find_ghostty_pid",
        lambda: None,
    )
    result = GhosttyAPI().focus_result(101, {})
    assert result.state == "failed"
    assert not result.target_found


def test_ghostty_activates_before_global_tab_keys(monkeypatch):
    calls = []
    api = GhosttyAPI()
    monkeypatch.setattr(
        "claude_fleet_monitor.terminal_apis.ghostty.time.sleep",
        lambda seconds: calls.append(("delay", seconds)),
    )
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "101:2")
    monkeypatch.setattr(
        api, "raise_window", lambda target, env: calls.append("activate") or True
    )
    monkeypatch.setattr(
        api, "switch_tab", lambda target, env: calls.append("select") or True
    )
    result = api.focus_result(101, {})
    assert calls == ["activate", ("delay", 0.15), "select"]
    assert result.complete


def test_ghostty_skips_global_keys_when_activation_fails(monkeypatch):
    api = GhosttyAPI()
    monkeypatch.setattr(api, "find_tab", lambda pid, env: "101:2")
    monkeypatch.setattr(api, "raise_window", lambda target, env: False)
    monkeypatch.setattr(
        api,
        "switch_tab",
        lambda target, env: pytest.fail("global keys must not be sent"),
    )
    result = api.focus_result(101, {})
    assert result.state == "failed"
    assert not result.selection.attempted


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("claude_fleet_monitor.terminal_apis.iterm2", "ITerm2API"),
        ("claude_fleet_monitor.terminal_apis.macos_terminal", "MacOSTerminalAPI"),
    ],
)
def test_macos_selection_reads_text_output(monkeypatch, module_name, class_name):
    module = __import__(module_name, fromlist=[class_name])
    api = getattr(module, class_name)()
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="focused\n")

    monkeypatch.setattr(module.subprocess, "run", run)
    assert api.switch_tab("target", {})
    assert calls[0]["text"] is True


def test_detect_windows_terminal(monkeypatch):
    _set_markers(monkeypatch, {"WT_SESSION": "some-guid"})
    assert detect_terminal().name == "windows_terminal"


def test_detect_generic_fallback(monkeypatch):
    clear_terminal_markers(monkeypatch)
    assert detect_terminal().name == "generic"


def test_capture_terminal_info_konsole(monkeypatch):
    _set_markers(
        monkeypatch,
        {
            "KONSOLE_VERSION": "260402",
            "KONSOLE_DBUS_SERVICE": "org.kde.konsole-12345",
            "KONSOLE_DBUS_SESSION": "/Sessions/3",
        },
    )
    info = capture_terminal_info()
    assert info["terminal"] == "konsole"
    assert info["terminal_env"]["KONSOLE_DBUS_SERVICE"] == "org.kde.konsole-12345"


def test_capture_terminal_info_tmux(monkeypatch):
    _set_markers(monkeypatch, {"TMUX": "/tmp/tmux-1000/default,12345,0"})
    info = capture_terminal_info()
    assert info["terminal"] == "tmux"
    assert "/tmp/tmux-1000/default" in info["terminal_env"]["TMUX"]


def test_get_terminal_api():
    assert get_terminal_api("konsole").name == "konsole"
    assert get_terminal_api("tmux").name == "tmux"
    assert get_terminal_api("terminator").name == "terminator"
    assert get_terminal_api("nonexistent").name == "generic"


def _forbid_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("hook-time capture must not start a process")

    for name in ("run", "Popen", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)


def test_every_registered_adapter_has_markers():
    assert [cls.name for cls in TERMINALS] == list(ADAPTER_MARKERS)


@pytest.mark.parametrize("cls", TERMINALS, ids=lambda cls: cls.name)
def test_capture_is_subprocess_free_and_bounded(monkeypatch, cls):
    _set_markers(monkeypatch, ADAPTER_MARKERS[cls.name])
    _forbid_subprocess(monkeypatch)

    info = capture_terminal_info()

    assert info["terminal"] == cls.name
    env = info["terminal_env"]
    assert isinstance(env, dict)
    assert len(env) <= discovery.MAX_ENV_ITEMS
    for key, value in env.items():
        assert isinstance(key, str) and key
        assert isinstance(value, str)
        assert "\0" not in key and "\0" not in value
        assert len(key.encode("utf-8")) <= 128
        assert len(value.encode("utf-8")) <= discovery.MAX_ENV_VALUE_LENGTH


def test_bounded_env_keeps_values_at_the_byte_limit(monkeypatch):
    clear_terminal_markers(monkeypatch)
    exact = "é" * (_env.MAX_VALUE_BYTES // 2)
    monkeypatch.setenv("TERMINATOR_UUID", exact)
    monkeypatch.setenv("TERMINATOR_DBUS_NAME", exact + "x")
    monkeypatch.setenv("TERMINATOR_DBUS_PATH", "")

    assert _env.bounded_env(
        ("TERMINATOR_UUID", "TERMINATOR_DBUS_NAME", "TERMINATOR_DBUS_PATH")
    ) == {"TERMINATOR_UUID": exact, "TERMINATOR_DBUS_PATH": ""}


def test_bounded_env_omits_unset_nul_and_non_text(monkeypatch):
    environ = {"GOOD": "1", "NUL": "a\0b", "BYTES": b"1", "NONE": None}
    monkeypatch.setattr(_env, "os", SimpleNamespace(environ=environ))

    assert _env.bounded_env(("GOOD", "NUL", "BYTES", "NONE", "UNSET")) == {
        "GOOD": "1"
    }


def test_bounded_env_never_raises(monkeypatch):
    class BrokenEnviron:
        def get(self, name):
            raise RuntimeError("broken environment")

    monkeypatch.setattr(_env, "os", SimpleNamespace(environ=BrokenEnviron()))

    assert _env.bounded_env(("ANY",)) == {}


@pytest.mark.parametrize("value", ["0", "7", "123456789012"])
def test_is_decimal_id_accepts_ascii_digits(value):
    assert _env.is_decimal_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-1",
        "+1",
        " 1",
        "1 ",
        "1.0",
        "0x1",
        "١٢",
        "²",
        "1234567890123",
        None,
        12,
        b"12",
    ],
)
def test_is_decimal_id_rejects_non_digits(value):
    assert not _env.is_decimal_id(value)


def test_is_decimal_id_honors_max_len():
    assert _env.is_decimal_id("1234", max_len=4)
    assert not _env.is_decimal_id("12345", max_len=4)


def test_claude_md_detection_order_matches_registry():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    match = re.search(r"^Detection order: (.+?)\.(?:\s|$)", text, re.MULTILINE)
    assert match is not None
    documented = [name.strip() for name in match.group(1).split(">")]
    assert documented == [cls.name for cls in TERMINALS]


def test_ghostty_kwin_raise_uses_resolved_qdbus(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="7\n")

    monkeypatch.setattr(
        konsole.shutil,
        "which",
        lambda name: "/usr/bin/qdbus-qt6" if name == "qdbus-qt6" else None,
    )
    monkeypatch.setattr(konsole.subprocess, "run", run)

    assert not GhosttyAPI._try_kwin_raise()
    assert [command[0] for command in calls] == [
        "/usr/bin/qdbus-qt6",
        "/usr/bin/qdbus-qt6",
    ]
    assert calls[1][2] == "/Scripting/Script7"


def test_ghostty_kwin_raise_without_qdbus_is_safe(monkeypatch):
    monkeypatch.setattr(konsole.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        konsole.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("qdbus must not run"),
    )

    assert not GhosttyAPI._try_kwin_raise()
