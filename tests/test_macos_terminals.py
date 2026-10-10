"""Mocked tests for the iTerm2 and Terminal.app AppleScript adapters."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import _applescript, iterm2, macos_terminal
from claude_fleet_monitor.terminal_apis._applescript import AppleScriptError
from claude_fleet_monitor.terminal_apis.iterm2 import ITerm2API
from claude_fleet_monitor.terminal_apis.macos_terminal import MacOSTerminalAPI
from claude_fleet_monitor.terminal_apis.parent import activate_parent
from tests.terminal_env import clear_terminal_markers

GUID = "6A1BC2F3-0D4E-4F5A-8B6C-7D8E9F0A1B2C"
ITERM_ID = f"w0t1p2:{GUID}"
TTY = "/dev/ttys003"
TERM_UUID = "0E7A1B2C-3D4E-4F50-9A8B-7C6D5E4F3A21"
INJECTIONS = (
    f'w0t0p0:{GUID}" & (do shell script "touch /tmp/pwned") & "',
    'w0t0p0:x" & (do shell script "id") & "',
    f"{GUID}\" & (do shell script \"id\") & \"",
    f"w0t0p0:{GUID}\nend tell",
    f"w0t0p0:{GUID} ",
    f"-e w0t0p0:{GUID}",
    "w0t0p0:12345",
    GUID,
    f"w0t0p0:{GUID[:-1]}Z",
    f"wAt0p0:{GUID}",
)


class FakeRunner:
    """Answer ``ps`` and ``osascript`` calls from per-command queues.

    The last queued answer repeats; an exception instance is raised.
    """

    def __init__(self, responses):
        self.responses = {key: list(values) for key, values in responses.items()}
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == "ps":
            key = "ps"
        else:
            assert argv[:2] == ["osascript", "-e"] and len(argv) == 4
            key = argv[2]
        queue = self.responses[key]
        value = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, tuple):
            returncode, stdout, stderr = value
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        return SimpleNamespace(returncode=0, stdout=f"{value}\n", stderr="")

    def scripts(self):
        return [call[2] for call in self.calls if call[0] == "osascript"]


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_applescript.time, "sleep", lambda seconds: None)


def _install(monkeypatch, responses):
    runner = FakeRunner(responses)
    monkeypatch.setattr(subprocess, "run", runner)
    return runner


def _no_calls(monkeypatch):
    def run(*args, **kwargs):
        pytest.fail("no subprocess may run")

    monkeypatch.setattr(subprocess, "run", run)


def _iterm(select="selected", readback="current", raise_="requested",
           front="frontmost"):
    return {
        iterm2.SELECT_SCRIPT: [select],
        iterm2.SELECTION_READBACK_SCRIPT: list(readback)
        if isinstance(readback, list) else [readback],
        iterm2.RAISE_SCRIPT: [raise_],
        iterm2.ACTIVATION_READBACK_SCRIPT: list(front)
        if isinstance(front, list) else [front],
    }


def _terminal(ps="ttys003", select="selected", readback="current",
              raise_="requested", front="frontmost"):
    return {
        "ps": [ps],
        macos_terminal.SELECT_SCRIPT: [select],
        macos_terminal.SELECTION_READBACK_SCRIPT: list(readback)
        if isinstance(readback, list) else [readback],
        macos_terminal.RAISE_SCRIPT: [raise_],
        macos_terminal.ACTIVATION_READBACK_SCRIPT: list(front)
        if isinstance(front, list) else [front],
    }


# iTerm2 identifiers


def test_iterm2_session_guid_is_the_part_after_the_colon():
    assert iterm2.session_guid(ITERM_ID) == GUID
    assert iterm2.session_guid(f"w12t3p0:{GUID.lower()}") == GUID.lower()


@pytest.mark.parametrize("value", INJECTIONS + ("", None, 7))
def test_iterm2_session_guid_rejects_malformed_values(value):
    assert iterm2.session_guid(value) is None


def test_iterm2_capture_keeps_a_well_formed_id(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ITERM_SESSION_ID", ITERM_ID)
    assert ITerm2API.capture_env() == {"ITERM_SESSION_ID": ITERM_ID}


@pytest.mark.parametrize("value", INJECTIONS)
def test_iterm2_capture_drops_a_malformed_id(monkeypatch, value):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("ITERM_SESSION_ID", value.replace("\n", " "))
    assert ITerm2API.capture_env() == {"ITERM_SESSION_ID": ""}
    assert ITerm2API.detect()


@pytest.mark.parametrize("value", INJECTIONS)
def test_iterm2_injected_id_never_reaches_osascript(monkeypatch, darwin, value):
    _no_calls(monkeypatch)
    result = ITerm2API().focus_result(4242, {"ITERM_SESSION_ID": value})
    assert result.state == "failed"
    assert not result.target_found
    assert not result.selection.attempted
    assert "rejected" in result.selection.detail
    assert not result.activation.attempted


def test_iterm2_missing_id_has_no_target(monkeypatch, darwin):
    _no_calls(monkeypatch)
    result = ITerm2API().focus_result(4242, {})
    assert not result.target_found
    assert result.selection.detail == "iTerm2 session id was not captured"


@pytest.mark.parametrize(
    "target",
    tuple(value for value in INJECTIONS if value != GUID) + (ITERM_ID, "", None),
)
def test_iterm2_operations_revalidate_the_target(monkeypatch, darwin, target):
    _no_calls(monkeypatch)
    api = ITerm2API()
    with pytest.raises(AppleScriptError, match="rejected"):
        api.switch_tab(target, {})
    with pytest.raises(AppleScriptError, match="rejected"):
        api.raise_window(target, {})
    assert not api.verify_selection(target, {})
    assert not api.raise_requested


# iTerm2 focus


def test_iterm2_focus_passes_the_guid_only_as_argv(monkeypatch, darwin):
    runner = _install(monkeypatch, _iterm())
    api = ITerm2API()
    result = api.focus_result(4242, {"ITERM_SESSION_ID": ITERM_ID})
    assert result.state == "complete"
    assert runner.scripts() == [
        iterm2.SELECT_SCRIPT,
        iterm2.SELECTION_READBACK_SCRIPT,
        iterm2.RAISE_SCRIPT,
        iterm2.ACTIVATION_READBACK_SCRIPT,
    ]
    for argv in runner.calls:
        assert argv[3] == GUID
        assert GUID not in argv[2] and "w0t1p2" not in argv[2]
        assert argv[2].startswith("on run argv\n")
    assert api.raise_requested


def test_iterm2_scripts_read_the_target_from_argv_only():
    for script in (
        iterm2.SELECT_SCRIPT,
        iterm2.SELECTION_READBACK_SCRIPT,
        iterm2.RAISE_SCRIPT,
        iterm2.ACTIVATION_READBACK_SCRIPT,
    ):
        assert "set targetId to item 1 of argv" in script
        assert "{" not in script and "do shell script" not in script
        assert script.rstrip().endswith("end run")
        assert 'application "iTerm2" is not running' in script
    assert "unique ID of current session of w" in iterm2.SELECTION_READBACK_SCRIPT
    assert "if not frontmost" in iterm2.ACTIVATION_READBACK_SCRIPT


def test_iterm2_selection_requires_readback(monkeypatch, darwin):
    _install(monkeypatch, _iterm(readback="other", front="background"))
    result = ITerm2API().focus_result(4242, {"ITERM_SESSION_ID": ITERM_ID})
    assert result.state == "failed"
    assert result.selection.attempted and not result.selection.succeeded
    assert result.selection.detail == "iTerm2 current session is a different session"
    assert result.activation.detail == "iTerm2 is not the frontmost application"


def test_iterm2_selection_confirmed_after_activation(monkeypatch, darwin):
    _install(monkeypatch, _iterm(readback=["other", "current"]))
    result = ITerm2API().focus_result(4242, {"ITERM_SESSION_ID": ITERM_ID})
    assert result.state == "complete"
    assert result.selection.detail == (
        "tab or pane selection verified after activation"
    )


def test_iterm2_missing_session_is_not_selected(monkeypatch, darwin):
    _install(monkeypatch, _iterm(select="not-found", raise_="not-found"))
    api = ITerm2API()
    result = api.focus_result(4242, {"ITERM_SESSION_ID": ITERM_ID})
    assert result.state == "failed"
    assert result.selection.detail == "iTerm2 session no longer exists"
    assert result.activation.detail == "iTerm2 session no longer exists"
    assert not api.raise_requested


def test_iterm2_activation_polls_until_frontmost(monkeypatch, darwin):
    runner = _install(
        monkeypatch, _iterm(front=["background", "other-window", "frontmost"])
    )
    assert ITerm2API().raise_window(GUID, {})
    assert runner.scripts().count(iterm2.ACTIVATION_READBACK_SCRIPT) == 3


def test_iterm2_activation_gives_up_after_bounded_readback(monkeypatch, darwin):
    runner = _install(monkeypatch, _iterm(front="minimized"))
    api = ITerm2API()
    with pytest.raises(AppleScriptError, match="iTerm2 window is minimized"):
        api.raise_window(GUID, {})
    assert (
        runner.scripts().count(iterm2.ACTIVATION_READBACK_SCRIPT)
        == _applescript.READBACK_ATTEMPTS
    )
    assert api.raise_requested


def test_iterm2_unexpected_output_is_not_success(monkeypatch, darwin):
    _install(monkeypatch, _iterm(readback="focused"))
    with pytest.raises(AppleScriptError, match="unexpected output"):
        ITerm2API().switch_tab(GUID, {})


def test_iterm2_readback_timeout_is_not_retried(monkeypatch, darwin):
    timeout = subprocess.TimeoutExpired("osascript", _applescript.TIMEOUT)
    runner = _install(monkeypatch, _iterm(front=timeout))
    api = ITerm2API()
    with pytest.raises(AppleScriptError, match="did not complete within 5s"):
        api.raise_window(GUID, {})
    assert runner.scripts().count(iterm2.ACTIVATION_READBACK_SCRIPT) == 1


def test_iterm2_raise_timeout_may_have_raised(monkeypatch, darwin):
    timeout = subprocess.TimeoutExpired("osascript", _applescript.TIMEOUT)
    _install(monkeypatch, _iterm(raise_=timeout))
    api = ITerm2API()
    with pytest.raises(AppleScriptError, match="did not complete"):
        api.raise_window(GUID, {})
    assert api.raise_requested


def test_iterm2_osascript_missing(monkeypatch, darwin):
    _install(monkeypatch, _iterm(select=FileNotFoundError("osascript")))
    with pytest.raises(AppleScriptError, match="osascript not found"):
        ITerm2API().switch_tab(GUID, {})


def test_iterm2_automation_permission_denied(monkeypatch, darwin):
    denied = (1, "", "execution error: Not authorized to send Apple events "
                     "to iTerm2. (-1743)\n")
    _install(monkeypatch, _iterm(select=denied))
    with pytest.raises(
        AppleScriptError,
        match="macOS Automation permission to control iTerm2 is not granted",
    ):
        ITerm2API().switch_tab(GUID, {})


def test_iterm2_nonzero_exit_reports_first_stderr_line(monkeypatch, darwin):
    _install(monkeypatch, _iterm(select=(1, "selected\n", "boom\x1b[0m\nmore")))
    with pytest.raises(AppleScriptError, match=r"exited 1: boom\[0m$"):
        ITerm2API().switch_tab(GUID, {})


def test_iterm2_off_macos_runs_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _no_calls(monkeypatch)
    result = ITerm2API().focus_result(4242, {"ITERM_SESSION_ID": ITERM_ID})
    assert result.state == "failed"
    assert result.selection.detail == "iTerm2 AppleScript is only available on macOS"
    assert result.activation.detail == "iTerm2 AppleScript is only available on macOS"


# AppleScript runner


@pytest.mark.parametrize(
    "argument", ["-e", "--", "", "a b", 'x"y', "x\ny", "/dev/tty\x00", "a" * 65]
)
def test_runner_rejects_unsafe_arguments(monkeypatch, darwin, argument):
    _no_calls(monkeypatch)
    with pytest.raises(AppleScriptError, match="argument rejected"):
        _applescript.run("iTerm2", "on run argv\nend run", argument)


def test_runner_uses_text_mode_and_no_stdin(monkeypatch, darwin):
    seen = {}

    def run(argv, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert _applescript.run("Terminal", "on run argv\nend run", TTY) == "ok"
    assert seen["text"] is True
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["timeout"] == _applescript.TIMEOUT


# Terminal.app target


@pytest.mark.parametrize("output", ["ttys003\n", "s003\n", "/dev/ttys003\n"])
def test_terminal_target_is_the_agent_tty(monkeypatch, darwin, output):
    runner = _install(monkeypatch, {"ps": [output]})
    assert MacOSTerminalAPI().find_tab(4242, {}) == TTY
    assert runner.calls == [["ps", "-o", "tty=", "-p", "4242"]]


@pytest.mark.parametrize("output", ["??\n", "\n", "pts/3\n", "ttys003 x\n", "console\n"])
def test_terminal_without_a_tty_has_no_target(monkeypatch, darwin, output):
    runner = _install(monkeypatch, _terminal(ps=output))
    api = MacOSTerminalAPI()
    result = api.focus_result(4242, {"TERM_SESSION_ID": TERM_UUID})
    assert result.state == "failed"
    assert not result.target_found
    assert result.selection.detail == "agent process has no controlling Terminal tty"
    assert not result.activation.attempted
    assert runner.scripts() == []


def test_terminal_never_falls_back_to_the_pid(monkeypatch, darwin):
    runner = _install(monkeypatch, _terminal(ps=(1, "", "")))
    result = MacOSTerminalAPI().focus_result(4242, {})
    assert not result.target_found
    assert result.selection.detail == "agent process is not running"
    assert runner.scripts() == []
    assert all("4242" not in " ".join(call) for call in runner.calls[1:])


@pytest.mark.parametrize("pid", [0, 1, -5, True, "4242", None])
def test_terminal_rejects_invalid_pids(monkeypatch, darwin, pid):
    _no_calls(monkeypatch)
    with pytest.raises(LookupError, match="not valid"):
        MacOSTerminalAPI().find_tab(pid, {})


def test_terminal_ps_timeout(monkeypatch, darwin):
    _install(monkeypatch, {"ps": [subprocess.TimeoutExpired("ps", 5)]})
    with pytest.raises(LookupError, match="could not be read"):
        MacOSTerminalAPI().find_tab(4242, {})


def test_terminal_off_macos_runs_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    _no_calls(monkeypatch)
    result = MacOSTerminalAPI().focus_result(4242, {})
    assert not result.target_found
    assert result.selection.detail == "Terminal tabs can only be matched on macOS"


def test_terminal_capture_keeps_only_a_uuid_session_id(monkeypatch):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.setenv("TERM_SESSION_ID", TERM_UUID)
    assert MacOSTerminalAPI.detect()
    assert MacOSTerminalAPI.capture_env() == {"TERM_SESSION_ID": TERM_UUID}
    monkeypatch.setenv("TERM_SESSION_ID", f'{TERM_UUID}" & (do shell script "id")')
    assert MacOSTerminalAPI.capture_env() == {"TERM_SESSION_ID": ""}


@pytest.mark.parametrize("value", INJECTIONS)
def test_terminal_session_id_never_reaches_osascript(monkeypatch, darwin, value):
    runner = _install(monkeypatch, _terminal())
    result = MacOSTerminalAPI().focus_result(4242, {"TERM_SESSION_ID": value})
    assert result.state == "complete"
    for argv in runner.calls[1:]:
        assert argv[3] == TTY
        assert value not in "".join(argv)


@pytest.mark.parametrize(
    "target",
    ['/dev/ttys003" & (do shell script "id") & "', "4242", "ttys003",
     "/dev/pts/3", "/dev/ttys003\n", "", None],
)
def test_terminal_operations_revalidate_the_target(monkeypatch, darwin, target):
    _no_calls(monkeypatch)
    api = MacOSTerminalAPI()
    with pytest.raises(AppleScriptError, match="rejected"):
        api.switch_tab(target, {})
    with pytest.raises(AppleScriptError, match="rejected"):
        api.raise_window(target, {})
    assert not api.verify_selection(target, {})


# Terminal.app focus


def test_terminal_focus_passes_the_tty_only_as_argv(monkeypatch, darwin):
    runner = _install(monkeypatch, _terminal())
    api = MacOSTerminalAPI()
    result = api.focus_result(4242, {"TERM_SESSION_ID": TERM_UUID})
    assert result.state == "complete"
    assert runner.scripts() == [
        macos_terminal.SELECT_SCRIPT,
        macos_terminal.SELECTION_READBACK_SCRIPT,
        macos_terminal.RAISE_SCRIPT,
        macos_terminal.ACTIVATION_READBACK_SCRIPT,
    ]
    for argv in runner.calls[1:]:
        assert argv[3] == TTY
        assert "ttys003" not in argv[2] and TERM_UUID not in argv[2]
    assert api.raise_requested


def test_terminal_scripts_read_the_target_from_argv_only():
    for script in (
        macos_terminal.SELECT_SCRIPT,
        macos_terminal.SELECTION_READBACK_SCRIPT,
        macos_terminal.RAISE_SCRIPT,
        macos_terminal.ACTIVATION_READBACK_SCRIPT,
    ):
        assert "set targetTty to item 1 of argv" in script
        assert "do shell script" not in script and "contains" not in script
        assert 'application "Terminal" is not running' in script
    assert (
        "tty of selected tab of front window"
        in macos_terminal.SELECTION_READBACK_SCRIPT
    )
    assert "if not frontmost" in macos_terminal.ACTIVATION_READBACK_SCRIPT


def test_terminal_selection_readback_mismatch(monkeypatch, darwin):
    _install(monkeypatch, _terminal(readback="other", front="other-window"))
    result = MacOSTerminalAPI().focus_result(4242, {})
    assert result.state == "failed"
    assert result.selection.detail == "Terminal front window shows a different tab"
    assert result.activation.detail == (
        "Terminal front window does not hold the agent's tab"
    )


def test_terminal_selection_without_activation_is_partial(monkeypatch, darwin):
    _install(monkeypatch, _terminal(front="background"))
    result = MacOSTerminalAPI().focus_result(4242, {})
    assert result.state == "partial"
    assert result.selection.succeeded
    assert result.activation.detail == "Terminal is not the frontmost application"


def test_terminal_not_running(monkeypatch, darwin):
    _install(monkeypatch, _terminal(select="not-running", raise_="not-running"))
    api = MacOSTerminalAPI()
    result = api.focus_result(4242, {})
    assert result.selection.detail == "Terminal is not running"
    assert result.activation.detail == "Terminal is not running"
    assert not api.raise_requested


def test_terminal_as_tmux_parent_matches_the_client_tty(monkeypatch, darwin):
    runner = _install(monkeypatch, _terminal(ps="ttys007"))
    outcome = activate_parent(MacOSTerminalAPI(), 777)
    assert outcome.confirmed and outcome.activated
    assert runner.calls[0] == ["ps", "-o", "tty=", "-p", "777"]
    assert all(argv[3] == "/dev/ttys007" for argv in runner.calls[1:])


def test_terminal_parent_unconfirmed_raise_still_counts(monkeypatch, darwin):
    _install(monkeypatch, _terminal(front="background"))
    outcome = activate_parent(MacOSTerminalAPI(), 777)
    assert outcome.activated and not outcome.confirmed
    assert "not the frontmost application" in outcome.detail


def test_iterm2_parent_without_session_id_is_not_activated(monkeypatch, darwin):
    _no_calls(monkeypatch)
    outcome = activate_parent(ITerm2API(), 777)
    assert not outcome.activated
    assert "iTerm2 session id was not captured" in outcome.detail
