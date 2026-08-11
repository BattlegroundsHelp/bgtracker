"""COMBAT window - the win/tie/loss odds for the fight on screen. Only that.

Lifecycle, keyed strictly to the PowerTaskList copy of the log (the copy that
is in sync with the screen):
  opens   the instant the SCREEN enters combat
  holds   for the whole fight
  closes  the instant the SCREEN returns to the tavern

Why PTL and nothing else: GameState.DebugPrintPower() writes an ENTIRE fight -
and often the next shop - in one burst seconds AHEAD of the animation. Keying
this window off that copy is what made the odds appear one fight late, vanish
mid-fight, and leave a COMBAT header sitting over the tavern.

Because the odds are computed off that early GameState burst, they normally
arrive ~1.4s BEFORE this window opens. They are therefore stamped with the
fight's sequence number and parked; the window draws them only when the number
matches the fight it is currently showing. A result whose fight has been
superseded is never drawn - and no number is ever invented: when the sim had
nothing to say, this window says so.
"""

from __future__ import annotations

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_NAME, F_SUB, F_TITLE,
                   GOOD, LINE, PANEL_HI, SOFT, BaseWindow, rrect)


class CombatWindow(BaseWindow):
    KEY = "combat"
    TITLE = "COMBAT"
    COLUMN = "right"
    DY = 70
    RESERVE = 78
    MAX_H = 78
    WIDTH = 316
    EVENTS = ("combat", "combat_over", "odds", "game")

    def __init__(self, app):
        super().__init__(app)
        self.seq = -1          # which fight is on screen
        self.round = None
        # seq -> result. A dict, not a single slot: parking the next fight's
        # early result must never overwrite the one belonging to the fight
        # currently on screen. That is what "holds the whole fight" means.
        self.odds = {}

    def reset(self):
        self.seq, self.round = -1, None
        self.odds.clear()
        self.hide()

    def on_event(self, name, payload):
        if name == "combat":
            self.seq = payload.get("seq", self.seq + 1)
            self.round = payload.get("round")
            self.show()
        elif name == "combat_over":
            self.hide()
        elif name == "odds":
            # Park every result under its own fight; only the fight on screen
            # is ever drawn. Keep a couple of neighbours and drop the rest.
            seq = payload.get("seq")
            self.odds[seq] = payload
            for old in [s for s in self.odds if s < seq - 2]:
                del self.odds[old]
            if self.is_open and seq == self.seq:
                self.redraw()
        elif name == "game":
            self.reset()

    def _current(self):
        return self.odds.get(self.seq)

    def draw(self, c):
        rnd = f"round {self.round}" if self.round else None
        y = self.header(c, rnd, DIM, dot=BAD)
        o = self._current()
        if o is None:
            c.create_text(14, y + 9, text="odds —  boards not fully readable",
                          anchor="w", fill=DIM, font=F_SUB)
            return y + 26

        x = 14

        def seg(txt, fill, font=F_SUB):
            nonlocal x
            i = c.create_text(x, y + 9, text=txt, anchor="w", fill=fill, font=font)
            x = c.bbox(i)[2] + 5

        seg("ODDS", SOFT, F_TITLE)
        rrect(c, x, y + 2, x + 32, y + 16, 6, fill=PANEL_HI, outline=LINE)
        c.create_text(x + 16, y + 9, text="BETA", fill=AMBER, font=F_CHIP)
        x += 40
        seg(f"W {o['win'] * 100:.0f}%", GOOD, F_NAME)
        seg("/", DIM)
        seg(f"T {o['tie'] * 100:.0f}%", DIM, F_NAME)
        seg("/", DIM)
        seg(f"L {o['loss'] * 100:.0f}%", BAD, F_NAME)
        y += 22
        n = o.get("n")
        if n:
            c.create_text(14, y + 7, text=f"{n:,} simulated fights", anchor="w",
                          fill=DIM, font=F_CHIP)
            c.create_text(self.WIDTH - 14, y + 7, text="log-only sim", anchor="e",
                          fill=ACCENT, font=F_CHIP)
            y += 16
        return y + 8
