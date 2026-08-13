"""Drop Hearthstone's connection so the client reconnects itself.

WHY. Asked for on the release thread: a quick dc/rc button. Reconnecting is the
player's standard fix for a hung fight, a frozen shop, or animations that have
fallen behind, and doing it by hand today means quitting the client and waiting
through a full relaunch.

WHAT IT TOUCHES. Nothing inside the game. It closes a TCP socket that Windows
owns, the same act as Sysinternals TCPView's "Close Connection". The client sees
its socket die, shows its own reconnect, and rejoins the game in progress. No
game memory is read and no game file is written, so this is on the safe side of
the log-only posture and can ship in the default build (unlike native/msync).
Combat resolves on Blizzard's servers, so reconnecting cannot change a fight.

THE LADDER, fastest first:

  1. drop_sockets()  kills the established connections owned by Hearthstone.exe.
     Seconds, client stays open. Needs Administrator, and SetTcpEntry is
     IPv4-only: Windows exposes no IPv6 equivalent, so v6 rows are reported and
     skipped rather than silently counted as dropped.
  2. restart_client() taskkill + relaunch through the Battle.net handler. Works
     unelevated and over any IP version, but costs a full client start.

CLI:

    python dcrc.py            what it can see, and what it would do
    python dcrc.py --list     every connection Hearthstone owns
    python dcrc.py --drop     do it (needs an elevated shell)
    python dcrc.py --restart  the fallback path
    python dcrc.py --pid N    inspect another process (for testing without HS)
"""

from __future__ import annotations

import argparse
import ctypes
import os
import socket
import struct
import subprocess
import sys
import time
from ctypes import wintypes

# --------------------------------------------------------------------------
# Win32
# --------------------------------------------------------------------------

AF_INET, AF_INET6 = 2, 23
TCP_TABLE_OWNER_PID_ALL = 5
MIB_TCP_STATE_ESTAB = 5
MIB_TCP_STATE_DELETE_TCB = 12

ERROR_INSUFFICIENT_BUFFER = 122
ERROR_ACCESS_DENIED = 5

# Blizzard's game protocol. Measured on a live client: of the ten sockets
# Hearthstone holds open, the session is the one on 1119 and the rest are
# loopback to Blizzard's helper processes plus HTTPS to auth and the CDN. 3724
# is the older port, kept because it costs nothing to also match it.
GAME_PORTS = (1119, 3724)

# Two sockets sit on 1119, and only one of them may be closed.
#
# Measured across three drops in one session: the game server address changes
# every single time (34.13.135.202, then 34.147.20.215, then 34.90.248.4 - all
# Google Cloud, one per match), while a second 1119 connection stays on the
# SAME address all session, inside Blizzard's own space. That second one is the
# Battle.net session.
#
# Killing both is what produced the dead client: it re-grabbed a game server
# within 0.3s, then both sockets closed six seconds later and the game offered
# nothing but "Exit Game" - a game server it could reach and no login session
# left to authenticate with. So Blizzard's own ranges are spared even on a game
# port. If a future client hosts the match itself inside these ranges, this
# rule stops finding a target rather than breaking the client, and the trial
# says so in its report.
BNET_PREFIXES = ("37.244.", "137.221.", "5.42.")

# The rule behind that list, because the list alone will go stale: across every
# session measured, the GAME server is on a cloud range and its address is
# different every single reconnect (34.13.135.202, 34.147.20.215, 34.90.248.4,
# 34.141.191.160, 35.204.119.70 ...), while the session socket sits on
# Blizzard's own space at the SAME address all session (37.244.26.22 one night,
# 5.42.177.208 the next). Kill the changing one; never the constant one.
#
# Killing both is survivable exactly once. It worked on the first press and
# took the client down on the second, twice over, on two different addresses -
# which is also what HDT-Reconnector's README reports as "after several
# disconnect and reconnect, the game may crash".

TCP_STATE_NAMES = {
    1: "CLOSED", 2: "LISTEN", 3: "SYN_SENT", 4: "SYN_RCVD", 5: "ESTABLISHED",
    6: "FIN_WAIT1", 7: "FIN_WAIT2", 8: "CLOSE_WAIT", 9: "CLOSING",
    10: "LAST_ACK", 11: "TIME_WAIT", 12: "DELETE_TCB",
}


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD)]


class MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
    _fields_ = [("ucLocalAddr", ctypes.c_ubyte * 16),
                ("dwLocalScopeId", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("ucRemoteAddr", ctypes.c_ubyte * 16),
                ("dwRemoteScopeId", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwState", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD)]


class MIB_TCPROW(ctypes.Structure):
    """What SetTcpEntry takes. Deliberately NOT the _OWNER_PID shape: passing
    the six-field row here writes past the end of what the API expects."""
    _fields_ = [("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD)]


def _port(dw: int) -> int:
    """Ports arrive in network byte order inside the low half of a DWORD."""
    return ((dw & 0xFF) << 8) | ((dw >> 8) & 0xFF)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _table(af: int, row_type):
    """One GetExtendedTcpTable call, sized then filled. Returns [] rather than
    raising: a machine with IPv6 disabled answers with an error here, and that
    is a normal state, not a failure worth stopping the overlay for."""
    fn = ctypes.windll.iphlpapi.GetExtendedTcpTable
    size = wintypes.DWORD(0)
    rc = fn(None, ctypes.byref(size), False, af, TCP_TABLE_OWNER_PID_ALL, 0)
    if rc != ERROR_INSUFFICIENT_BUFFER or size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    rc = fn(buf, ctypes.byref(size), False, af, TCP_TABLE_OWNER_PID_ALL, 0)
    if rc != 0:
        return []
    count = struct.unpack_from("I", buf, 0)[0]
    # from_buffer_COPY, not a pointer into buf. Indexing a cast pointer hands
    # back structs that share this buffer's memory without keeping it alive, so
    # once this function returns they read freed bytes: usually the old values,
    # occasionally whatever was allocated over them. That decodes as impossible
    # states, and drop_sockets would then hand SetTcpEntry an address and port
    # belonging to nothing, or to somebody else's connection.
    stride = ctypes.sizeof(row_type)
    count = min(count, max(0, (len(buf) - 4) // stride))
    return [row_type.from_buffer_copy(buf, 4 + i * stride) for i in range(count)]


def connections(pid: int) -> list[dict]:
    """Every TCP connection the process owns, v4 and v6."""
    out = []
    for r in _table(AF_INET, MIB_TCPROW_OWNER_PID):
        if r.dwOwningPid != pid:
            continue
        out.append({
            "family": 4,
            "state": r.dwState,
            "state_name": TCP_STATE_NAMES.get(r.dwState, str(r.dwState)),
            "local": (socket.inet_ntoa(struct.pack("I", r.dwLocalAddr)),
                      _port(r.dwLocalPort)),
            "remote": (socket.inet_ntoa(struct.pack("I", r.dwRemoteAddr)),
                       _port(r.dwRemotePort)),
            "_row": r,
        })
    for r in _table(AF_INET6, MIB_TCP6ROW_OWNER_PID):
        if r.dwOwningPid != pid:
            continue
        out.append({
            "family": 6,
            "state": r.dwState,
            "state_name": TCP_STATE_NAMES.get(r.dwState, str(r.dwState)),
            "local": (socket.inet_ntop(socket.AF_INET6, bytes(r.ucLocalAddr)),
                      _port(r.dwLocalPort)),
            "remote": (socket.inet_ntop(socket.AF_INET6, bytes(r.ucRemoteAddr)),
                       _port(r.dwRemotePort)),
            "_row": r,
        })
    return out


# --------------------------------------------------------------------------
# Finding Hearthstone
# --------------------------------------------------------------------------

HS_EXE_DEFAULT = (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
                  + r"\Hearthstone\Hearthstone.exe")


def hs_hwnd():
    """The game window, the same handle ui.base already anchors to. It exists
    whether or not Hearthstone is the foreground app."""
    u = ctypes.windll.user32
    return (u.FindWindowW("UnityWndClass", "Hearthstone")
            or u.FindWindowW(None, "Hearthstone") or None)


def hs_pid() -> int | None:
    hwnd = hs_hwnd()
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def is_hung() -> bool:
    """Whether the game is frozen rather than gone.

    This is the actual failure mode and nothing was watching for it. After a
    few reconnects the client does not exit - it keeps its window and its
    process, stops pumping messages, and quietly loses every connection except
    loopback. Watching for the process to disappear therefore sees a healthy
    game forever, which is how a hung client got recorded as a clean 0.5s
    reconnect. IsHungAppWindow is the same test that puts "Not Responding" in
    a title bar.
    """
    hwnd = hs_hwnd()
    if not hwnd:
        return False
    return bool(ctypes.windll.user32.IsHungAppWindow(hwnd))


# --------------------------------------------------------------------------
# The two rungs
# --------------------------------------------------------------------------

def is_game_conn(c: dict) -> bool:
    """The one connection a dc/rc is actually about.

    The first live trial dropped all ten of Hearthstone's sockets at once. The
    CDN link reopened within a second and looked like a successful reconnect,
    while the client, having also lost loopback to Blizzard's helper processes
    and its auth session, could not recover and exited. Only the game socket
    should ever be closed, and loopback is never touched.
    """
    host, port = c["remote"]
    if host.startswith("127.") or host == "::1":
        return False
    if host.startswith(BNET_PREFIXES):
        return False          # the login session, see BNET_PREFIXES
    return port in GAME_PORTS


def drop_sockets(pid: int, ports: tuple[int, ...] | None = None) -> dict:
    """Close the game session's connection so the client rejoins it.

    Only the game socket goes by default (see is_game_conn). Pass an explicit
    ports tuple to target others, or () for every non-loopback connection - the
    blunt version, kept only in case a future client moves off 1119.

    Returns a report rather than raising, because the caller is a UI button and
    every failure here has a different thing to tell the player: not elevated,
    nothing to drop, or an IPv6-only session this API cannot reach.
    """
    live = [c for c in connections(pid) if c["state"] == MIB_TCP_STATE_ESTAB]
    if ports is None:
        rows = [c for c in live if is_game_conn(c)]
    elif ports:
        rows = [c for c in live if c["remote"][1] in ports
                and not c["remote"][0].startswith("127.")]
    else:
        rows = [c for c in live if not c["remote"][0].startswith("127.")
                and c["remote"][0] != "::1"]

    v4 = [c for c in rows if c["family"] == 4]
    v6 = [c for c in rows if c["family"] == 6]
    report = {"established": len(live), "targets": len(rows),
              "spared": len(live) - len(rows), "v4": len(v4),
              "v6_skipped": len(v6), "dropped": 0, "errors": [],
              "elevated": is_admin()}
    if not rows:
        report["errors"].append(
            "no game connection found on ports "
            f"{ports if ports is not None else GAME_PORTS}"
            f" ({len(live)} other connections left alone)")
        return report
    if not v4:
        report["errors"].append(
            "only IPv6 connections: SetTcpEntry has no IPv6 form, use --restart")
        return report

    fn = ctypes.windll.iphlpapi.SetTcpEntry
    for c in v4:
        src = c["_row"]
        row = MIB_TCPROW(MIB_TCP_STATE_DELETE_TCB, src.dwLocalAddr,
                         src.dwLocalPort, src.dwRemoteAddr, src.dwRemotePort)
        rc = fn(ctypes.byref(row))
        if rc == 0:
            report["dropped"] += 1
        elif rc == ERROR_ACCESS_DENIED:
            report["errors"].append("access denied: needs Administrator")
        else:
            report["errors"].append(f"{c['remote'][0]}:{c['remote'][1]} rc={rc}")
    return report


BLOCK_RULE = "bgtracker-dcrc-temp"


def hs_exe_path(pid: int) -> str | None:
    """Full image path of a running process, for the firewall rule."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def _netsh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["netsh", "advfirewall", "firewall", *args],
                          capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def clear_block_rule() -> None:
    """Remove the rule if it survived a crash. Safe to call when absent."""
    _netsh("delete", "rule", f"name={BLOCK_RULE}")


def block_briefly(pid: int, seconds: float = 3.0) -> dict:
    """Make the game's packets disappear for a moment, without closing anything.

    This is the difference that matters. Aborting the socket (drop_sockets)
    tells the client the server hung up, and it treats that as the session
    being over: measured twice on a live client, it opened a fresh game server
    within half a second and then exited anyway. Losing packets is a different
    signal entirely - the socket stays open, nothing is refused, and that is
    the condition the client's own "Reconnecting" path is written for, because
    it is what a real wifi blip looks like.

    The rule is deleted in a finally, and again at startup, because a block
    rule left behind would leave the player unable to connect at all.
    """
    exe = hs_exe_path(pid)
    report = {"exe": exe, "seconds": seconds, "blocked": False,
              "elevated": is_admin(), "errors": []}
    if not exe:
        report["errors"].append("could not read the game's exe path")
        return report

    clear_block_rule()
    add = _netsh("add", "rule", f"name={BLOCK_RULE}", "dir=out",
                 f"program={exe}", "action=block", "enable=yes")
    if add.returncode != 0:
        report["errors"].append(f"add rule failed: {add.stdout.strip()}")
        return report
    try:
        report["blocked"] = True
        time.sleep(seconds)
    finally:
        rm = _netsh("delete", "rule", f"name={BLOCK_RULE}")
        report["unblocked"] = rm.returncode == 0
        if rm.returncode != 0:
            report["errors"].append(
                f"COULD NOT REMOVE {BLOCK_RULE} - run: netsh advfirewall "
                f"firewall delete rule name={BLOCK_RULE}")
    return report


def ensure_block_rule(exe: str) -> bool:
    """Create the block rule once, disabled. Toggling an existing rule is both
    faster than add/delete and what the reference tool does."""
    show = _netsh("show", "rule", f"name={BLOCK_RULE}")
    if show.returncode == 0 and BLOCK_RULE in (show.stdout or ""):
        return True
    add = _netsh("add", "rule", f"name={BLOCK_RULE}", "dir=out",
                 f"program={exe}", "action=block", "enable=no")
    return add.returncode == 0


def set_block(on: bool) -> bool:
    r = _netsh("set", "rule", f"name={BLOCK_RULE}", "new",
               f"enable={'yes' if on else 'no'}")
    return r.returncode == 0


def disconnect_via_firewall(pid: int, seconds: float = 9.0) -> dict:
    """Block the game's traffic for a fixed spell, exactly like Vaiz's tool.

    Its defaults are DisconnectIntervalMin=8 / DisconnectIntervalMax=10, and it
    sleeps a random interval in that range with the rule enabled the WHOLE
    time. My earlier version lifted the block the moment the socket died, on
    the reasoning that the client needed its retries to get through; that was
    a deviation from the one design known to work, and it produced a client
    that reconnected in a second and then quit anyway.

    Hold it. The client is supposed to come out of this having decided it lost
    the connection, which is the state its rejoin path is written for.
    """
    exe = hs_exe_path(pid)
    report = {"exe": exe, "seconds": round(seconds, 1), "blocked": False,
              "elevated": is_admin(), "errors": []}
    if not exe:
        report["errors"].append("could not read the game's exe path")
        return report
    if not ensure_block_rule(exe):
        report["errors"].append("could not create the firewall rule "
                                "(needs Administrator)")
        return report
    if not set_block(True):
        report["errors"].append("could not enable the rule")
        return report
    report["blocked"] = True
    try:
        time.sleep(seconds)
    finally:
        report["unblocked"] = set_block(False)
        if not report["unblocked"]:
            report["errors"].append(
                f"COULD NOT DISABLE {BLOCK_RULE} - run: netsh advfirewall "
                f"firewall delete rule name={BLOCK_RULE}")
    return report


def block_until_dropped(pid: int, max_seconds: float = 20.0,
                        grace: float = 0.4) -> dict:
    """Block the game's packets only until its connection actually dies.

    A fixed duration is the wrong shape, and the 10s run proved it: the game
    socket died two seconds in, the client immediately began retrying, and it
    spent every one of those retries against a firewall still held shut. Eight
    seconds later the block lifted and the client had already given up - alive,
    but with no game connection and no intention of making one.

    So the block is held for exactly as long as it takes to do its one job, and
    dropped the instant the socket is gone. The client's next retry is the
    first one that gets through, which is the whole point.
    """
    exe = hs_exe_path(pid)
    report = {"exe": exe, "dropped": False, "held": 0.0, "max": max_seconds,
              "elevated": is_admin(), "errors": []}
    if not exe:
        report["errors"].append("could not read the game's exe path")
        return report

    def game_is_up() -> bool:
        return any(is_game_conn(c) for c in connections(pid)
                   if c["state"] == MIB_TCP_STATE_ESTAB)

    # Without this, a client that is ALREADY disconnected reports a perfect
    # result: the "has it died yet" test passes on the first poll, so the run
    # ends in 0.4s having blocked nothing, and whatever the client does next
    # gets credited to it. That happened once and read as a real measurement.
    if not game_is_up():
        report["errors"].append(
            "no game connection to interrupt - the client is already "
            "disconnected, or you are not in a match. Nothing was blocked.")
        return report

    clear_block_rule()
    add = _netsh("add", "rule", f"name={BLOCK_RULE}", "dir=out",
                 f"program={exe}", "action=block", "enable=yes")
    if add.returncode != 0:
        report["errors"].append(f"add rule failed: {add.stdout.strip()}")
        return report

    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < max_seconds:
            if not game_is_up():
                report["dropped"] = True
                break
            time.sleep(0.2)
        if report["dropped"]:
            # Long enough that the socket is really gone rather than between
            # polls, short enough to be well inside the client's retry window.
            time.sleep(grace)
        else:
            report["errors"].append(
                f"connection survived the whole {max_seconds:.0f}s - the game "
                "was probably idle, so nothing was in flight to time out")
    finally:
        report["held"] = round(time.monotonic() - t0, 1)
        rm = _netsh("delete", "rule", f"name={BLOCK_RULE}")
        report["unblocked"] = rm.returncode == 0
        if rm.returncode != 0:
            report["errors"].append(
                f"COULD NOT REMOVE {BLOCK_RULE} - run: netsh advfirewall "
                f"firewall delete rule name={BLOCK_RULE}")
    return report


def restart_client(exe: str | None = None) -> dict:
    """The unelevated fallback: end the process, let Battle.net bring it back.
    Slower by a full client start, but it needs no rights and no IPv4."""
    # A dead client is the main reason to press this. Refusing to act because
    # the process is gone gets it exactly backwards: "the game crashed, put me
    # back in" is the job. Kill first only if there is something to kill.
    pid = hs_pid()
    if pid is not None:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    path = exe or HS_EXE_DEFAULT
    # Battle.net FIRST, exe only as a fallback. Measured: launching
    # Hearthstone.exe directly brings a window up in half a second and then
    # never connects - 120s without a single game socket, and the process quit
    # on its own. The client expects Battle.net's launch handoff, so starting
    # the binary alone produces something that looks alive and is not.
    try:
        os.startfile("battlenet://WTCG")
        return {"ok": True, "killed": pid, "via": "battlenet://WTCG"}
    except Exception as e:
        try:
            if os.path.exists(path):
                subprocess.Popen([path], cwd=os.path.dirname(path))
                return {"ok": True, "killed": pid, "via": path,
                        "warning": f"Battle.net handler failed ({e}); launched "
                                   "the exe directly, which may never connect"}
        except Exception as e2:
            return {"ok": False, "killed": pid, "error": f"exe launch: {e2}"}
        return {"ok": False, "killed": pid, "error": f"relaunch failed: {e}"}


def elevate_and_drop() -> bool:
    """Re-run this module as Administrator for one drop, then exit.

    One UAC prompt per press, which is the honest v1. The polish path is a
    scheduled task registered once with highest privileges, which `schtasks
    /run` then triggers with no prompt at all.
    """
    params = f'"{os.path.abspath(__file__)}" --drop'
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 0)
    return rc > 32


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _show(pid: int) -> None:
    rows = connections(pid)
    print(f"pid {pid}: {len(rows)} connections")
    for c in sorted(rows, key=lambda c: (c["state"], c["family"])):
        print(f"  v{c['family']} {c['state_name']:<12}"
              f" {c['local'][0]}:{c['local'][1]}"
              f" -> {c['remote'][0]}:{c['remote'][1]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="show connections")
    ap.add_argument("--drop", action="store_true", help="close them (needs admin)")
    ap.add_argument("--restart", action="store_true", help="kill and relaunch")
    ap.add_argument("--pid", type=int, help="inspect another process")
    a = ap.parse_args(argv)

    pid = a.pid or hs_pid()
    if pid is None:
        print("Hearthstone is not running (no UnityWndClass window found).")
        return 1

    if a.restart:
        print(restart_client())
        return 0
    if a.drop:
        r = drop_sockets(pid)
        print(r)
        return 0 if r["dropped"] else 2
    if a.list:
        _show(pid)
        return 0

    est = [c for c in connections(pid) if c["state"] == MIB_TCP_STATE_ESTAB]
    print(f"pid {pid}, {len(est)} established "
          f"({sum(c['family'] == 4 for c in est)} v4, "
          f"{sum(c['family'] == 6 for c in est)} v6)")
    print(f"elevated: {is_admin()}")
    print("--drop closes them in place; --restart is the unelevated fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
