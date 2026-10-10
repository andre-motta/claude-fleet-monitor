import subprocess
from types import SimpleNamespace

import pytest

from claude_fleet_monitor.terminal_apis import screen, tmux
from claude_fleet_monitor.terminal_apis.screen import ScreenAPI
from tests.terminal_env import clear_terminal_markers

STY = "4242.pts-3.fleet"
SCREEN_ENV = {"STY": STY, "WINDOW": "2"}
SELECT = ["screen", "-S", STY, "-X", "select", "2"]
NUMBER = ["screen", "-S", STY, "-Q", "number"]
WINDOWS = ["screen", "-S", STY, "-Q", "windows"]


def _completed(stdout=""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


class FakeScreen:
    """Answers the _run seam like a screen server with one current window."""

    def __init__(self, current="0", displays=True, windows=("0", "1", "2")):
        self.current = current
        self.displays = displays
        self.windows = windows
        self.calls = []
        self.fail = set()
        self.detach_after_select = False

    def __call__(self, argv):
        self.calls.append(list(argv))
        command = tuple(argv[3:])
        if command[0] in self.fail:
            return None
        if command == ("-Q", "windows"):
            listing = "  ".join(f"{n} sh" for n in self.windows)
            return _completed(listing if self.displays else "")
        if command == ("-Q", "number"):
            return _completed(f"{self.current} (sh)")
        if command[:2] == ("-X", "select"):
            if self.displays and command[2] in self.windows:
                self.current = command[2]
            if self.detach_after_select:
                self.displays = False
            return _completed()
        raise AssertionError(f"unexpected argv {argv}")


@pytest.fixture
def no_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("screen must not start a process here")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def fake(monkeypatch, no_subprocess):
    server = FakeScreen()
    monkeypatch.setattr(screen, "_run", server)
    return server


def test_adapter_identity():
    api = ScreenAPI()

    assert api.name == "screen"
    assert api.selection_supported
    assert not api.activation_supported
    assert not api.raise_window("2", dict(SCREEN_ENV))
    assert "screen" not in tmux.TERMINAL_PROCESS_NAMES
    assert "SCREEN" not in tmux.TERMINAL_PROCESS_NAMES


def test_detect_and_capture_are_subprocess_free(monkeypatch, no_subprocess):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("STY", STY)
    monkeypatch.setenv("WINDOW", "2")
    monkeypatch.setenv("SCREENDIR", "/tmp/ignored")

    assert ScreenAPI.detect()
    assert ScreenAPI.capture_env() == SCREEN_ENV


def test_capture_fills_unset_and_oversized_keys_with_empty(monkeypatch, no_subprocess):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("STY", "1." + "x" * 1024)

    assert ScreenAPI.capture_env() == {"STY": "", "WINDOW": ""}
    assert not ScreenAPI.detect()


@pytest.mark.parametrize(
    ("sty", "window"),
    [
        ("", "2"),
        (STY, ""),
        (STY, "-1"),
        (STY, "2a"),
        ("pts-3.fleet", "2"),
    ],
)
def test_detect_requires_valid_sty_and_window(monkeypatch, no_subprocess, sty, window):
    clear_terminal_markers(monkeypatch)
    monkeypatch.setenv("STY", sty)
    monkeypatch.setenv("WINDOW", window)

    assert not ScreenAPI.detect()


def test_successful_selection_requires_display_and_readback(fake):
    assert ScreenAPI().switch_tab("2", dict(SCREEN_ENV))

    assert fake.calls == [WINDOWS, SELECT, NUMBER, WINDOWS]
    assert fake.current == "2"


def test_focus_result_is_partial_with_unsupported_activation(fake):
    result = ScreenAPI().focus_result(101, dict(SCREEN_ENV))

    assert result.state == "partial"
    assert result.backend == "screen"
    assert result.target_found
    assert result.selection.succeeded
    assert not result.activation.attempted
    assert result.activation.detail == "backend does not support window activation"


def test_window_number_is_normalized(fake):
    env = {"STY": STY, "WINDOW": "02"}

    assert ScreenAPI().find_tab(101, env) == "2"
    assert ScreenAPI().switch_tab("02", env)
    assert SELECT in fake.calls


def test_zero_displays_never_trusts_stale_readback(fake):
    fake.displays = False
    fake.current = "2"

    with pytest.raises(screen.ScreenFocusError, match="no attached screen display"):
        ScreenAPI().switch_tab("2", dict(SCREEN_ENV))

    assert fake.calls == [WINDOWS]


def test_display_detaching_during_selection_fails(fake):
    fake.detach_after_select = True

    result = ScreenAPI().focus_result(101, dict(SCREEN_ENV))

    assert result.state == "failed"
    assert result.selection.detail == "no attached screen display"


def test_stale_window_fails_on_readback(fake):
    fake.windows = ("0", "1")

    result = ScreenAPI().focus_result(101, dict(SCREEN_ENV))

    assert result.state == "failed"
    assert result.selection.attempted
    assert not result.selection.succeeded
    assert result.selection.detail == "screen shows window 0, not window 2"


def test_readback_mismatch_fails(fake, monkeypatch):
    original = fake.__call__

    def lagging(argv):
        if argv[3:] == ["-Q", "number"]:
            fake.calls.append(list(argv))
            return _completed("1 (other)")
        return original(argv)

    monkeypatch.setattr(screen, "_run", lagging)

    with pytest.raises(screen.ScreenFocusError, match="shows window 1, not window 2"):
        ScreenAPI().switch_tab("2", dict(SCREEN_ENV))


@pytest.mark.parametrize("output", ["", "x (sh)", "-1 (sh)", "\n"])
def test_unparseable_readback_fails(fake, monkeypatch, output):
    original = fake.__call__
    monkeypatch.setattr(
        screen,
        "_run",
        lambda argv: _completed(output) if argv[3:] == ["-Q", "number"] else original(argv),
    )

    with pytest.raises(screen.ScreenFocusError, match="window unknown, not window 2"):
        ScreenAPI().switch_tab("2", dict(SCREEN_ENV))


@pytest.mark.parametrize(
    ("failing", "detail"),
    [
        ("-Q", "screen session could not be queried"),
        ("-X", "screen could not select window 2"),
    ],
)
def test_failed_commands_name_the_step(fake, failing, detail):
    fake.fail.add(failing)

    result = ScreenAPI().focus_result(101, dict(SCREEN_ENV))

    assert result.state == "failed"
    assert result.selection.detail == detail


def test_failed_readback_names_the_step(fake, monkeypatch):
    original = fake.__call__
    monkeypatch.setattr(
        screen,
        "_run",
        lambda argv: None if argv[3:] == ["-Q", "number"] else original(argv),
    )

    with pytest.raises(screen.ScreenFocusError, match="current window could not be read"):
        ScreenAPI().switch_tab("2", dict(SCREEN_ENV))


@pytest.mark.parametrize(
    "sty",
    [
        "-X",
        "--version",
        "pts-3.fleet",
        "4242",
        "4242.",
        "4242.na me",
        "4242.a/b",
        "4242.a\x00b",
        "4242.a\nb",
        "４２.fleet",
        "4242." + "x" * 256,
        None,
        42,
    ],
)
def test_malformed_sty_never_reaches_argv(fake, sty):
    env = {"STY": sty, "WINDOW": "2"}

    assert ScreenAPI().find_tab(101, env) is None
    with pytest.raises(screen.ScreenFocusError, match="not valid"):
        ScreenAPI().switch_tab("2", env)
    result = ScreenAPI().focus_result(101, env)

    assert result.state == "failed"
    assert not result.selection.attempted
    assert fake.calls == []


@pytest.mark.parametrize("window", ["-1", "1 2", "--", "", None, 2, "２", "1" * 13])
def test_malformed_window_never_reaches_argv(fake, window):
    env = {"STY": STY, "WINDOW": window}

    assert ScreenAPI().find_tab(101, env) is None
    with pytest.raises(screen.ScreenFocusError, match="not valid"):
        ScreenAPI().switch_tab(window, dict(SCREEN_ENV))
    assert fake.calls == []


@pytest.mark.parametrize("terminal_env", [{}, {"STY": STY}, {"WINDOW": "2"}, None])
def test_pre_upgrade_record_reports_unavailable_without_commands(fake, terminal_env):
    result = ScreenAPI().focus_result(101, terminal_env)

    assert result.state == "failed"
    assert not result.target_found
    assert not result.selection.attempted
    assert result.selection.detail == "exact tab or pane target was not found"
    assert fake.calls == []


def test_run_uses_bounded_timeout_and_returns_output(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return SimpleNamespace(returncode=0, stdout="2 (sh)\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = screen._run(NUMBER)

    assert result.stdout == "2 (sh)\n"
    assert seen["argv"] == NUMBER
    assert 0 < seen["timeout"] <= 5
    assert seen["stdin"] is subprocess.DEVNULL
    assert "shell" not in seen


@pytest.mark.parametrize(
    "outcome",
    [
        FileNotFoundError("screen"),
        PermissionError("screen"),
        subprocess.TimeoutExpired(NUMBER, 5),
    ],
)
def test_run_returns_none_on_missing_cli_or_timeout(monkeypatch, outcome):
    def failing(*args, **kwargs):
        raise outcome

    monkeypatch.setattr(subprocess, "run", failing)

    assert screen._run(NUMBER) is None


def test_run_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="No screen session found.", stderr=""
        ),
    )

    assert screen._run(NUMBER) is None


@pytest.mark.parametrize(
    "outcome",
    [
        FileNotFoundError("screen"),
        subprocess.TimeoutExpired(WINDOWS, 5),
        SimpleNamespace(returncode=1, stdout="No screen session found.", stderr=""),
    ],
)
def test_missing_cli_timeout_or_gone_session_fail_selection(monkeypatch, outcome):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = ScreenAPI().focus_result(101, dict(SCREEN_ENV))

    assert result.state == "failed"
    assert result.selection.detail == "screen session could not be queried"
    assert calls == [WINDOWS]
