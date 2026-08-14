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

# The audit's verdict on why this died on use #2: re-use was allowed by a
# 45-second CLOCK, not by the client actually being back. The reference tool
# has no timer at all - its button stays hidden until it sees a live remote
# game connection again. So: one busy flag, set on fire, cleared only when a
# real game-range socket is confirmed back (or the attempt failed/timed out).
# No wall-clock gate.

# The fixed blip length, Breekys' default first. Short is the point: a brief
# outbound blip skips the fight without a deep disconnect. The dial only exists
# to nudge it if 4s ever proves too short to trip the server-side skip.
BLIP_CHOICES = (4.0, 5.0, 6.0, 3.0)

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


def game_is_back(live: list[dict]) -> bool:
    """A real reconnect = an established GAME-range socket, nothing else.

    The audit found the old port-only signature ('v4 :1119') was matching the
    spared Battle.net session - which also lives on 1119 and never went
    anywhere - so every drop reported a phantom sub-second reconnect off a
    socket that never closed. The block only returns after the game socket is
    dead, so any is_game_conn socket seen afterwards is by construction the
    NEW one.
    """
    return any(dcrc.is_game_conn(c) for c in live)


class Trial:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.pid: int | None = None
        self.seen: set[str] = set()
        self.armed_until = 0.0
        self.drop_at: float | None = None
        self.blip_secs = BLIP_CHOICES[0]
        self.hung = False
        # THE re-use gate, replacing the old 45s clock: set when a cut starts,
        # cleared only on a CONFIRMED new game socket, a timeout, a failure,
        # a hang, or the client going away. State, not time.
        self.busy = False
        self._combo = False

        root.title("dc/rc trial  v3 (4s blip)")
        root.attributes("-topmost", True)
        root.configure(bg="#14140f")
        root.geometry("620x440")

        self.head = tk.Label(root, text="looking for Hearthstone...",
                             bg="#14140f", fg="#d8b45a",
                             font=("Consolas", 11, "bold"), anchor="w")
        self.head.pack(fill="x", padx=10, pady=(10, 4))

        bar = tk.Frame(root, bg="#14140f")
        bar.pack(fill="x", padx=10)
        self.b_drop = tk.Button(bar, text="SKIP FIGHT  (ctrl+alt+D)",
                                command=self.arm, bg=IDLE_BG, fg="#f0e6cc",
                                activebackground="#5a4620", relief="flat",
                                font=("Consolas", 10, "bold"))
        self.b_drop.pack(side="left", padx=(0, 6))
        self.b_blip = tk.Button(bar, text=f"SKIP {BLIP_CHOICES[0]:.0f}s (click)",
                                command=self.blip,
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

    def fire(self, ceiling: float = 4.0) -> None:
        """The fight-skip: a brief fixed traffic blip, Breekys' proven recipe.

        NOT a socket kill, and NOT a wait-until-dead deep disconnect. Both of
        those wedged the client on the second use. This blocks the game's
        traffic for a fixed few seconds so the server skips the combat, then
        lets it straight back - the shallowest disconnect that still skips.
        """
        self.armed_until = 0.0
        if self.pid is None:
            self.say("Hearthstone is gone", "ABORT")
            return
        if self.busy:
            self.say("a blip is still in flight - wait for it to finish",
                     "REFUSED")
            return
        before = established(self.pid)
        game = [c for c in before if dcrc.is_game_conn(c)]
        self.say(f"{len(before)} established, {len(game)} of them the game: "
                 + (", ".join(sorted(_sig(c) for c in game)) or "NONE"), "BEFORE")
        if not game:
            self.say("no game connection - join a match first", "VOID")
            return
        self.busy = True
        pid = self.pid
        secs = ceiling
        self.say(f"blipping the game's traffic for a fixed {secs:.0f}s "
                 f"(server skips the fight, socket left alone)", "BLIP")

        def run():
            r = dcrc.disconnect_via_firewall(pid, secs)
            self.root.after(0, lambda: self._work_done(r))

        threading.Thread(target=run, daemon=True).start()

    def cycle_secs(self) -> None:
        i = BLIP_CHOICES.index(self.blip_secs)
        self.blip_secs = BLIP_CHOICES[(i + 1) % len(BLIP_CHOICES)]
        self.b_blip.configure(text=f"SKIP {self.blip_secs:.0f}s (click)")
        self.say(f"blip length set to {self.blip_secs:.0f}s", "SET")

    def blip(self) -> None:
        """Same adaptive cut as ARM DROP, with the dial as the ceiling."""
        self.fire(ceiling=self.blip_secs)

    def _work_done(self, r: dict) -> None:
        self.say(str(r), "RESULT")
        if r.get("errors"):
            self.say("!! " + "; ".join(r["errors"]), "WARN")
        if r.get("blocked"):
            # The blip ran and lifted. The socket is usually still alive (a
            # brief blip does not kill it), so there is no reconnect to wait
            # for - the fight was skipped server-side. Ready for the next round
            # as soon as this returns.
            self.busy = False
            self.say("blip done, traffic restored - skip should have landed, "
                     "ready for the next round", "OK")
        else:
            # Not elevated, rule failed, or no game connection.
            self.busy = False
            self.say("nothing was blocked (see the error above)", "VOID")

    def restart(self) -> None:
        """Always available - it IS the escape hatch when a cycle went bad."""
        self.busy = False
        self.drop_at = None
        self.say(str(dcrc.restart_client()), "RESTART")

    # -- loop --------------------------------------------------------------

    def tick(self) -> None:
        pid = dcrc.hs_pid()
        if pid != self.pid:
            self.pid = pid
            self.seen.clear()
            self.busy = False
            self.drop_at = None
            self.say(f"Hearthstone pid = {pid}", "GAME")

        if self.pid:
            hung = dcrc.is_hung()
            if hung and not self.hung:
                self.say("THE CLIENT IS FROZEN - window still there, not "
                         "pumping messages. This is the failure mode, and it "
                         "does not show up as the process going away. "
                         "RESTART CLIENT is the only way out.", "HUNG")
                self.drop_at = None
                self.busy = False
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
                if game_is_back(live):
                    dt = time.monotonic() - self.drop_at
                    who = [c for c in live if dcrc.is_game_conn(c)]
                    self.say(f"NEW game connection {_sig(who[0])} after "
                             f"{dt:.1f}s - ready for the next press",
                             "RECONNECT")
                    self.drop_at = None
                    self.busy = False
                elif time.monotonic() - self.drop_at > RECONNECT_TIMEOUT:
                    self.say(f"no reconnect within {RECONNECT_TIMEOUT:.0f}s",
                             "TIMEOUT")
                    self.drop_at = None
                    self.busy = False
        else:
            self.head.configure(text="Hearthstone not running")

        if time.monotonic() >= self.armed_until and self.b_drop["bg"] == ARMED_BG:
            self.b_drop.configure(text="SKIP FIGHT  (ctrl+alt+D)", bg=IDLE_BG)

        # Fire only on the key-down TRANSITION. Polling every 500ms meant a
        # held combo armed on one tick and fired on the next, collapsing the
        # two-press guard into a single long press.
        combo = _key(VK_CONTROL) and _key(VK_MENU) and _key(VK_D)
        if combo and not self._combo:
            self.arm()
        self._combo = combo

        self.root.after(POLL_MS, self.tick)


def main() -> int:
    root = tk.Tk()
    Trial(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
