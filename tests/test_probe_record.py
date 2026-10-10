"""Schema and privacy checks for the terminal capability probe record."""

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "validation" / "evidence" / "terminal-probe-fedora44.json"

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="probe helper is Linux-only")

if sys.platform == "linux":
    _spec = importlib.util.spec_from_file_location(
        "probe_terminals", ROOT / "validation" / "probe_terminals.py"
    )
    probe = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(probe)


def mocked_record():
    record = {name: probe.not_installed_record("mocked") for name in probe.TERMINALS}
    record["zellij"].update({
        "installed": True, "version": "zellij 0.45.1", "readback_proven": True,
        "select_argv": ["zellij", "action", "focus-pane-id", "terminal_<id>"],
        "readback_argv": ["zellij", "action", "list-clients"],
        "recommendation": "adapter", "evidence_kind": "live",
    })
    return record


@pytest.fixture
def evidence():
    return json.loads(EVIDENCE.read_text())


def test_committed_evidence_matches_schema(evidence):
    assert probe.validate_record(evidence) == []
    assert set(probe.TERMINALS) <= set(evidence)


def test_committed_evidence_records_every_terminal_honestly(evidence):
    for name in probe.TERMINALS:
        entry = evidence[name]
        assert isinstance(entry["installed"], bool)
        if entry["recommendation"] == "adapter":
            assert entry["readback_proven"] is True
            assert entry["evidence_kind"] == "live"
            assert entry["select_argv"] and entry["readback_argv"]
        assert entry["activation_readback"]["status"] != "verified"
    assert evidence["wezterm"]["installed"] is False
    assert evidence["wezterm"]["recommendation"] == "none"
    assert evidence["wezterm"]["reason"] == "skipped by CTO decision"
    assert evidence["terminator"]["recommendation"] == "none"


def test_committed_evidence_cleanup_and_isolation(evidence):
    meta = evidence["probe"]
    assert meta["kwin_calls"] == 0
    assert meta["user_config_unchanged"] is True
    assert meta["cleanup"] == {"survivors": 0, "marker_strays_after_run": 0}
    for name in probe.TERMINALS:
        cleanup = evidence[name].get("cleanup")
        if evidence[name]["installed"]:
            assert cleanup["survivors"] == 0 and cleanup["marker_strays"] == 0


def test_committed_evidence_is_public_safe(evidence):
    text = EVIDENCE.read_text()
    for forbidden in ("/home/", "/run/user/", "/tmp/fleetprobe-", "fleetprobe-"):
        assert forbidden not in text
    for entry in (evidence[name] for name in probe.TERMINALS):
        for shape in entry["env_markers"].get("own", {}).values():
            assert set(shape) == {"shape", "length"}


def test_mocked_record_is_valid():
    assert probe.validate_record(mocked_record()) == []


@pytest.mark.parametrize("terminal", ["zellij", "wezterm", "kitty", "screen", "terminator"])
def test_missing_terminal_is_rejected(terminal):
    record = mocked_record()
    del record[terminal]
    assert probe.validate_record(record) == [f"{terminal}: missing"]


@pytest.mark.parametrize("field, value", [
    ("installed", "yes"),
    ("readback_proven", None),
    ("select_argv", "zellij action"),
    ("env_markers", []),
    ("version_floor", None),
])
def test_wrong_field_type_is_rejected(field, value):
    record = mocked_record()
    record["kitty"][field] = value
    assert f"kitty.{field}: wrong type" in probe.validate_record(record)


@pytest.mark.parametrize("field, value, message", [
    ("recommendation", "maybe", "screen.recommendation: invalid"),
    ("evidence_kind", "guessed", "screen.evidence_kind: invalid"),
    ("activation_readback", {"status": "done", "method": "x"},
     "screen.activation_readback: invalid"),
    ("pid_only_find_tab", {"viable": "no", "method": "x"}, "screen.pid_only_find_tab: invalid"),
    ("select_argv", ["screen", 1], "screen.select_argv: non-string item"),
])
def test_invalid_values_are_rejected(field, value, message):
    record = mocked_record()
    record["screen"][field] = value
    assert message in probe.validate_record(record)


def test_adapter_without_readback_is_rejected():
    record = copy.deepcopy(mocked_record())
    record["zellij"]["readback_proven"] = False
    assert "zellij: adapter recommended without proven readback" in probe.validate_record(record)


def test_redactor_replaces_private_values_longest_first():
    redact = probe.Redactor({"/home/someone": "<home>", "someone": "<user>",
                             "/tmp/fleetprobe-1234-x": "<probe_tmp>", "": "<empty>"})
    text = redact("unix:/tmp/fleetprobe-1234-x/k.sock /home/someone/bin someone")
    assert text == "unix:<probe_tmp>/k.sock <home>/bin <user>"
    assert redact.leaks(text) == []
    assert redact.leaks("/home/someone") == ["<home>", "<user>"]


def test_value_shape_hides_identifiers():
    redact = probe.Redactor({"/tmp/p": "<probe_tmp>"})
    assert probe.value_shape("urn:uuid:5ff63aa5-c646-4f57-945b-23cfc7e03554", redact) \
        == "urn:uuid:<uuid>"
    assert probe.value_shape("12345.fleet", redact) == "<digits>.fleet"
    assert probe.value_shape("unix:/tmp/p/rc.sock-77", redact) == "unix:<probe_tmp>/rc.sock-<digits>"
    assert probe.value_shape("net.example.App5ef4b219e3b005583550f2b0f9f990c3", redact) \
        == "net.example.App<hex>"


def test_marker_description_separates_own_foreign_and_leaked():
    child = {"STY": "1.s", "WINDOW": "0", "KONSOLE_VERSION": "260801", "WINDOWID": "9",
             "TMUX": "/tmp/x,1,0", "KITTY_PUBLIC_KEY": "secret", "PATH": "/usr/bin"}
    launcher = {"KONSOLE_VERSION": "260801", "WINDOWID": "9", "TMUX": "other"}
    described = probe.describe_markers(child, ("STY", "WINDOW", "KITTY_PUBLIC_KEY"),
                                       launcher, probe.Redactor({}))
    assert described["own"]["STY"] == {"shape": "<digits>.s", "length": 3}
    assert described["own"]["KITTY_PUBLIC_KEY"]["shape"] == "<opaque>"
    assert described["foreign_markers_in_child"] == ["KONSOLE_VERSION", "TMUX", "WINDOWID"]
    assert described["leaked_from_launcher"] == ["KONSOLE_VERSION", "WINDOWID"]
    assert described["launcher_terminal"] == "konsole"
