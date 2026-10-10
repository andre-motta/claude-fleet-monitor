"""Host-independent tests for the sock_diag and /proc peer helpers."""

import os
import struct

import pytest

from claude_fleet_monitor.terminal_apis import _unix_peers

SOCKET_PATH = "/run/user/1000/zellij/contract_version_1/session"


def _attribute(kind, payload):
    size = 4 + len(payload)
    padding = b"\0" * (_unix_peers._align(size) - size)
    return struct.pack("=HH", size, kind) + payload + padding


def _message(inode, state, name=None, peer=None):
    attributes = b""
    if name is not None:
        attributes += _attribute(_unix_peers.UNIX_DIAG_NAME, name)
    if peer is not None:
        attributes += _attribute(_unix_peers.UNIX_DIAG_PEER, struct.pack("=I", peer))
    body = struct.pack("=BBBBIII", 1, 1, state, 0, inode, 0, 0) + attributes
    return struct.pack("=IHHII", 16 + len(body), 20, 2, 1, 0) + body


def _done():
    return struct.pack("=IHHII", 20, _unix_peers.NLMSG_DONE, 2, 1, 0) + b"\0" * 4


class FakeNetlink:
    def __init__(self, datagrams):
        self.datagrams = list(datagrams)
        self.sent = []
        self.timeout = None

    def __call__(self, family, kind, protocol):
        assert (family, protocol) == (
            _unix_peers.socket.AF_NETLINK,
            _unix_peers.NETLINK_SOCK_DIAG,
        )
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        self.sent.append(data)

    def recv(self, size):
        if not self.datagrams:
            return b""
        item = self.datagrams.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(_unix_peers.sys, "platform", "linux")


def test_parse_reads_state_name_and_peer():
    table = {}
    data = (
        _message(11, 10, SOCKET_PATH.encode())
        + _message(12, 1, SOCKET_PATH.encode() + b"\0", 21)
        + _message(21, 1, peer=12)
        + _message(30, 1, b"\0abstract", 31)
    )

    assert not _unix_peers._parse(data, table)
    assert table == {
        11: (10, SOCKET_PATH.encode(), None),
        12: (1, SOCKET_PATH.encode(), 21),
        21: (1, None, 12),
        30: (1, None, 31),
    }
    assert _unix_peers._parse(_done(), table)


@pytest.mark.parametrize(
    "data",
    [
        struct.pack("=IHHII", 16, _unix_peers.NLMSG_ERROR, 0, 1, 0),
        struct.pack("=IHHII", 64, 20, 0, 1, 0),
        struct.pack("=IHHII", 8, 20, 0, 1, 0),
        struct.pack("=IHHII", 20, 20, 0, 1, 0) + b"\0" * 4,
    ],
    ids=["error", "truncated", "short-header", "short-message"],
)
def test_parse_rejects_malformed_messages(data):
    with pytest.raises(ValueError):
        _unix_peers._parse(data, {})


def test_unix_sockets_dumps_every_state_with_name_and_peer(monkeypatch, linux):
    fake = FakeNetlink([_message(12, 1, b"/s", 21), _message(21, 1) + _done()])
    monkeypatch.setattr(_unix_peers.socket, "socket", fake)

    assert _unix_peers.unix_sockets() == {12: (1, b"/s", 21), 21: (1, None, None)}
    header = struct.unpack_from("=IHHII", fake.sent[0])
    request = struct.unpack_from("=BBHIIIII", fake.sent[0], 16)
    assert header[1] == _unix_peers.SOCK_DIAG_BY_FAMILY
    assert header[2] == _unix_peers.NLM_F_REQUEST | _unix_peers.NLM_F_DUMP
    assert request[0] == _unix_peers.socket.AF_UNIX
    assert request[3] == _unix_peers.ALL_STATES
    assert request[5] == _unix_peers.UDIAG_SHOW_NAME | _unix_peers.UDIAG_SHOW_PEER
    assert 0 < fake.timeout <= _unix_peers.DUMP_TIMEOUT


@pytest.mark.parametrize(
    "datagrams",
    [
        [OSError("netlink denied")],
        [TimeoutError("timed out")],
        [b""],
        [struct.pack("=IHHII", 16, _unix_peers.NLMSG_ERROR, 0, 1, 0)],
    ],
    ids=["denied", "timeout", "closed", "error"],
)
def test_unix_sockets_failures_return_none(monkeypatch, linux, datagrams):
    monkeypatch.setattr(_unix_peers.socket, "socket", FakeNetlink(datagrams))

    assert _unix_peers.unix_sockets() is None


def test_unix_sockets_is_bounded_without_done(monkeypatch, linux):
    fake = FakeNetlink([_message(12, 1)] * 10)
    monkeypatch.setattr(_unix_peers.socket, "socket", fake)
    monkeypatch.setattr(_unix_peers, "MAX_RECEIVES", 3)

    assert _unix_peers.unix_sockets() is None
    assert len(fake.datagrams) == 7


def test_parse_keeps_only_requested_inodes():
    table = {}
    data = _message(12, 1, b"/s", 21) + _message(21, 1, peer=12)

    _unix_peers._parse(data, table, keep={12})

    assert table == {12: (1, b"/s", 21)}


def test_unix_sockets_keep_filters_the_dump(monkeypatch, linux):
    fake = FakeNetlink([_message(12, 1, b"/s", 21) + _message(21, 1) + _done()])
    monkeypatch.setattr(_unix_peers.socket, "socket", fake)

    assert _unix_peers.unix_sockets(frozenset({21})) == {21: (1, None, None)}


def test_unix_sockets_has_a_total_deadline(monkeypatch, linux):
    fake = FakeNetlink([_message(12, 1)] * 10)
    monkeypatch.setattr(_unix_peers.socket, "socket", fake)
    clock = iter([0.0, 0.5, 1.5, 2.5, 3.5])
    monkeypatch.setattr(_unix_peers.time, "monotonic", lambda: next(clock))

    assert _unix_peers.unix_sockets() is None
    assert len(fake.datagrams) == 8


def test_socket_creation_failure_returns_none(monkeypatch, linux):
    def refuse(*args):
        raise PermissionError("no netlink")

    monkeypatch.setattr(_unix_peers.socket, "socket", refuse)

    assert _unix_peers.unix_sockets() is None
    assert _unix_peers.peer_owners(50, SOCKET_PATH, "zellij") is None


def test_non_linux_returns_none_without_netlink(monkeypatch):
    monkeypatch.setattr(_unix_peers.sys, "platform", "darwin")
    monkeypatch.setattr(
        _unix_peers.socket, "socket", lambda *args: pytest.fail("no netlink off Linux")
    )

    assert _unix_peers.unix_sockets() is None
    assert _unix_peers.peer_owners(50, SOCKET_PATH, "zellij") is None


def _proc(tmp_path, pid, comm, inodes, extra=()):
    directory = tmp_path / str(pid)
    (directory / "fd").mkdir(parents=True)
    (directory / "comm").write_text(comm + "\n")
    for fd, inode in enumerate(inodes):
        os.symlink(f"socket:[{inode}]", directory / "fd" / str(fd))
    for fd, target in enumerate(extra, start=len(inodes)):
        os.symlink(target, directory / "fd" / str(fd))


@pytest.fixture
def proc(monkeypatch, tmp_path, linux):
    monkeypatch.setattr(_unix_peers, "PROC", tmp_path)
    return tmp_path


def test_socket_inodes_reads_only_socket_links(proc):
    _proc(proc, 7, "zellij", [5, 6], extra=["/dev/pts/3", "pipe:[9]"])

    assert _unix_peers.socket_inodes(7) == {5, 6}
    assert _unix_peers.socket_inodes(8) is None


def test_socket_inodes_is_bounded(proc, monkeypatch):
    _proc(proc, 7, "zellij", [1, 2, 3])
    monkeypatch.setattr(_unix_peers, "MAX_FDS", 2)

    assert _unix_peers.socket_inodes(7) is None


def test_peer_owners_maps_server_peers_to_same_uid_zellij_processes(
    proc, monkeypatch
):
    name = SOCKET_PATH.encode()
    table = {
        100: (10, name, None),
        101: (1, name, 201),
        102: (1, name, 202),
        103: (1, name, 203),
        104: (1, b"/other", 204),
        105: (7, name, 205),
    }
    monkeypatch.setattr(_unix_peers, "unix_sockets", lambda keep: kept.append(keep) or table)
    _proc(proc, 50, "zellij", [100, 101, 102, 103, 104, 105])
    _proc(proc, 300, "zellij", [201])
    _proc(proc, 301, "zellij", [202, 201])
    _proc(proc, 302, "bash", [203])
    _proc(proc, 303, "zellij", [204, 205])
    (proc / "self").mkdir()

    kept = []
    owners = _unix_peers.peer_owners(50, SOCKET_PATH, "zellij")

    assert owners == {201: {300, 301}, 202: {301}, 203: frozenset()}
    assert kept == [{100, 101, 102, 103, 104, 105}]


def test_peer_owners_without_server_fds_is_none(proc, monkeypatch):
    monkeypatch.setattr(
        _unix_peers, "unix_sockets", lambda *args: pytest.fail("no dump without server")
    )

    assert _unix_peers.peer_owners(50, SOCKET_PATH, "zellij") is None


def test_peer_owners_without_peers_skips_process_scan(proc, monkeypatch):
    monkeypatch.setattr(_unix_peers, "unix_sockets", lambda keep: {})
    monkeypatch.setattr(
        _unix_peers, "_own_processes", lambda *args: pytest.fail("no scan needed")
    )
    _proc(proc, 50, "zellij", [100])

    assert _unix_peers.peer_owners(50, SOCKET_PATH, "zellij") == {}


def test_peer_owners_never_raises(proc, monkeypatch):
    _proc(proc, 50, "zellij", [101])
    monkeypatch.setattr(
        _unix_peers, "unix_sockets", lambda keep: {101: (1, SOCKET_PATH.encode(), 201)}
    )

    def broken(*args):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(_unix_peers, "_own_processes", broken)

    assert _unix_peers.peer_owners(50, SOCKET_PATH, "zellij") is None


def test_own_processes_skip_other_uids(proc, monkeypatch):
    _proc(proc, 300, "zellij", [])
    other = os.getuid() + 1
    monkeypatch.setattr(_unix_peers.os, "getuid", lambda: other)

    assert _unix_peers._own_processes("zellij", 50) == []


@pytest.mark.parametrize(
    ("stat", "expected"),
    [
        ("300 (zellij) S 250 300 250 34816 300 4194304 0", 34816),
        ("300 (a) b) S 250 300 250 0 -1 4194304 0", 0),
        ("garbage", None),
    ],
)
def test_controlling_tty_reads_tty_nr(proc, stat, expected):
    (proc / "300").mkdir()
    (proc / "300" / "stat").write_text(stat)

    assert _unix_peers.controlling_tty(300) == expected
    assert _unix_peers.controlling_tty(301) is None
