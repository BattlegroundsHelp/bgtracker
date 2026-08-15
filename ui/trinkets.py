"""TRINKETS window - the four trinkets on offer. Nothing else, ever.

Lifecycle:
  opens   on the trinket choose-one block, delivered when the SCREEN is back
          in the tavern (the block is written to the log DURING the fight that
          precedes it, which is why it used to appear a fight early)
  closes  when the screen enters combat, when a later tavern roll proves the
          dialog is gone, or on its timeout

Order comes from the choice block, never from the offer detector: trinkets are
staged in SETASIDE where all four log at zonePos=0, so the detector's order is
meaningless and would badge the wrong cards.

Two guards from the detector are worth restating, because they are why this
window fires twice a game instead of seven times: a genuine offer is always
exactly four options (the rest of SETASIDE is opponents' trinkets revealed as
you fight them), and only our own player's are kept.
"""

from __future__ import annotations

import bgtracker as bg

from .base import AMBER, DIM, F_SUB, F_TITLE, BaseWindow, offer_rows


class TrinketWindow(BaseWindow):
    KEY = "trinkets"
    TITLE = "PICK YOUR TRINKET"
    COLUMN = "left"
    DY = 492
    RESERVE = 272
    MAX_H = 272
    EVENTS = ("trinket", "picks_over", "tavern", "game")
    BADGE_KIND = "trinket"
    BADGE_PRIORITY = 30
    TIMEOUT_MS = 45_000

    def __init__(self, app):
        super().__init__(app)
        self.rows, self.tuned = [], False
        self.roll = -1

    def reset(self):
        self.rows, self.tuned, self.roll = [], False, -1
        self.hide()

    def on_event(self, name, payload):
        if name == "trinket":
            self.rows = payload.get("rows") or []
            self.tuned = payload.get("tuned", False)
            self.roll = payload.get("roll", -1)
            self.show()
            self.badges_show(self.rows, bg.MIN_SAMPLE)
        elif name == "picks_over":
            self.reset()
        elif name == "tavern":
            if self.is_open and payload.get("roll", 0) > self.roll:
                self.reset()
        elif name == "game":
            self.reset()

    def draw(self, c):
        y = self.header(c, f"{len(self.rows)} on offer" if self.rows else None)
        if not self.rows:
            return y + 24
        y = offer_rows(c, y, self.rows, self.WIDTH, self.app.art, bg.MIN_SAMPLE)
        if not any(r.get("avg") is not None for r in self.rows):
            c.create_text(14, y + 8, text="NO TRINKET STATS CONFIGURED", anchor="w",
                          fill=DIM, font=F_TITLE)
            c.create_text(14, y + 24, text="names only - see sources.json",
                          anchor="w", fill=DIM, font=F_SUB)
            y += 36
        return y + 8
