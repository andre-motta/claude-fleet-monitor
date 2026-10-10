"""Linux unix-socket peer discovery for multiplexer client lookup.

A sock_diag netlink dump maps the server's accepted sockets to their peer
inodes, and /proc/<pid>/fd links of the caller's own processes map those inodes
to client PIDs. Only fd links, comm and stat are read, never environ. Every
helper is bounded and returns None instead of raising.
"""

import os
from pathlib import Path
import re
import socket
import struct
import sys

NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
NLM_F_REQUEST = 0x1
NLM_F_DUMP = 0x300
NLMSG_ERROR = 2
NLMSG_DONE = 3
UDIAG_SHOW_NAME = 0x1
UDIAG_SHOW_PEER = 0x4
UNIX_DIAG_NAME = 0
UNIX_DIAG_PEER = 2
ESTABLISHED = 1
ALL_STATES = 0xFFFFFFFF
RECV_BUFFER = 1 << 16
MAX_RECEIVES = 4096
RECV_TIMEOUT = 1.0
MAX_FDS = 65536
MAX_PROCESSES = 1 << 20
PROC = Path("/proc")
_HEADER = struct.Struct("=IHHII")
_REQUEST = struct.Struct("=BBHIIIII")
_MESSAGE = struct.Struct("=BBBBIII")
_ATTRIBUTE = struct.Struct("=HH")
_SOCKET_LINK = re.compile(r"socket:\[(\d+)\]")


def _align(length: int) -> int:
    return (length + 3) & ~3


def _parse(data: bytes, table: dict) -> bool:
    """Add one netlink datagram's sockets to table; return True at NLMSG_DONE."""
    offset = 0
    while offset + _HEADER.size <= len(data):
        length, kind, _, _, _ = _HEADER.unpack_from(data, offset)
        if length < _HEADER.size or offset + length > len(data):
            raise ValueError("truncated netlink message")
        if kind == NLMSG_DONE:
            return True
        if kind == NLMSG_ERROR:
            raise ValueError("sock_diag reported an error")
        if length < _HEADER.size + _MESSAGE.size:
            raise ValueError("short sock_diag message")
        body = offset + _HEADER.size
        _, _, state, _, inode, _, _ = _MESSAGE.unpack_from(data, body)
        name = peer = None
        attribute = body + _MESSAGE.size
        end = offset + length
        while attribute + _ATTRIBUTE.size <= end:
            size, kind = _ATTRIBUTE.unpack_from(data, attribute)
            if size < _ATTRIBUTE.size or attribute + size > end:
                break
            payload = data[attribute + _ATTRIBUTE.size:attribute + size]
            if kind == UNIX_DIAG_NAME:
                name = payload.split(b"\0", 1)[0] if payload[:1] != b"\0" else None
            elif kind == UNIX_DIAG_PEER and len(payload) >= 4:
                peer = struct.unpack_from("=I", payload)[0]
            attribute += _align(size)
        table[inode] = (state, name, peer)
        offset += _align(length)
    return False


def _dump() -> dict[int, tuple[int, bytes | None, int | None]]:
    request = _REQUEST.pack(
        socket.AF_UNIX, 0, 0, ALL_STATES, 0,
        UDIAG_SHOW_NAME | UDIAG_SHOW_PEER, 0xFFFFFFFF, 0xFFFFFFFF,
    )
    header = _HEADER.pack(
        _HEADER.size + len(request), SOCK_DIAG_BY_FAMILY,
        NLM_F_REQUEST | NLM_F_DUMP, 1, 0,
    )
    table = {}
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_SOCK_DIAG) as sock:
        sock.settimeout(RECV_TIMEOUT)
        sock.sendto(header + request, (0, 0))
        for _ in range(MAX_RECEIVES):
            data = sock.recv(RECV_BUFFER)
            if not data:
                break
            if _parse(data, table):
                return table
    raise ValueError("sock_diag dump did not finish")


def unix_sockets() -> dict[int, tuple[int, bytes | None, int | None]] | None:
    """Return inode -> (state, bound name, peer inode) for every unix socket."""
    if sys.platform != "linux":
        return None
    try:
        return _dump()
    except Exception:
        return None


def socket_inodes(pid: int) -> frozenset[int] | None:
    """Return the socket inodes held open by one process."""
    try:
        directory = PROC / str(pid) / "fd"
        found = set()
        for count, entry in enumerate(os.scandir(directory)):
            if count >= MAX_FDS:
                return None
            try:
                match = _SOCKET_LINK.fullmatch(os.readlink(entry.path))
            except OSError:
                continue
            if match:
                found.add(int(match.group(1)))
        return frozenset(found)
    except Exception:
        return None


def _own_processes(comm: str, exclude: int) -> list[int]:
    uid = os.getuid()
    pids = []
    for count, entry in enumerate(os.scandir(PROC)):
        if count >= MAX_PROCESSES:
            break
        if not entry.name.isdigit() or int(entry.name) == exclude:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            if (PROC / entry.name / "comm").read_text().strip() != comm:
                continue
        except (OSError, ValueError):
            continue
        pids.append(int(entry.name))
    return pids


def peer_owners(
    server_pid: int, socket_path: str, comm: str
) -> dict[int, frozenset[int]] | None:
    """Map each peer of the server's accepted sockets to the PIDs holding it.

    Only same-UID processes named comm are searched, so a peer held by nobody
    there maps to an empty set and callers can refuse instead of guessing.
    """
    if sys.platform != "linux":
        return None
    try:
        held = socket_inodes(server_pid)
        if held is None:
            return None
        table = unix_sockets()
        if table is None:
            return None
        name = os.fsencode(socket_path)
        peers = set()
        for inode in held:
            state, bound, peer = table.get(inode, (None, None, None))
            if state == ESTABLISHED and bound == name and peer:
                peers.add(peer)
        owners = {peer: set() for peer in peers}
        if peers:
            for pid in _own_processes(comm, server_pid):
                for inode in (socket_inodes(pid) or ()):
                    if inode in owners:
                        owners[inode].add(pid)
        return {peer: frozenset(pids) for peer, pids in owners.items()}
    except Exception:
        return None


def controlling_tty(pid: int) -> int | None:
    """Return the tty_nr stat field (0 means no controlling terminal)."""
    try:
        stat = (PROC / str(pid) / "stat").read_text()
        return int(stat.rsplit(") ", 1)[1].split()[4])
    except Exception:
        return None
