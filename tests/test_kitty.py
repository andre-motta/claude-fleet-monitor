import json
import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import kitty, tmux
from claude_fleet_monitor.terminal_apis.kitty import KittyAPI
from claude_fleet_monitor.terminal_apis.parent import activate_parent
from claude_fleet_monitor.terminal_apis.tmux import TmuxAPI
from tests.terminal_env import clear_terminal_markers

ADDRESS = "unix:/tmp/fleet-kitty-test/rc.sock"
KITTY_PID = 500
KITTY_ENV = {"KITTY_WINDOW_ID": "2", "KITTY_LISTEN_ON": ADDRESS, "KITTY_PID": str(KITTY_PID)}
NO_QDBUS = "kitty window activation needs KDE Plasma KWin; qdbus not found"


def _process(pid, ppid, name):
    return SimpleNamespace(pid=pid, ppid=ppid, name=name)


def _listing(active_window=2, active_tab=True, other_active=False):
    return [
        {
            "id": 1,
            "is_focused": False,
            "tabs": [
                {
                    "id": 1,
                    "is_active": not active_tab,
                    "windows": [
                        {"id": 1, "pid": 8, "is_active": True, "is_focused": False}
                    ],
                },
                {
                    "id": 2,
                    "is_active": active_tab,
                    "windows": [
                        {"id": 2, "pid": 9, "is_active": active_window == 2,
                         "is_focused": False},
                        {"id": 3, "pid": 7,
                         "is_active": active_window == 3 or other_active},
                    ],
                },
            ],
        }
    ]


def _done(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


class FakeKitty:
    """Records argv and answers focus-window and ls like a kitty instance.

    ls before focus-window lists self.listing unless pre_result is set; the
    ls_stdout and ls_result overrides apply to the readback after it.
    """

    def __init__(self, select=None, listing=None, ls_stdout=None, ls_result="ok",
                 pre_result="ok"):
        self.calls = []
        self.select = select
        self.listing = _listing() if listing is None else listing
        self.ls_stdout = ls_stdout
        self.ls_result = ls_result
        self.pre_result = pre_result

    def __call__(self, argv):
        self.calls.append(list(argv))
        if "focus-window" in argv:
            return _done(argv) if self.select is None else self.select
        if not any("focus-window" in call for call in self.calls):
            if self.pre_result is None or isinstance(
                self.pre_result, subprocess.CompletedProcess
            ):
                return self.pre_result
            return _done(argv, stdout=json.dumps(self.listing))
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
def processes(monkeypatch):
    """A session under kitty 500 whose windows' children are 9, 8 and 7; no KWin."""
    tree = {
        10: _process(10, 9, "claude"),
        9: _process(9, KITTY_PID, "bash"),
        8: _process(8, KITTY_PID, "bash"),
        7: _process(7, KITTY_PID, "bash"),
        KITTY_PID: _process(KITTY_PID, 1, "kitty"),
    }
    monkeypatch.setattr(kitty.discovery, "get_process_info", tree.get)
    monkeypatch.setattr(kitty, "resolve_qdbus", lambda: None)
    monkeypatch.setattr(
        kitty, "kwin_available", lambda executable: pytest.fail("no KWin in tests")
    )
    return tree


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

    assert KittyAPI.capture_env() == {
        "KITTY_WINDOW_ID": "7",
        "KITTY_LISTEN_ON": ADDRESS,
        "KITTY_PID": "4242",
    }


@pytest.mark.parametrize("value", ["", "0x10", "-5", "12 ", "4242;rm", "1" * 13])
def test_capture_env_omits_invalid_kitty_pid(monkeypatch, value):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("KITTY_WINDOW_ID", "7")
    monkeypatch.setenv("KITTY_PID", value)

    assert KittyAPI.capture_env() == {"KITTY_WINDOW_ID": "7"}


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


def test_find_tab_returns_owned_window_id(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())

    assert KittyAPI().find_tab(10, dict(KITTY_ENV)) == "2"
    assert fake.calls == [["kitten", "@", "--to", ADDRESS, "ls"]]


@pytest.mark.parametrize("env", [{}, {"KITTY_LISTEN_ON": ADDRESS}, {"KITTY_WINDOW_ID": "x"}])
def test_find_tab_is_truthfully_none_without_window_id(env):
    assert KittyAPI().find_tab(10, env) is None


def test_remote_control_off_reports_unavailable_without_processes(monkeypatch, tools):
    fake = _fake(monkeypatch, FakeKitty())
    env = {"KITTY_WINDOW_ID": "2"}

    with pytest.raises(LookupError, match="allow_remote_control and a unix: listen_on"):
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
        ["kitten", "@", "--to", ADDRESS, "ls"],
        ["kitten", "@", "--to", ADDRESS, "ls"],
        ["kitten", "@", "--to", ADDRESS, "focus-window", "--match", "id:2"],
        ["kitten", "@", "--to", ADDRESS, "ls"],
    ]
    assert result.state == "partial"
    assert result.selection.succeeded
    assert not result.activation.attempted
    assert result.activation.detail == NO_QDBUS


def test_kitty_at_is_used_when_kitten_is_missing(monkeypatch, tools):
    del tools["kitten"]
    fake = _fake(monkeypatch, FakeKitty())

    assert KittyAPI().switch_tab("2", dict(KITTY_ENV))
    assert [argv[:2] for argv in fake.calls] == [["kitty", "@"]] * 3


def test_missing_tool_fails_with_detail(monkeypatch, tools):
    tools.clear()
    fake = _fake(monkeypatch, FakeKitty())

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))
    with pytest.raises(RuntimeError, match="^kitty remote control tool not found"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))

    assert not result.selection.attempted
    assert result.selection.detail == "kitty remote control tool not found (kitten or kitty)"
    assert fake.calls == []


def test_timeout_fails_with_detail(monkeypatch, tools):
    monkeypatch.setattr(kitty, "_run", lambda argv: None)

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.state == "failed"
    assert not result.selection.attempted
    assert result.selection.detail == "kitty ls did not complete within 5s"


def test_focus_window_timeout_fails_with_detail(monkeypatch, tools):
    _fake(monkeypatch, FakeKitty(select=None))
    monkeypatch.setattr(
        kitty, "_run",
        lambda argv: None if "focus-window" in argv else _done(
            argv, stdout=json.dumps(_listing())),
    )

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.selection.attempted
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
            "Error: Remote control disallowed by window specific password",
            "kitty focus-window: remote control password was refused",
        ),
        (
            "Error: The user rejected this request",
            "kitty focus-window: remote control request was rejected",
        ),
        (
            "Error: Failed to connect to unix:/run/user/1000/password-store/kitty.sock"
            " with error: dial unix: connect: no such file or directory",
            "kitty focus-window: remote control socket refused or missing"
            " (kitty closed or remote control off)",
        ),
        (
            "Error: Failed to connect to unix:/tmp/remote control is disabled/k.sock"
            " with error: connect: connection refused",
            "kitty focus-window: remote control socket refused or missing"
            " (kitty closed or remote control off)",
        ),
        (
            "Error: Failed to connect to unix:/tmp/no matching windows/k.sock",
            "kitty focus-window: remote control socket refused or missing"
            " (kitty closed or remote control off)",
        ),
        (
            "Remote control is disabled. Add allow_remote_control to your kitty.conf",
            "kitty focus-window: remote control is disabled (allow_remote_control)",
        ),
        (
            "Error: open /run/password/rc: permission denied",
            "kitty focus-window exited 2: Error: open /run/password/rc: permission denied",
        ),
        (
            "Error: request failed: no matching windows",
            "kitty focus-window exited 2: Error: request failed: no matching windows",
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
    assert [call[4] for call in fake.calls] == ["ls", "ls", "focus-window"]


@pytest.mark.parametrize(
    "address",
    ["tcp:127.0.0.1:5000", "fd:3", "unix:relative.sock"],
)
def test_non_unix_listen_on_reports_unix_socket_requirement(
    monkeypatch, tools, address
):
    monkeypatch.setenv("KITTY_WINDOW_ID", "2")
    monkeypatch.setenv("KITTY_LISTEN_ON", address)
    fake = _fake(monkeypatch, FakeKitty())

    env = KittyAPI.capture_env()
    result = KittyAPI().focus_result(10, env)

    assert "KITTY_LISTEN_ON" not in env
    assert not result.selection.attempted
    assert result.selection.detail == (
        "kitty remote control unavailable: needs allow_remote_control and a unix:"
        " listen_on socket"
    )
    assert fake.calls == []


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


def test_capabilities_claim_activation_but_not_as_a_parent():
    api = KittyAPI()

    assert api.selection_supported
    assert api.activation_supported
    assert not api.activation_before_selection
    assert not api.deferred_selection_readback
    assert not api.parent_activation_supported
    assert api.name == "kitty"


def test_boolean_window_id_in_readback_is_not_the_target(monkeypatch, tools):
    listing = [{"tabs": [{"is_active": True, "windows": [{"id": True, "is_active": True}]}]}]
    _fake(monkeypatch, FakeKitty(listing=listing))

    with pytest.raises(RuntimeError, match="no longer exists"):
        KittyAPI().switch_tab("1", {**KITTY_ENV, "KITTY_WINDOW_ID": "1"})


ACTIVATION_ENV = dict(KITTY_ENV)
QDBUS = "/usr/bin/qdbus-qt6"


class FakeDesktop(FakeKitty):
    """One kitty process whose OS window focus follows a fake KWin activation."""

    def __init__(self, os_windows=1, focused=False, confirms=True, accepts=True,
                 focus_delay=0):
        listing = _listing()
        listing[0]["is_focused"] = focused
        for extra in range(2, os_windows + 1):
            listing.append({"id": extra, "is_focused": False, "tabs": []})
        super().__init__(listing=listing)
        self.confirms = confirms
        self.accepts = accepts
        self.focus_delay = focus_delay
        self.kwin = []
        self.order = []

    def __call__(self, argv):
        self.order.append(argv[-1] if argv[-1] == "ls" else argv[4])
        if argv[-1] == "ls" and self.kwin and self.accepts:
            if self.focus_delay:
                self.focus_delay -= 1
            else:
                self.listing[0]["is_focused"] = True
        return super().__call__(argv)

    def activate(self, executable, owner_pid, **kwargs):
        self.order.append("kwin")
        self.kwin.append((executable, owner_pid, kwargs))
        if isinstance(self.confirms, Exception):
            raise self.confirms
        return self.confirms


@pytest.fixture
def desktop(monkeypatch, tools, processes):
    def install(**kwargs):
        fake = FakeDesktop(**kwargs)
        _fake(monkeypatch, fake)
        monkeypatch.setattr(kitty, "activate_owned_window", fake.activate)
        return fake

    tree = processes
    monkeypatch.setattr(kitty, "resolve_qdbus", lambda: QDBUS)
    monkeypatch.setattr(kitty, "kwin_available", lambda executable: True)
    monkeypatch.setattr(kitty, "ACTIVATION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(kitty, "ACTIVATION_STABLE_SECONDS", 0)
    install.tree = tree
    return install


def test_activation_confirmed_by_kitty_focus_readback(desktop):
    fake = desktop()
    api = KittyAPI()

    result = api.focus_result(10, dict(ACTIVATION_ENV))

    assert result.state == "complete"
    assert result.selection.succeeded
    assert result.activation.succeeded
    assert result.activation.detail == "window activation"
    assert fake.order == [
        "ls", "ls", "ls", "focus-window", "ls", "ls", "kwin", "ls", "ls"
    ]
    assert api.raise_requested
    assert fake.kwin == [
        (QDBUS, KITTY_PID, {"plugin_prefix": "claude-fleet-kitty", "report": True})
    ]


def test_activation_waits_for_late_focus(desktop, monkeypatch):
    monkeypatch.setattr(kitty, "ACTIVATION_SETTLE_SECONDS", 5)
    monkeypatch.setattr(kitty, "ACTIVATION_POLL_SECONDS", 0)
    fake = desktop(focus_delay=2)

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.order == ["ls", "kwin", "ls", "ls", "ls", "ls"]


def test_refused_activation_times_out_with_detail(desktop):
    fake = desktop(accepts=False)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert result.state == "partial"
    assert result.activation.attempted and not result.activation.succeeded
    assert result.activation.detail == (
        "kitty did not report its OS window focused within 0s (KWin focus"
        " stealing prevention may have refused it)"
    )
    assert len(fake.kwin) == 1


def test_unconfirmed_kwin_activation_fails_without_readback(desktop):
    fake = desktop(confirms=False)
    api = KittyAPI()

    with pytest.raises(RuntimeError, match=(
        "^KWin did not confirm a single normal window owned by kitty process 500$"
    )):
        api.raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.order == ["ls", "kwin"]
    assert api.raise_requested


def test_failed_kwin_script_or_precheck_is_no_raise_request(desktop):
    fake = desktop(confirms=kitty.KWinScriptError("KWin script could not be run"))
    api = KittyAPI()

    with pytest.raises(RuntimeError, match="could not be run"):
        api.raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    fake.listing.append({"id": 9, "is_focused": False, "tabs": []})
    with pytest.raises(RuntimeError, match="2 OS windows"):
        api.raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert not api.raise_requested


def test_stale_focus_without_kwin_window_is_not_activation(desktop):
    fake = desktop(focused=True, confirms=False)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert fake.listing[0]["is_focused"] is True
    assert not result.activation.succeeded
    assert "KWin did not confirm" in result.activation.detail


def test_already_focused_window_confirmed_by_kwin_succeeds(desktop):
    fake = desktop(focused=True)

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert len(fake.kwin) == 1


def test_kwin_script_failure_is_named(desktop):
    desktop(confirms=kitty.KWinScriptError("KWin script could not be loaded"))

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert result.activation.attempted
    assert result.activation.detail == "KWin script could not be loaded"


def test_missing_kitty_pid_refuses_selection_and_activation(desktop):
    fake = desktop()
    env = {key: value for key, value in KITTY_ENV.items() if key != "KITTY_PID"}

    result = KittyAPI().focus_result(10, env)
    with pytest.raises(LookupError, match="restart the agent session"):
        KittyAPI().switch_tab("2", env)

    detail = (
        "kitty process id was not captured; restart the agent session to enable"
        " kitty focus"
    )
    assert result.state == "failed"
    assert not result.selection.attempted and result.selection.detail == detail
    assert not result.activation.attempted and result.activation.detail == detail
    assert fake.calls == [] and fake.kwin == []


@pytest.mark.parametrize(
    "tree_update",
    [
        {9: _process(9, 77, "bash"), 77: _process(77, 1, "konsole")},
        {KITTY_PID: _process(KITTY_PID, 1, "konsole")},
        {9: None},
        {9: _process(9, 10, "bash")},
    ],
    ids=["not-ancestor", "not-kitty", "vanished", "cycle"],
)
def test_leaked_kitty_pid_is_rejected(desktop, tree_update):
    fake = desktop()
    desktop.tree.update(tree_update)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert not result.activation.attempted
    assert result.activation.detail == (
        "captured kitty process is not an ancestor of the session (kitty"
        " variables may have leaked from another terminal)"
    )
    assert fake.kwin == []


def test_session_pid_equal_to_kitty_pid_is_rejected(desktop):
    assert not kitty._is_kitty_ancestor(KITTY_PID, KITTY_PID)
    assert not kitty._is_kitty_ancestor(True, KITTY_PID)
    assert kitty._is_kitty_ancestor(10, KITTY_PID)


def test_ancestor_walk_is_bounded(monkeypatch):
    monkeypatch.setattr(
        kitty.discovery,
        "get_process_info",
        lambda pid: _process(pid, pid + 1, "bash"),
    )

    assert not kitty._is_kitty_ancestor(10, 10_000)


def test_ancestor_lookup_errors_are_rejection(monkeypatch):
    def broken(pid):
        raise OSError("gone")

    monkeypatch.setattr(kitty.discovery, "get_process_info", broken)

    assert not kitty._is_kitty_ancestor(10, KITTY_PID)


def test_multiple_os_windows_are_ambiguous(desktop):
    fake = desktop(os_windows=2)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert result.selection.succeeded
    assert not result.activation.attempted
    assert result.activation.detail == (
        "kitty process has 2 OS windows and KWin cannot tell them apart;"
        " activation needs one OS window per kitty process"
    )
    assert fake.kwin == []


def test_os_window_added_after_lookup_stops_before_kwin(desktop):
    fake = desktop()
    fake.listing.append({"id": 9, "is_focused": False, "tabs": []})

    with pytest.raises(RuntimeError, match="has 2 OS windows"):
        KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.kwin == []


def test_target_missing_from_single_os_window_is_unavailable(desktop):
    fake = desktop()

    result = KittyAPI().focus_result(10, {**ACTIVATION_ENV, "KITTY_WINDOW_ID": "8"})

    assert not result.activation.attempted
    assert result.activation.detail == "kitty ls readback: target window no longer exists"
    assert fake.kwin == []


def test_without_qdbus_activation_is_unavailable(desktop, monkeypatch):
    fake = desktop()
    monkeypatch.setattr(kitty, "resolve_qdbus", lambda: None)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert result.state == "partial"
    assert not result.activation.attempted
    assert result.activation.detail == (
        "kitty window activation needs KDE Plasma KWin; qdbus not found"
    )
    assert fake.kwin == []


def test_without_kwin_activation_is_unavailable(desktop, monkeypatch):
    fake = desktop()
    monkeypatch.setattr(kitty, "kwin_available", lambda executable: False)

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert not result.activation.attempted
    assert result.activation.detail == (
        "kitty window activation needs KDE Plasma KWin; KWin is not running on"
        " the session bus"
    )
    assert fake.kwin == []


def test_activation_lookup_reports_ls_failure(desktop):
    fake = desktop()
    fake.pre_result = _done([], 1, "", "Error: Failed to connect to unix:/x: refused")

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))

    assert not result.selection.attempted
    assert not result.activation.attempted
    assert result.activation.detail == (
        "kitty ls: remote control socket refused or missing (kitty closed or"
        " remote control off)"
    )


@pytest.mark.parametrize(
    "target", ["2", "500:", ":2", "500:2:1", "-1:2", "500:2 ", None, 500, "1" * 13 + ":2"]
)
def test_raise_window_rejects_malformed_targets(desktop, target):
    fake = desktop()

    assert not KittyAPI().raise_window(target, dict(ACTIVATION_ENV))
    assert fake.calls == [] and fake.kwin == []


def test_remote_control_off_reports_activation_unavailable(desktop):
    fake = desktop()

    result = KittyAPI().focus_result(10, {"KITTY_WINDOW_ID": "2", "KITTY_PID": "500"})

    assert not result.activation.attempted
    assert result.activation.detail == kitty.REMOTE_CONTROL_UNAVAILABLE
    assert fake.calls == [] and fake.kwin == []


@pytest.mark.parametrize(
    "child",
    [None, "9", True, 1, 4242],
    ids=["missing", "string", "bool", "init", "outer-kitty-child"],
)
def test_socket_of_another_kitty_is_refused_before_kwin(desktop, child):
    fake = desktop()
    desktop.tree[4242] = _process(4242, 4000, "bash")
    desktop.tree[4000] = _process(4000, 1, "kitty")
    window = fake.listing[0]["tabs"][1]["windows"][0]
    if child is None:
        del window["pid"]
    else:
        window["pid"] = child

    result = KittyAPI().focus_result(10, dict(ACTIVATION_ENV))
    with pytest.raises(RuntimeError, match="does not belong to the captured kitty"):
        KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))

    assert not result.activation.attempted
    assert result.activation.detail == (
        "kitty remote control socket does not belong to the captured kitty"
        " process (KITTY_LISTEN_ON may be inherited from an outer kitty)"
    )
    assert fake.kwin == []


def test_window_child_below_a_kitty_helper_is_accepted(desktop):
    fake = desktop()
    desktop.tree[9] = _process(9, 30, "bash")
    desktop.tree[30] = _process(30, KITTY_PID, "kitty")

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert len(fake.kwin) == 1


def test_real_kitty_is_refused_as_a_nested_parent(desktop, monkeypatch):
    fake = desktop()
    chain = {
        200: SimpleNamespace(pid=200, ppid=150, name="tmux: client",
                             executable="tmux", argv=("tmux",)),
        150: SimpleNamespace(pid=150, ppid=KITTY_PID, name="bash",
                             executable="bash", argv=("bash",)),
        KITTY_PID: SimpleNamespace(pid=KITTY_PID, ppid=1, name="kitty",
                                   executable="kitty", argv=("kitty",)),
    }
    monkeypatch.setattr(tmux.discovery, "get_process_info", chain.get)
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            stdout="200\t$7\t@12\t%34\t0\n", returncode=0
        ),
    )

    outcome = activate_parent(KittyAPI(), 200)
    with pytest.raises(
        RuntimeError,
        match="^parent terminal kitty does not support window activation$",
    ):
        TmuxAPI().raise_window("$7:@12.%34", {"TMUX": "/tmp/fleet,4400,7"})

    assert not outcome.activated and not outcome.confirmed
    assert outcome.detail == "parent terminal kitty does not support window activation"
    assert isinstance(tmux._detect_parent_terminal(200), KittyAPI)
    assert fake.calls == [] and fake.kwin == []


def _outer_kitty_owns_window(processes, listing):
    processes[4242] = _process(4242, 4000, "bash")
    processes[4000] = _process(4000, 1, "kitty")
    listing[0]["tabs"][1]["windows"][0]["pid"] = 4242


def test_inherited_outer_socket_never_selects(monkeypatch, tools, processes):
    fake = _fake(monkeypatch, FakeKitty())
    _outer_kitty_owns_window(processes, fake.listing)

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))
    with pytest.raises(RuntimeError, match="does not belong to the captured kitty"):
        KittyAPI().switch_tab("2", dict(KITTY_ENV))

    assert result.state == "failed"
    assert not result.selection.attempted
    assert result.selection.detail == (
        "kitty remote control socket does not belong to the captured kitty"
        " process (KITTY_LISTEN_ON may be inherited from an outer kitty)"
    )
    assert all("focus-window" not in call for call in fake.calls)


def test_session_outside_kitty_never_selects(monkeypatch, tools, processes):
    fake = _fake(monkeypatch, FakeKitty())
    processes[10] = _process(10, 77, "claude")
    processes[77] = _process(77, 1, "wezterm-gui")

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert not result.selection.attempted
    assert result.selection.detail == kitty.NOT_AN_ANCESTOR
    assert all("focus-window" not in call for call in fake.calls)


def test_selection_rechecks_ownership_before_focus_window(monkeypatch, tools, processes):
    fake = _fake(monkeypatch, FakeKitty())
    api = KittyAPI()
    assert api.find_tab(10, dict(KITTY_ENV)) == "2"
    _outer_kitty_owns_window(processes, fake.listing)

    with pytest.raises(RuntimeError, match="does not belong to the captured kitty"):
        api.switch_tab("2", dict(KITTY_ENV))
    assert all("focus-window" not in call for call in fake.calls)


class FlakyFocus(FakeDesktop):
    """Reports the OS window focused only on the listed readback calls."""

    def __init__(self, focused_reads):
        super().__init__()
        self.focused_reads = focused_reads
        self.reads = 0

    def __call__(self, argv):
        if argv[-1] == "ls" and self.kwin:
            self.reads += 1
            self.listing[0]["is_focused"] = self.reads in self.focused_reads
            self.order.append("ls")
            return FakeKitty.__call__(self, argv)
        return super().__call__(argv)


def _flaky(monkeypatch, focused_reads, settle=0):
    fake = FlakyFocus(focused_reads)
    _fake(monkeypatch, fake)
    monkeypatch.setattr(kitty, "activate_owned_window", fake.activate)
    monkeypatch.setattr(kitty, "ACTIVATION_SETTLE_SECONDS", settle)
    monkeypatch.setattr(kitty, "ACTIVATION_POLL_SECONDS", 0)
    return fake


def test_focus_lost_after_activation_fails(desktop, monkeypatch):
    fake = _flaky(monkeypatch, {1})

    with pytest.raises(RuntimeError, match="^kitty OS window lost focus after activation$"):
        KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.reads == 2


def test_focus_regained_and_stable_within_deadline_succeeds(desktop, monkeypatch):
    fake = _flaky(monkeypatch, {1, 3, 4}, settle=5)

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.reads == 4


def test_already_focused_still_needs_stable_readback(desktop, monkeypatch):
    fake = _flaky(monkeypatch, {1, 2})

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert fake.reads == 2


def test_stability_wait_uses_the_configured_delay(desktop, monkeypatch):
    sleeps = []
    _flaky(monkeypatch, {1, 2})
    monkeypatch.setattr(kitty, "ACTIVATION_STABLE_SECONDS", 0.2)
    monkeypatch.setattr(kitty.time, "sleep", sleeps.append)

    assert KittyAPI().raise_window(f"{KITTY_PID}:2", dict(ACTIVATION_ENV))
    assert sleeps == [0.2]


def test_leaked_variables_never_list_a_foreign_kitty(monkeypatch, tools, processes):
    fake = _fake(monkeypatch, FakeKitty())
    processes[10] = _process(10, 77, "claude")
    processes[77] = _process(77, 1, "wezterm-gui")

    assert KittyAPI().focus_result(10, dict(KITTY_ENV)).selection.detail == (
        kitty.NOT_AN_ANCESTOR
    )
    assert fake.calls == []


def test_ended_session_is_named_before_any_ls(monkeypatch, tools, processes):
    fake = _fake(monkeypatch, FakeKitty())
    del processes[10]

    result = KittyAPI().focus_result(10, dict(KITTY_ENV))

    assert result.selection.detail == "agent session process no longer exists"
    assert result.activation.detail == "agent session process no longer exists"
    assert fake.calls == []
