"""A bench for the dc/rc idea, so the first real test produces numbers.

The open question is not whether a socket can be closed - dcrc.py proves that
against Windows' own table. It is whether Hearthstone comes BACK, how long it
takes, and whether the game's connection is IPv4 at all (SetTcpEntry has no
IPv6 form, so a v6 game session can only use the restart rung).

So this tool does three things in order, and none of them guesses:

  WATCH   sit next to a live game and log every connection Hearthstone opens
          and closes. Run this first, for a whole match, and read the log. It
          answers "which endpoint is the game server, and is it v4 or v6"
          without touching anything.
  DROP    close them, then time how long until Hearthstone has an established
          connection to that same server again. That elapsed number is the
          entire case for the feature.
  RESTART the fallback, timed the same way, so the two are comparable.

Hotkey CTRL+ALT+D fires DROP without leaving the game window. There is an
arm-then-confirm guard: a stray hotkey mid-shop should not drop you.

    python tools/dcrc_trial.py          (run tools/dcrc_trial.bat for admin)
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dcrc  # noqa: E402

LOG = ROOT / "data" / "dcrc_trial.log"
POLL_MS = 500
RECONNECT_TIMEOUT = 90.0
ARM_SECONDS = 3.0

# Two drops 17 seconds apart is what killed the client on the first run. The
# second one is also unmeasurable: the client is still settling from the first,
# so whatever it does next says nothing about a dc/rc from a steady state. One
# drop, let it fully recover, then judge.
COOLDOWN = 45.0

# 3s may simply be shorter than the client's patience, in which case it buffers
# through and nothing happens on screen. The point of the bench is to find the
# shortest block that actually trips the reconnect, so the length is a dial.
BLIP_CHOICES = (9.0, 10.0, 12.0, 8.0)

VK_CONTROL, VK_MENU, VK_D = 0x11, 0x12, 0x44

IDLE_BG, ARMED_BG = "#3a2f14", "#6b2020"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _key(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def established(pid: int) -> list[dict]:
    return [c for c in dcrc.connections(pid)
            if c["state"] == dcrc.MIB_TCP_STATE_ESTAB]


def _sig(c: dict) -> str:
    """For the watch log, where the remote address is the interesting part."""
    return f"v{c['family']} {c['remote'][0]}:{c['remote'][1]}"


def _gamesig(c: dict) -> str:
    """For deciding whether the GAME came back, where the address is useless.

    Measured across three drops: the client rejoins on a different server every
    time (34.13.221.86, then 34.91.128.107, then 34.141.204.51). Matching the
    address therefore never fires, and what did fire was the CDN link on :443
    reopening - a reported 1.1s "reconnect" that had nothing to do with the
    game. Only the port identifies the session.
    """
    return f"v{c['family']} :{c['remote'][1]}"


class Trial:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.pid: int | None = None
        self.seen: set[str] = set()
        self.armed_until = 0.0
        self.drop_at: float | None = None
        self.last_drop: float | None = None
        self.blip_secs = BLIP_CHOICES[0]
        self.hung = False
        self.targets: set[str] = set()

        root.title("dc/rc trial")
        root.attributes("-topmost", True)
        root.configure(bg="#14140f")
        root.geometry("620x440")

        self.head = tk.Label(root, text="looking for Hearthstone...",
                             bg="#14140f", fg="#d8b45a",
                             font=("Consolas", 11, "bold"), anchor="w")
        self.head.pack(fill="x", padx=10, pady=(10, 4))

        bar = tk.Frame(root, bg="#14140f")
        bar.pack(fill="x", padx=10)
        self.b_drop = tk.Button(bar, text="ARM DROP  (ctrl+alt+D)",
                                command=self.arm, bg=IDLE_BG, fg="#f0e6cc",
                                activebackground="#5a4620", relief="flat",
                                font=("Consolas", 10, "bold"))
        self.b_drop.pack(side="left", padx=(0, 6))
        self.b_blip = tk.Button(bar, text="BLIP 3s", command=self.blip,
                                bg="#14331f", fg="#dff0e0",
                                activebackground="#1f5232", relief="flat",
                                font=("Consolas", 10, "bold"))
        self.b_blip.pack(side="left", padx=(0, 2))
        tk.Button(bar, text="+", command=self.cycle_secs, bg="#14331f",
                  fg="#dff0e0", activebackground="#1f5232", relief="flat",
                  font=("Consolas", 10, "bold")).pack(side="left", padx=(0, 6))
        tk.Button(bar, text="RESTART CLIENT", command=self.restart,
                  bg="#241f18", fg="#c9c1b0", activebackground="#3a3228",
                  relief="flat", font=("Consolas", 10)).pack(side="left")

        self.txt = tk.Text(root, bg="#0e0e0a", fg="#c9c1b0", relief="flat",
                           font=("Consolas", 9), wrap="none")
        self.txt.pack(fill="both", expand=True, padx=10, pady=10)

        LOG.parent.mkdir(parents=True, exist_ok=True)
        # A block rule left behind by a crash would leave the game unable to
        # connect at all, with nothing on screen explaining why.
        dcrc.clear_block_rule()
        root.protocol("WM_DELETE_WINDOW",
                      lambda: (dcrc.clear_block_rule(), root.destroy()))
        self.say(f"log -> {LOG}")
        self.say(f"elevated: {dcrc.is_admin()}"
                 + ("" if dcrc.is_admin() else "   <- DROP will fail, use the .bat"))
        self.tick()

    # -- output ------------------------------------------------------------

    def say(self, msg: str, event: str = "NOTE") -> None:
        line = f"{_stamp()} | {event:<9} | {msg}"
        self.txt.insert("end", line + "\n")
        self.txt.see("end")
        try:
            with LOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    # -- actions -----------------------------------------------------------

    def arm(self) -> None:
        """First press arms, a second press inside the window fires."""
        now = time.monotonic()
        if now < self.armed_until:
            self.fire()
            return
        self.armed_until = now + ARM_SECONDS
        self.b_drop.configure(text=f"CONFIRM within {ARM_SECONDS:.0f}s",
                              bg=ARMED_BG)
        self.say("armed", "ARM")

    def fire(self) -> None:
        self.armed_until = 0.0
        if self.pid is None:
            self.say("Hearthstone is gone", "ABORT")
            return
        if self.last_drop is not None:
            waited = time.monotonic() - self.last_drop
            if waited < COOLDOWN:
                self.say(f"{COOLDOWN - waited:.0f}s left of the cooldown - let "
                         "the client fully settle, or the next result means "
                         "nothing", "REFUSED")
                return
        before = established(self.pid)
        game = [c for c in before if dcrc.is_game_conn(c)]
        self.targets = {_gamesig(c) for c in game}
        self.say(f"{len(before)} established, {len(game)} of them the game: "
                 + (", ".join(sorted(_sig(c) for c in game)) or "NONE")
                 + "   | leaving alone: "
                 + ", ".join(sorted(_sig(c) for c in before
                                    if not dcrc.is_game_conn(c))), "BEFORE")
        r = dcrc.drop_sockets(self.pid)
        self.say(str(r), "DROP")
        if r["dropped"]:
            self.drop_at = self.last_drop = time.monotonic()
            self.say(f"timing the game socket back on {sorted(self.targets)}",
                     "WAIT")
        else:
            self.targets = set()

    def cycle_secs(self) -> None:
        i = BLIP_CHOICES.index(self.blip_secs)
        self.blip_secs = BLIP_CHOICES[(i + 1) % len(BLIP_CHOICES)]
        self.b_blip.configure(text=f"BLIP {self.blip_secs:.0f}s")
        self.say(f"blip length set to {self.blip_secs:.0f}s", "SET")

    def blip(self) -> None:
        """Packet loss for 3s, socket untouched. No arming: unlike a drop this
        does not hang the client up, it only makes it wait."""
        if self.pid is None:
            self.say("Hearthstone is gone", "ABORT")
            return
        if self.last_drop is not None:
            waited = time.monotonic() - self.last_drop
            if waited < COOLDOWN:
                self.say(f"{COOLDOWN - waited:.0f}s left of the cooldown",
                         "REFUSED")
                return
        pid = self.pid
        self.targets = {_gamesig(c) for c in established(pid)
                        if dcrc.is_game_conn(c)} or {"v4 :1119"}
        secs = self.blip_secs
        self.say(f"blocking the game's traffic for a full {secs:.0f}s, held "
                 f"the whole time, sockets untouched "
                 f"(watching {sorted(self.targets)})", "BLIP")
        self.last_drop = time.monotonic()

        def run():
            r = dcrc.disconnect_via_firewall(pid, secs)
            self.root.after(0, lambda: self._blip_done(r))

        threading.Thread(target=run, daemon=True).start()

    def _blip_done(self, r: dict) -> None:
        self.say(str(r), "BLIP")
        if r.get("errors"):
            self.say("!! " + "; ".join(r["errors"]), "WARN")
        # Only time a reconnect when there was a disconnect. Otherwise the
        # still-open game socket is sitting right there at the next poll and
        # gets reported as a triumphant sub-second recovery, which is what
        # every misleading RECONNECT line in this log has been.
        if r.get("dropped") or r.get("blocked"):
            self.drop_at = time.monotonic()
        else:
            self.targets = set()
            self.say("nothing was disconnected, so there is nothing to time",
                     "VOID")

    def restart(self) -> None:
        if self.pid is None:
            self.say("Hearthstone is gone", "ABORT")
            return
        self.targets = {_gamesig(c) for c in established(self.pid)
                        if dcrc.is_game_conn(c)} or {"v4 :1119"}
        self.say(str(dcrc.restart_client()), "RESTART")
        self.drop_at = time.monotonic()

    # -- loop --------------------------------------------------------------

    def tick(self) -> None:
        pid = dcrc.hs_pid()
        if pid != self.pid:
            self.pid = pid
            self.seen.clear()
            self.say(f"Hearthstone pid = {pid}", "GAME")

        if self.pid:
            hung = dcrc.is_hung()
            if hung and not self.hung:
                self.say("THE CLIENT IS FROZEN - window still there, not "
                         "pumping messages. This is the failure mode, and it "
                         "does not show up as the process going away. "
                         "RESTART CLIENT is the only way out.", "HUNG")
                self.drop_at = None
            self.hung = hung

            live = established(self.pid)
            sigs = {_sig(c) for c in live}
            for s in sorted(sigs - self.seen):
                self.say(s, "OPEN")
            for s in sorted(self.seen - sigs):
                self.say(s, "CLOSE")
            self.seen = sigs

            self.head.configure(
                text=f"pid {self.pid}   established {len(live)}"
                     f"   v4 {sum(c['family'] == 4 for c in live)}"
                     f"   v6 {sum(c['family'] == 6 for c in live)}")

            if self.drop_at is not None:
                back = {_gamesig(c) for c in live} & self.targets
                if back:
                    dt = time.monotonic() - self.drop_at
                    self.say(f"back on {sorted(back)[0]} after {dt:.1f}s",
                             "RECONNECT")
                    self.drop_at = None
                    self.targets = set()
                elif time.monotonic() - self.drop_at > RECONNECT_TIMEOUT:
                    self.say(f"no reconnect within {RECONNECT_TIMEOUT:.0f}s",
                             "TIMEOUT")
                    self.drop_at = None
        else:
            self.head.configure(text="Hearthstone not running")

        if time.monotonic() >= self.armed_until and self.b_drop["bg"] == ARMED_BG:
            self.b_drop.configure(text="ARM DROP  (ctrl+alt+D)", bg=IDLE_BG)

        if _key(VK_CONTROL) and _key(VK_MENU) and _key(VK_D):
            self.arm()

        self.root.after(POLL_MS, self.tick)


def main() -> int:
    root = tk.Tk()
    Trial(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
