"""GOLD - the one number you look at every single turn, on its own.

Split out of the counters strip on founder feedback (2026-08-15): gold is
checked constantly and every other counter is checked occasionally, so it
gets the same treatment the standing buffs got - its own little window that
drags anywhere and remembers where it was put, instead of being the first
column of a strip you have to aim at.

It owns no parser. The numbers come from the counters window's CounterState,
the single source every counter surface shares, so this window and the strip
can never disagree. No counters window, no gold - it hides rather than
freezing on the last number it saw.

What it draws, and nothing else:
  * the gold you have left, big, over the gold this turn gives you
  * the coin pips: one per gold still spendable, so the count reads without
    being read, the way the game's own tray does
  * gold already banked for NEXT turn, only when the log has said so
"""

from __future__ import annotations

from .base import (AMBER, DIM, F_CHIP, F_HUGE, F_SUB, GOOD, SOFT, TEXT,
                   BaseWindow, advance)

PIP_R = 4                       # coin pip radius
PIP_GAP = 3


class GoldWindow(BaseWindow):
    KEY = "gold"
    TITLE = "GOLD"
    COLUMN = "float"            # movable, like the BUFFS pills
    DY = 720
    RESERVE = 58
    MAX_H = 58
    WIDTH = 132
    EVENTS = ("game",)

    def __init__(self, app):
        super().__init__(app)
        self._seen = -1

    def reset(self):
        # Same re-arm as the BUFFS window: a new game resets the state's
        # version to 0, and a stale _seen could equal it and swallow the
        # first update of the next game.
        self._seen = -1
        self.hide()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()

    def _counters_state(self):
        w = self.app.by_key.get("counters")
        return w.state if w is not None else None

    def tick(self, rect, game_front):
        s = self._counters_state()
        if s is None:
            # The counters window is switched off - it is this window's only
            # source, so hide rather than freeze (the same trap the BUFFS
            # window was caught in twice).
            self._seen = -1
            self.hide()
        elif s.version != self._seen:
            self._seen = s.version
            if s.known() and s.gold is not None:
                self.show()
            else:
                self.hide()
        super().tick(rect, game_front)

    def draw(self, c):
        s = self._counters_state()
        if s is None or s.gold is None:
            return 24
        y = self.header(c)
        gold, gmax = s.gold, s.gold_max

        # The number itself: spendable gold in the big face, the turn's
        # allowance beside it in the quiet one. Dim at zero - an empty purse
        # is information and should not shout like a full one.
        t = c.create_text(12, y, text=str(gold), anchor="nw",
                          fill=TEXT if gold else DIM, font=F_HUGE)
        if gmax:
            c.create_text(advance(c, t) + 3, y + 12, text=f"/{gmax}",
                          anchor="nw", fill=SOFT, font=F_SUB)

        # Banked gold, only when the log actually said so - this tag is
        # silent in current patches (see the counters window's tag notes).
        if s.extra_next:
            c.create_text(self.WIDTH - 12, y + 2, text=f"+{s.extra_next}g",
                          anchor="ne", fill=GOOD, font=F_SUB)
            c.create_text(self.WIDTH - 12, y + 14, text="next turn",
                          anchor="ne", fill=DIM, font=F_CHIP)

        # The pips: what is still spendable, capped so a big allowance cannot
        # push the row past the window's edge.
        py = y + 26
        step = PIP_R * 2 + PIP_GAP
        room = max(1, (self.WIDTH - 30) // step)
        for i in range(min(gold or 0, room)):
            px = 12 + i * step
            c.create_oval(px, py, px + PIP_R * 2, py + PIP_R * 2,
                          fill=AMBER, outline="")
        if (gold or 0) > room:
            c.create_text(self.WIDTH - 12, py + PIP_R, text=f"+{gold - room}",
                          anchor="e", fill=DIM, font=F_CHIP)
        return py + PIP_R * 2 + 6
