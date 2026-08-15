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
                   GOOD, LINE, PANEL_HI, SOFT, BaseWindow, advance, rrect)


class CombatWindow(BaseWindow):
    KEY = "combat"
    TITLE = "COMBAT"
    COLUMN = "right"
    DY = 70
    # 78 is load-bearing: the tavern window's band starts at 156 and 70+86
    # would overlap it (layout_check catches exactly that). The damage/lethal
    # row fits because it REPLACES the rollout-count row rather than stacking
    # under it - see draw().
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
            # advance(), not bbox()[2]: the line is laid out in base pixels
            # but painted in scaled ones, so the raw bbox would space the
            # W / T / L segments as if the panel were still 316px wide.
            nonlocal x
            i = c.create_text(x, y + 9, text=txt, anchor="w", fill=fill, font=font)
            x = advance(c, i) + 5

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

        # Damage and lethal ride the same rollouts. Every field arrives None
        # whenever the log did not state a fact it needs (hero tier or life
        # unknown, ghost opponent) - a None field is simply not drawn, so this
        # row never shows a guess. dmg means are conditional: "hit ~7" reads
        # "when this fight is won, about 7 lands on their hero". The row
        # REPLACES the rollout-count line rather than stacking under it: the
        # window's 78px band is load-bearing (see MAX_H), and between "how
        # hard does this hit" and "how many dice were rolled" the first one
        # is the line a player acts on.
        dd, dt = o.get("dmg_dealt"), o.get("dmg_taken")
        kill, lethal = o.get("kill"), o.get("lethal")
        n = o.get("n")
        if dd or dt or kill is not None or lethal is not None:
            x = 14
            if dd:
                seg(f"hit ~{dd['mean']:.0f}", GOOD, F_CHIP)
            if dt:
                seg(f"take ~{dt['mean']:.0f}", BAD, F_CHIP)
            if kill is not None:
                seg(f"they die {kill * 100:.0f}%", GOOD, F_CHIP)
            if lethal is not None:
                seg(f"we die {lethal * 100:.0f}%", BAD, F_CHIP)
            if n:
                c.create_text(self.WIDTH - 14, y + 7, text=f"{n // 1000}k sims",
                              anchor="e", fill=DIM, font=F_CHIP)
            y += 16
        elif n:
            c.create_text(14, y + 7, text=f"{n:,} simulated fights", anchor="w",
                          fill=DIM, font=F_CHIP)
            c.create_text(self.WIDTH - 14, y + 7, text="log-only sim", anchor="e",
                          fill=DIM, font=F_CHIP)
            y += 16
        return y + 8
