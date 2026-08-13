"""Offline checks for dcrc.py. No network, no Hearthstone, no admin.

What can actually go wrong here is silent and nasty: a struct laid out wrong
reads garbage addresses, and a port left in the wrong byte order points at a
plausible-looking number that is not the port. Both would still "work" - they
would just close the wrong socket, or nothing. So the sizes and the byte order
are pinned, and the live table is cross-checked for self-consistency.

Nothing in this file can close a connection: the only drop_sockets call targets
a PID that owns none, so SetTcpEntry is never reached.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dcrc  # noqa: E402

NO_SUCH_PID = 0xFFFFFF


def test_struct_sizes():
    """Win32 layouts. If these move, every field after them reads garbage."""
    assert ctypes.sizeof(dcrc.MIB_TCPROW) == 20, "SetTcpEntry row is 5 DWORDs"
    assert ctypes.sizeof(dcrc.MIB_TCPROW_OWNER_PID) == 24
    assert ctypes.sizeof(dcrc.MIB_TCP6ROW_OWNER_PID) == 56


def test_port_byte_order():
    """Ports arrive network-order in the low half of a DWORD. 1119 is
    Blizzard's, and 0x045F stored that way reads back as 0x5F04."""
    assert dcrc._port(0x5F04) == 1119
    assert dcrc._port(0xBB01) == 443
    assert dcrc._port(0x5000) == 80
    assert dcrc._port(0) == 0


def test_tables_are_readable():
    """Both address families answer. A machine with IPv6 off returns an empty
    list rather than raising, which is the contract the overlay relies on."""
    v4 = dcrc._table(dcrc.AF_INET, dcrc.MIB_TCPROW_OWNER_PID)
    v6 = dcrc._table(dcrc.AF_INET6, dcrc.MIB_TCP6ROW_OWNER_PID)
    assert isinstance(v4, list) and isinstance(v6, list)
    assert v4, "a Windows box always has at least one IPv4 TCP row"


def test_rows_are_sane():
    """Every row decodes to a real state and a port inside 16 bits. Catches a
    shifted struct, which shows up as impossible ports long before it shows up
    as a wrong connection being closed."""
    for r in dcrc._table(dcrc.AF_INET, dcrc.MIB_TCPROW_OWNER_PID):
        assert 1 <= r.dwState <= 12, f"impossible TCP state {r.dwState}"
        assert 0 <= dcrc._port(r.dwLocalPort) <= 65535
        assert 0 <= dcrc._port(r.dwRemotePort) <= 65535


def test_connections_shape():
    rows = dcrc.connections(os.getpid())
    assert isinstance(rows, list)
    for c in rows:
        assert c["family"] in (4, 6)
        assert c["state_name"]
        assert isinstance(c["local"][1], int)


def test_connections_filter_by_pid():
    """The PID filter is the safety belt: aim at a PID nobody owns, get
    nothing. If this ever returns rows, drop_sockets would close strangers."""
    assert dcrc.connections(NO_SUCH_PID) == []


def test_drop_is_a_noop_without_targets():
    """Reports, never raises, and never reaches SetTcpEntry with no rows."""
    r = dcrc.drop_sockets(NO_SUCH_PID)
    assert r["dropped"] == 0
    assert r["established"] == 0
    assert r["targets"] == 0
    assert any("no game connection" in e for e in r["errors"])
    assert isinstance(r["elevated"], bool)


def test_loopback_is_never_a_game_connection():
    """The first live run killed four 127.0.0.1 sockets to Blizzard's own
    helper processes and the client could not recover. Loopback is out,
    always, even when it sits on a game port."""
    for host in ("127.0.0.1", "127.53.1.9"):
        assert not dcrc.is_game_conn({"family": 4, "remote": (host, 1119)}), host
    assert not dcrc.is_game_conn({"family": 6, "remote": ("::1", 1119)})


def test_bnet_session_is_spared():
    """The exact addresses from the run that killed the client.

    37.244.26.22:1119 was the Battle.net session - same address all session,
    Blizzard's own space. 34.90.248.4:1119 was that match's game server, a new
    Google Cloud address every time. Dropping both left the client with a game
    server it could reach and no login session, and it offered only "Exit
    Game". Only the changing one is ever a target.
    """
    for game in ("34.13.135.202", "34.147.20.215", "34.90.248.4",
                 "34.141.191.160", "34.90.48.255", "35.204.119.70",
                 "34.34.66.139"):
        assert dcrc.is_game_conn({"family": 4, "remote": (game, 1119)}), game
    # Every address that stayed constant across reconnects, i.e. the session.
    # 5.42.177.208 is the one that got missed and crashed the client twice.
    for session in ("37.244.26.22", "137.221.104.171", "5.42.177.208"):
        assert not dcrc.is_game_conn(
            {"family": 4, "remote": (session, 1119)}), session


def test_only_game_ports_are_targets():
    """443 is auth and the CDN. Dropping those is what broke the client."""
    assert dcrc.is_game_conn({"family": 4, "remote": ("34.13.221.86", 1119)})
    assert dcrc.is_game_conn({"family": 4, "remote": ("34.13.221.86", 3724)})
    assert not dcrc.is_game_conn({"family": 4, "remote": ("137.221.104.171", 443)})
    assert not dcrc.is_game_conn({"family": 4, "remote": ("75.2.95.102", 443)})


def test_blunt_mode_is_opt_in_only():
    """ports=() drops everything non-loopback, so it must never be what a
    caller gets by accident: the default and an explicit None both stay
    surgical."""
    assert dcrc.drop_sockets(NO_SUCH_PID)["targets"] == 0
    assert dcrc.drop_sockets(NO_SUCH_PID, ports=None)["targets"] == 0
    assert dcrc.drop_sockets(NO_SUCH_PID, ports=())["dropped"] == 0


def test_hs_pid_when_absent():
    """None or a real PID, never a crash and never 0."""
    pid = dcrc.hs_pid()
    assert pid is None or (isinstance(pid, int) and pid > 0)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {name}: {e}")
    print("all passed" if not fails else f"{fails} failed")
    raise SystemExit(1 if fails else 0)
