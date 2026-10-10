import json
import subprocess

import pytest

from claude_fleet_monitor.terminal_apis import kitty
from claude_fleet_monitor.terminal_apis.kitty import KittyAPI
from tests.terminal_env import clear_terminal_markers

ADDRESS = "unix:/tmp/fleet-kitty-test/rc.sock"
KITTY_ENV = {"KITTY_WINDOW_ID": "2", "KITTY_LISTEN_ON": ADDRESS}


def _listing(active_window=2, active_tab=True, other_active=False):
    return [
        {
            "id": 1,
            "is_focused": False,
            "tabs": [
                {
                    "id": 1,
                    "is_active": not active_tab,
                    "windows": [{"id": 1, "is_active": True, "is_focused": False}],
                },
                {
                    "id": 2,
                    "is_active": active_tab,
                    "windows": [
                        {"id": 2, "is_active": active_window == 2, "is_focused": False},
                        {"id": 3, "is_active": active_window == 3 or other_active},
                    ],
                },
            ],
        }
    ]


def _done(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class FakeKitty:
    """Records argv and answers focus-window and ls like a kitty instance."""

    def __init__(self, select=None, listing=None, ls_stdout=None, ls_result="ok"):
        self.calls = []
        self.select = select
        self.listing = _listing() if listing is None else listing
        self.ls_stdout = ls_stdout
        self.ls_result = ls_result

    def __call__(self, argv):
        self.calls.append(list(argv))
        if "focus-window" in argv:
            return _done(argv) if self.select is None else self.select
        if self.ls_result is None:
            return None
        if isinstance(self.ls_result, subprocess.CompletedProcess):
            return self.ls_result
        stdout = self.ls_stdout if self.ls_stdout is not None else json.dumps(self.listing)
        return _done(argv, stdout=stdout)


@pytest.fixture
def tools(monkeypatch):
    available = {"kitten": "/usr/bin/kitten", "kitty": "/usr/bin/kitty"}
    monkeypatch.setattr(kitty.shutil, "which", lambda name: available.get(name))
    return available


@pytest.fixture(autouse=True)
def forbid_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("kitty tests must not start a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)


def _fake(monkeypatch, fake):
    monkeypatch.setattr(kitty, "_run", fake)
    return fake


def test_detect_requires_decimal_window_id(monkeypatch):
    clear_terminal_markers(monkeypatch)
    assert not KittyAPI.detect()
    monkeypatch.setenv("KITTY_WINDOW_ID", "12")
    assert KittyAPI.detect()
    for value in ("", "-1", "1a", "+2", "١", "1" * 13):
        monkeypatch.setenv("KITTY_WINDOW_ID", value)
        assert not KittyAPI.detect(), value


def test_capture_env_reads_only_valid_values_without_processes(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("capture must not run processes")
    )
    monkeypatch.setattr(
        kitty.shutil, "which", lambda name: pytest.fail("capture must not look up tools")
    )
    monkeypatch.setenv("KITTY_WINDOW_ID", "7")
    monkeypatch.setenv("KITTY_LISTEN_ON", ADDRESS)
    monkeypatch.setenv("KITTY_PID", "4242")
    monkeypatch.setenv("KITTY_PUBLIC_KEY", "secret")

    assert KittyAPI.capture_env() == {"KITTY_WINDOW_ID": "7", "KITTY_LISTEN_ON": ADDRESS}


def test_capture_env_accepts_abstract_socket(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:@fleet-kitty")

    assert KittyAPI.capture_env()["KITTY_LISTEN_ON"] == "unix:@fleet-kitty"


def test_capture_env_omits_oversized_listen_on(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("KITTY_LISTEN_ON", "unix:/" + "a" * 1100)

    assert KittyAPI.capture_env() == {"KITTY_WINDOW_ID": "1"}


@pytest.mark.parametrize(
    "value",
    [
        "-x",
        "--to=unix:/tmp/x",
        "tcp:localhost:12345",
        "tcp6:[::1]:1",
        "fd:3",
        "unix:relative/path",
        "unix:-x",
        "unix:@",
        "unix:",
        "unix:/tmp/a\nb",
        "/tmp/rc.sock",
        "@abstract",
    ],
)
def test_capture_env_omits_invalid_listen_on(monkeypatch, value):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("KITTY_LISTEN_ON", value)

    assert KittyAPI.capture_env() == {"KITTY_WINDOW_ID": "1"}


def test_capture_env_omits_invalid_window_id(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("KITTY_WINDOW_ID", "1;rm")
    monkeypatch.setenv("KITTY_LISTEN_ON", ADDRESS)

    assert KittyAPI.capture_env() == {"KITTY_LISTEN_ON": ADDRESS}


def test_find_tab_returns_window_id_with_valid_address():
    assert KittyAPI().find_tab(10, dict(KITTY_ENV)) == "2"


@pytest.mark.parametrize("env", [{}, {"KITTY_LISTEN_ON": ADDRESS}, {"KITTY_WINDOW_ID": "x"}])
def test_find_tab_is_truthfully_none_without_window_id(env):
    assert KittyAPI().find_tab(10, env) is None


def test_remote_control_off_reports_unavailable_without_processes(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())
    env = {"KITTY_WINDOW_ID": "2"}

    with pytest.raises(LookupError, match="allow_remote_control/listen_on"):
        KittyAPI().find_tab(10, env)
    result = KittyAPI().focus_result(10, env)

    assert result.state == "failed"
    assert not result.selection.attempted
    assert result.selection.detail == kitty.REMOTE_CONTROL_UNAVAILABLE
    assert not result.activation.attempted
    assert fake.calls == []


@pytest.mark.parametrize(
    "address",
    ["-x", "tcp:127.0.0.1:5000", "unix:/tmp/a\0b", "unix:relative", "fd:3"],
)
def test_malicious_listen_on_never_reaches_argv(monkeypatch, tools, address):
    fake = _fake(monkeypatch, FakeKitty())
    env = {"KITTY_WINDOW_ID": "2", "KITTY_LISTEN_ON": address}

    result = KittyAPI().focus_result(10, env)
    with pytest.raises(LookupError):
        KittyAPI().switch_tab("2", env)

    assert result.state == "failed"
    assert not result.selection.attempted
    assert "rejected" in result.selection.detail
    assert fake.calls == []


def test_switch_tab_rejects_non_decimal_target(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())

    assert not KittyAPI().switch_tab("2 --match all", dict(KITTY_ENV))
    assert fake.calls == []


def test_selection_succeeds_only_on_active_tab_and_window_readback(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert fake.calls == [
        ["kitten", "@", "--to", ADDRESS, "focus-window", "--match", "id:2"],
        ["kitten", "@", "--to", ADDRESS, "ls"],
    ]
    assert result.state == "partial"
    assert result.selection.succeeded
    assert not result.activation.attempted
    assert result.activation.detail == "backend does not support window activation"


def test_kitty_at_is_used_when_kitten_is_missing(monkeypatch, tools):
    del tools["kitten"]
    fake = _fake(monkeypatch, FakeKitty())

    assert KittyAPI().switch_tab("2", dict(KITTY_ENV))
    assert [argv[:2] for argv in fake.calls] == [["kitty", "@"], ["kitty", "@"]]


def test_missing_tool_fails_with_detail(monkeypatch, tools):
    tools.clear()
    fake = _fake(monkeypatch, FakeKitty())

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.selection.attempted
    assert not result.selection.succeeded
    assert result.selection.detail == "kitty remote control tool not found (kitten or kitty)"
    assert fake.calls == []


def test_timeout_fails_with_detail(monkeypatch, tools):
    monkeypatch.setattr(kitty, "_run", lambda argv: None)

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.state == "failed"
    assert result.selection.detail == "kitty focus-window did not complete within 5s"


def test_run_returns_none_on_timeout_and_missing_tool(monkeypatch):
    seen = {}

    def timeout(argv, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(kitty.subprocess, "run", timeout)
    assert kitty._run(["kitten", "@", "ls"]) is None
    assert seen["timeout"] <= 5
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["errors"] == "replace"

    def missing(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(kitty.subprocess, "run", missing)
    assert kitty._run(["kitten", "@", "ls"]) is None


def test_run_returns_nonzero_result_for_error_detail(monkeypatch):
    failed = _done(["kitten"], 1, "", "Error: boom")
    monkeypatch.setattr(kitty.subprocess, "run", lambda argv, **kwargs: failed)

    assert kitty._run(["kitten"]) is failed


@pytest.mark.parametrize(
    ("stderr", "detail"),
    [
        (
            "Error: Failed to connect to unix:/tmp/x/rc.sock with error: dial unix"
            " /tmp/x/rc.sock: connect: no such file or directory",
            "kitty focus-window: remote control socket refused or missing"
            " (kitty closed or remote control off)",
        ),
        (
            "Error: Failed to connect to unix:/tmp/x/rc.sock with error: dial unix"
            " /tmp/x/rc.sock: connect: connection refused",
            "kitty focus-window: remote control socket refused or missing"
            " (kitty closed or remote control off)",
        ),
        (
            "Error: Remote control is disabled. Add allow_remote_control to your kitty.conf",
            "kitty focus-window: remote control is disabled (allow_remote_control)",
        ),
        (
            "Error: Remote control is allowed over a socket only",
            "kitty focus-window: remote control is allowed over a socket only",
        ),
        (
            "Error: The user rejected this password or it is disallowed",
            "kitty focus-window: remote control password was refused",
        ),
        (
            "Error: No matching windows for expression: id:2",
            "kitty focus-window: target window no longer exists",
        ),
        ("Error: something\nelse", "kitty focus-window exited 2: Error: something"),
        ("", "kitty focus-window exited 2"),
    ],
)
def test_nonzero_exit_fails_with_specific_detail(monkeypatch, tools, stderr, detail):
    fake = _fake(monkeypatch, FakeKitty(select=_done([], 2, "", stderr)))

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.state == "failed"
    assert result.selection.attempted
    assert result.selection.detail == detail
    assert len(fake.calls) == 1


def test_stale_window_id_fails(monkeypatch, tools):
    stale = _done([], 1, "", "Error: No matching windows for expression: id:2")
    _fake(monkeypatch, FakeKitty(select=stale))

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert not result.selection.succeeded
    assert result.selection.detail == "kitty focus-window: target window no longer exists"


def test_window_missing_from_readback_fails(monkeypatch, tools):
    listing = _listing()
    listing[0]["tabs"][1]["windows"] = [{"id": 3, "is_active": True}]
    _fake(monkeypatch, FakeKitty(listing=listing))

    with pytest.raises(RuntimeError, match="target window no longer exists"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))


@pytest.mark.parametrize(
    "listing",
    [
        _listing(active_window=3),
        _listing(active_tab=False),
        _listing(active_window=3, active_tab=False),
    ],
)
def test_readback_mismatch_fails(monkeypatch, tools, listing):
    _fake(monkeypatch, FakeKitty(listing=listing))

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.state == "failed"
    assert not result.selection.succeeded
    assert result.selection.detail == (
        "kitty ls readback: target window is not active in the active tab"
    )


def test_is_focused_alone_is_not_selection_proof(monkeypatch, tools):
    listing = _listing(active_window=3)
    window = listing[0]["tabs"][1]["windows"][0]
    window["is_focused"] = True
    listing[0]["is_focused"] = True
    _fake(monkeypatch, FakeKitty(listing=listing))

    with pytest.raises(RuntimeError, match="not active"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))


def test_truthy_non_boolean_active_flags_are_not_proof(monkeypatch, tools):
    listing = _listing()
    listing[0]["tabs"][1]["is_active"] = "yes"
    _fake(monkeypatch, FakeKitty(listing=listing))

    with pytest.raises(RuntimeError, match="not active"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))


@pytest.mark.parametrize(
    "stdout",
    ["", "not json", "{\"tabs\": []}", "[1]", "[{\"tabs\": [{\"windows\": [{}]}]}]", "null"],
)
def test_malformed_readback_fails(monkeypatch, tools, stdout):
    _fake(monkeypatch, FakeKitty(ls_stdout=stdout))

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.state == "failed"
    assert result.selection.detail == "kitty ls readback returned malformed JSON"


def test_readback_timeout_and_nonzero_fail(monkeypatch, tools):
    _fake(monkeypatch, FakeKitty(ls_result=None))
    with pytest.raises(RuntimeError, match="ls readback did not complete within 5s"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))

    refused = _done([], 1, "", "Error: Failed to connect to unix:/tmp/x: connection refused")
    _fake(monkeypatch, FakeKitty(ls_result=refused))
    with pytest.raises(RuntimeError, match="ls readback: remote control socket refused"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))


def test_error_detail_strips_control_characters(monkeypatch, tools):
    noisy = _done([], 3, "", "\x1b[31mError:\x07 odd\x00\x9b failure " + "z" * 200)
    _fake(monkeypatch, FakeKitty(select=noisy))

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    detail = result.selection.detail
    assert detail.startswith("kitty focus-window exited 3: [31mError: odd failure")
    assert detail.isprintable()
    assert len(detail) <= 120


def test_activation_is_never_claimed(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())
    api = KittyAPI()

    assert api.selection_supported
    assert not api.activation_supported
    assert not api.deferred_selection_readback
    assert not api.raise_window("2", dict(KITTY_ENV))
    assert fake.calls == []
    assert api.name == "kitty"


def test_boolean_window_id_in_readback_is_not_the_target(monkeypatch, tools):
    listing = [{"tabs": [{"is_active": True, "windows": [{"id": True, "is_active": True}]}]}]
    _fake(monkeypatch, FakeKitty(listing=listing))

    with pytest.raises(RuntimeError, match="no longer exists"):
        KittyAPI().switch_tab("1", {"KITTY_WINDOW_ID": "1", "KITTY_LISTEN_ON": ADDRESS})
