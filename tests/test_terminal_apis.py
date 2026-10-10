import ast
import io
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_fleet_monitor import discovery
from claude_fleet_monitor.discovery import ProcessInfo
from claude_fleet_monitor.terminal_apis import (
    TERMINALS,
    _env,
    capture_terminal_info,
    detect_terminal,
    get_terminal_api,
    kitty,
    tmux,
)
from claude_fleet_monitor.terminal_apis import _ancestry as ancestry
from claude_fleet_monitor.terminal_apis.ghostty import GhosttyAPI
from claude_fleet_monitor.terminal_apis.kitty import KittyAPI
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from claude_fleet_monitor.terminal_apis.zellij import ZellijAPI
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
    "kitty": {
        "KITTY_WINDOW_ID": "3",
        "KITTY_LISTEN_ON": "unix:/tmp/kitty-fleet/rc.sock",
        "KITTY_PID": "4242",
    },
    "screen": {"STY": "4242.pts-3.fleet", "WINDOW": "2"},
    "generic": {},
}
PRE_EXISTING = [
    name for name in ADAPTER_MARKERS if name not in {"kitty", "screen", "generic"}
]
NEW_MARKERS = {
    "kitty": ADAPTER_MARKERS["kitty"],
    "screen": ADAPTER_MARKERS["screen"],
    "wezterm": {"WEZTERM_PANE": "4", "WEZTERM_UNIX_SOCKET": "/tmp/wez/gui-sock"},
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
        "claude_fleet_monitor.terminal_apis.ghostty.discovery.get_process_info",
        lambda pid: None,
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
    assert get_terminal_api("kitty").name == "kitty"
    assert get_terminal_api("screen").name == "screen"
    assert get_terminal_api("wezterm").name == "generic"
    assert get_terminal_api("nonexistent").name == "generic"


def test_new_adapters_sit_immediately_before_generic():
    names = [cls.name for cls in TERMINALS]
    assert names[-3:] == ["kitty", "screen", "generic"]
    assert "wezterm" not in names


@pytest.mark.parametrize(
    ("markers", "expected"),
    [
        (NEW_MARKERS["kitty"], "kitty"),
        (NEW_MARKERS["screen"], "screen"),
        (NEW_MARKERS["wezterm"], "generic"),
        ({**NEW_MARKERS["kitty"], **NEW_MARKERS["screen"]}, "kitty"),
        ({"STY": "4242.pts-3.fleet"}, "generic"),
        ({"KITTY_WINDOW_ID": "x1"}, "generic"),
    ],
    ids=["kitty", "screen", "wezterm", "screen-in-kitty", "sty-only", "bad-kitty-id"],
)
def test_new_marker_alone_detection(monkeypatch, markers, expected):
    _set_markers(monkeypatch, markers)
    assert detect_terminal().name == expected


@pytest.mark.parametrize("existing", PRE_EXISTING)
@pytest.mark.parametrize("leaked", [*NEW_MARKERS, "all"])
def test_new_markers_never_change_existing_detection(monkeypatch, existing, leaked):
    new = (
        {key: value for markers in NEW_MARKERS.values() for key, value in markers.items()}
        if leaked == "all"
        else NEW_MARKERS[leaked]
    )
    _set_markers(monkeypatch, {**new, **ADAPTER_MARKERS[existing]})
    assert detect_terminal().name == existing


@pytest.mark.parametrize("existing", ["konsole", "gnome"])
@pytest.mark.parametrize("leaked", list(NEW_MARKERS))
def test_konsole_and_gnome_markers_keep_precedence(monkeypatch, existing, leaked):
    _set_markers(monkeypatch, {**ADAPTER_MARKERS[existing], **NEW_MARKERS[leaked]})
    assert detect_terminal().name == existing


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


def _process(pid, ppid, name):
    return ProcessInfo(
        pid=pid,
        ppid=ppid,
        name=name,
        executable=name,
        argv=(name,),
        cwd=None,
        start_token="1",
    )


def _ancestry(monkeypatch, *chain):
    processes = {
        pid: _process(pid, ppid, name) for pid, ppid, name in chain
    }
    visited = []
    monkeypatch.setattr(
        tmux.discovery,
        "get_process_info",
        lambda pid: visited.append(pid) or processes.get(pid),
    )
    return visited


def _forbid_kitty(monkeypatch):
    for method in ("find_tab", "switch_tab", "raise_window", "focus_result"):
        monkeypatch.setattr(
            KittyAPI,
            method,
            lambda *args, **kwargs: pytest.fail("kitty cannot activate a parent"),
        )
    monkeypatch.setattr(
        kitty, "_run", lambda argv: pytest.fail("kitty remote control must not run")
    )


def test_tmux_parent_walk_stops_at_kitty_before_its_launcher(monkeypatch):
    visited = _ancestry(
        monkeypatch,
        (200, 150, "tmux: client"),
        (150, 100, "bash"),
        (100, 50, "kitty"),
        (50, 1, "konsole"),
    )

    parent = tmux._detect_parent_terminal(200)

    assert isinstance(parent, KittyAPI)
    assert visited == [200, 150, 100]


def test_tmux_in_kitty_reports_activation_failed_without_kitty_calls(monkeypatch):
    _ancestry(
        monkeypatch,
        (200, 150, "tmux: client"),
        (150, 100, "bash"),
        (100, 50, "kitty"),
        (50, 1, "konsole"),
    )
    _forbid_kitty(monkeypatch)
    commands = []
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command)
        or SimpleNamespace(stdout="200\t$7\t@12\t%34\t0\n", returncode=0),
    )

    with pytest.raises(
        RuntimeError,
        match="^parent terminal kitty does not support window activation$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", {"TMUX": "/tmp/fleet,socket,4400,7"})
    assert [command[3] for command in commands] == ["list-clients"]


def test_zellij_in_kitty_reports_unsupported_parent(monkeypatch):
    _ancestry(
        monkeypatch,
        (101, 90, "bash"),
        (90, 80, "zellij"),
        (80, 50, "kitty"),
        (50, 1, "konsole"),
    )
    _forbid_kitty(monkeypatch)

    result = ZellijAPI().focus_result(101, {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": "s"})

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == (
        "parent terminal kitty does not support window activation"
    )


def test_zellij_in_wezterm_reports_no_parent(monkeypatch):
    _ancestry(
        monkeypatch,
        (101, 90, "bash"),
        (90, 80, "zellij"),
        (80, 1, "wezterm-gui"),
    )

    result = ZellijAPI().focus_result(101, {"ZELLIJ": "0", "ZELLIJ_SESSION_NAME": "s"})

    assert result.state == "failed"
    assert not result.activation.succeeded
    assert result.activation.detail == "no parent terminal emulator found for zellij"


def test_screen_is_never_a_parent_terminal():
    assert "screen" not in tmux.TERMINAL_PROCESS_NAMES
    assert "SCREEN" not in tmux.TERMINAL_PROCESS_NAMES
    assert "wezterm-gui" not in tmux.TERMINAL_PROCESS_NAMES
    assert tmux.TERMINAL_PROCESS_NAMES["kitty"] == "kitty"


REAL_READ_STAT = ancestry._read_stat
HOOK_PID = 900


def _stat(pid, comm, ppid):
    return f"{pid} ({comm}) S {ppid} {pid} {pid} 0 -1 4194560 0 0 0 0 1 2 0 0 20 0"


def _proc(monkeypatch, *chain, platform="linux"):
    """Install a fake /proc: chain is (pid, comm, ppid) from the hook upward."""
    table = {pid: _stat(pid, comm, ppid) for pid, comm, ppid in chain}
    reads = []

    def read_stat(pid):
        reads.append(pid)
        if pid not in table:
            raise FileNotFoundError(pid)
        return table[pid]

    monkeypatch.setattr(ancestry, "_read_stat", read_stat)
    monkeypatch.setattr(ancestry, "os", SimpleNamespace(getpid=lambda: HOOK_PID))
    monkeypatch.setattr(ancestry, "sys", SimpleNamespace(platform=platform))
    _forbid_subprocess(monkeypatch)
    return reads


def _agent_under(*ancestors):
    """Hook, agent and shell, then the given comm names, then systemd as pid 1."""
    names = ["claude-fleet-ho", "claude", "bash", *ancestors]
    pids = [HOOK_PID - index * 10 for index in range(len(names))] + [1]
    chain = [(pid, comm, ppid) for pid, comm, ppid in zip(pids, names, pids[1:])]
    return [*chain, (1, "systemd", 0)]


LEAK_CASES = [
    pytest.param(
        {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["kitty"]},
        ("kitty", "bash", "konsole"),
        "kitty",
        id="kitty-launched-from-konsole",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["screen"]},
        ("screen", "screen", "bash", "konsole"),
        "screen",
        id="screen-inside-konsole",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["tmux"]},
        ("tmux: server",),
        "tmux",
        id="tmux-inside-konsole",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["tmux"], **ADAPTER_MARKERS["konsole"]},
        ("konsole", "bash", "tmux: server"),
        "konsole",
        id="konsole-with-leaked-tmux",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["terminator"]},
        ("terminator", "bash", "terminator"),
        "terminator",
        id="terminator-from-terminator-shell",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["terminator"], **ADAPTER_MARKERS["kitty"]},
        ("kitty", "bash", "terminator"),
        "kitty",
        id="kitty-with-leaked-terminator",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["tmux"], "ZELLIJ": "0", "ZELLIJ_PANE_ID": "4"},
        ("zellij",),
        "zellij",
        id="zellij-inside-tmux",
    ),
    pytest.param(
        {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["gnome"]},
        ("gnome-terminal-", "bash", "konsole"),
        "gnome",
        id="gnome-terminal-server-truncated-comm",
    ),
]


@pytest.mark.parametrize("markers, ancestors, expected", LEAK_CASES)
def test_nearest_ancestor_beats_leaked_markers(
    monkeypatch, markers, ancestors, expected
):
    _set_markers(monkeypatch, markers)
    _proc(monkeypatch, *_agent_under(*ancestors))

    info = capture_terminal_info()

    assert info["terminal"] == expected
    assert info["terminal_env"] == get_terminal_api(expected).capture_env()


def test_matching_ancestor_keeps_env_detection(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    expected = capture_terminal_info()
    _proc(monkeypatch, *_agent_under("konsole"))

    assert capture_terminal_info() == expected
    assert expected["terminal"] == "konsole"
    assert expected["terminal_env"]["KONSOLE_DBUS_SESSION"] == "/Sessions/3"


def test_ancestor_without_markers_captures_what_is_present(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    _proc(monkeypatch, *_agent_under("kitty", "bash", "konsole"))

    info = capture_terminal_info()

    assert info["terminal"] == "kitty"
    assert info["terminal_env"] == KittyAPI.capture_env()
    assert not any(name.startswith("KONSOLE_") for name in info["terminal_env"])


def test_no_known_ancestor_uses_env_detection(monkeypatch):
    _set_markers(
        monkeypatch, {**ADAPTER_MARKERS["konsole"], **ADAPTER_MARKERS["kitty"]}
    )
    reads = _proc(monkeypatch, *_agent_under("sshd-session", "sshd"))

    assert detect_terminal().name == "konsole"
    assert reads == [900, 890, 880, 870, 860, 1]


def test_hook_process_itself_is_not_an_ancestor(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    _proc(monkeypatch, (900, "screen", 890), (890, "bash", 1), (1, "systemd", 0))

    assert detect_terminal().name == "konsole"


def test_walk_stops_at_the_nearest_terminal(monkeypatch):
    _set_markers(monkeypatch, {})
    reads = _proc(monkeypatch, *_agent_under("zellij", "kitty", "konsole"))

    assert detect_terminal().name == "zellij"
    assert reads == [900, 890, 880, 870]


@pytest.mark.parametrize(
    "comm, expected",
    [
        ("tmux", "tmux"),
        ("tmux: server", "tmux"),
        ("tmux: client", "tmux"),
        ("tmuxinator", None),
        ("zellij", "zellij"),
        ("screen", "screen"),
        ("SCREEN", "screen"),
        ("konsole", "konsole"),
        ("ghostty", "ghostty"),
        ("gnome-terminal-", "gnome"),
        ("terminator", "terminator"),
        ("kitty", "kitty"),
        ("wezterm-gui", None),
        ("bash", None),
        ("", None),
    ],
)
def test_comm_terminal_mapping(comm, expected):
    assert ancestry.comm_terminal(comm) == expected


def test_process_names_are_registered_adapters_within_comm_length():
    registered = {cls.name for cls in TERMINALS}
    for comm, terminal in ancestry.PROCESS_TERMINALS.items():
        assert len(comm) <= ancestry.COMM_LENGTH
        assert terminal in registered
    for name, terminal in tmux.TERMINAL_PROCESS_NAMES.items():
        expected = None if terminal in ancestry.NON_LINUX_TERMINALS else terminal
        assert ancestry.comm_terminal(name[: ancestry.COMM_LENGTH]) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("10 (bash) S 9 10 10", ("bash", 9)),
        ("10 (tmux: server) S 1 10 10", ("tmux: server", 1)),
        ("10 (a) b (c) S 7 1", ("a) b (c", 7)),
        ("10 () S 7", ("", 7)),
        ("10 (bash) S", None),
        ("10 (bash) S x", None),
        ("10 (bash) S -3", None),
        ("10 (bash) S \u0663", None),
        ("10 bash S 9", None),
        ("10 )bash( S 9", None),
        ("", None),
    ],
)
def test_parse_stat(text, expected):
    assert ancestry._parse_stat(text) == expected


@pytest.mark.parametrize(
    "chain",
    [
        pytest.param([(900, "claude-fleet-ho", 890)], id="unreadable-parent"),
        pytest.param(
            [(900, "claude-fleet-ho", 890), (890, "claude", 880), (880, "bash", 890)],
            id="cycle",
        ),
        pytest.param(
            [(900, "claude-fleet-ho", 900)],
            id="self-parent",
        ),
        pytest.param(
            [(900, "claude-fleet-ho", 0)],
            id="no-parent",
        ),
    ],
)
def test_incomplete_ancestry_uses_env_detection(monkeypatch, chain):
    _set_markers(monkeypatch, ADAPTER_MARKERS["tmux"])
    reads = _proc(monkeypatch, *chain)

    assert capture_terminal_info()["terminal"] == "tmux"
    assert len(reads) == len(set(reads)) <= 3


def test_unreadable_proc_falls_back_to_env(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["kitty"])
    _proc(monkeypatch)

    assert capture_terminal_info() == {
        "terminal": "kitty",
        "terminal_env": KittyAPI.capture_env(),
    }


def test_malformed_stat_falls_back_to_env(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["screen"])
    _proc(monkeypatch, *_agent_under("konsole"))
    table = {870: "870 konsole S 860"}
    original = ancestry._read_stat
    monkeypatch.setattr(
        ancestry, "_read_stat", lambda pid: table.get(pid) or original(pid)
    )

    assert detect_terminal().name == "screen"


def test_walk_is_bounded(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["screen"])
    chain = [(pid, "bash", pid - 1) for pid in range(900, 600, -1)]
    reads = _proc(monkeypatch, *chain, (600, "konsole", 1))

    assert detect_terminal().name == "screen"
    assert len(reads) == ancestry.MAX_STEPS


def test_terminal_at_the_last_step_is_found(monkeypatch):
    _set_markers(monkeypatch, {})
    last = HOOK_PID - (ancestry.MAX_STEPS - 1)
    chain = [(pid, "bash", pid - 1) for pid in range(HOOK_PID, last, -1)]
    _proc(monkeypatch, *chain, (last, "kitty", 1))

    assert detect_terminal().name == "kitty"


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("hidepid"),
        ValueError("bad"),
        RuntimeError("boom"),
        MemoryError(),
    ],
    ids=lambda error: type(error).__name__,
)
def test_reader_errors_never_raise(monkeypatch, error):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    _proc(monkeypatch)

    def failing(pid):
        raise error

    monkeypatch.setattr(ancestry, "_read_stat", failing)

    assert ancestry.nearest_terminal() is None
    assert capture_terminal_info()["terminal"] == "konsole"


def test_non_text_stat_never_raises(monkeypatch):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    _proc(monkeypatch)
    monkeypatch.setattr(ancestry, "_read_stat", lambda pid: None)

    assert detect_terminal().name == "konsole"


@pytest.mark.parametrize("platform", ["darwin", "win32", "freebsd14"])
def test_non_linux_reads_no_ancestry(monkeypatch, platform):
    _set_markers(monkeypatch, ADAPTER_MARKERS["konsole"])
    reads = _proc(monkeypatch, *_agent_under("kitty"), platform=platform)

    assert detect_terminal().name == "konsole"
    assert reads == []


def test_real_reader_opens_only_proc_stat(monkeypatch):
    opened = []

    def fake_open(path, mode="r", *args, **kwargs):
        opened.append((path, mode))
        return io.BytesIO(b"42 (kitty) S 1 42 42")

    monkeypatch.setattr(ancestry, "open", fake_open, raising=False)

    assert REAL_READ_STAT(42) == "42 (kitty) S 1 42 42"
    assert opened == [("/proc/42/stat", "rb")]


def test_real_reader_decodes_invalid_utf8(monkeypatch):
    monkeypatch.setattr(
        ancestry,
        "open",
        lambda path, mode="r": io.BytesIO(b"42 (\xff\xfe) S 1"),
        raising=False,
    )

    assert ancestry._parse_stat(REAL_READ_STAT(42)) == ("\ufffd\ufffd", 1)


def test_ancestry_never_reads_environ_or_cmdline():
    tree = ast.parse(Path(ancestry.__file__).read_text(encoding="utf-8"))
    docstring = ast.get_docstring(tree, clean=False)
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value != docstring
    ]
    fstrings = [
        part.value
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
        if isinstance(part, ast.Constant)
    ]
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "/stat" in fstrings
    assert not any("environ" in text or "cmdline" in text for text in strings)
    assert "subprocess" not in imported


@pytest.mark.parametrize("comm", ["Terminal", "iTerm2", "WindowsTerminal"])
def test_linux_ancestry_ignores_non_linux_terminal_names(comm):
    from claude_fleet_monitor.terminal_apis import _ancestry

    assert _ancestry.comm_terminal(comm) is None
