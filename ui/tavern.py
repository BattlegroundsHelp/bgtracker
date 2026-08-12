"""TAVERN window - what is in the shop right now, and nothing else.

Lifecycle (independent of every other window):
  opens/rebuilds  on a ``tavern`` event, which the reader emits only while the
                  SCREEN is in the recruit phase
  closes          on ``tavern_gone`` (the screen entered combat)

The reroll law: a refresh RE-USES the existing TB_BaconShop_DragBuy tokens, so
drag counts are zero on a reroll and nothing in the log ever says "this minion
entered the shop". The reader therefore samples the whole shop and pushes a
fresh ``tavern`` event whenever its contents change - a roll, a buy, a sell, a
tavern spell. This window simply rebuilds itself from that payload every
single time; it holds no memory of the previous shop.
"""

from __future__ import annotations

import bgtracker as bg

from .base import (ACCENT, AMBER, DIM, F_STARS, F_SUB, F_TITLE, SOFT,
                   STAR_COLOR, TEXT, BaseWindow)


class TavernWindow(BaseWindow):
    KEY = "tavern"
    TITLE = "TAVERN"
    COLUMN = "right"
    DY = 156
    RESERVE = 232
    MAX_H = 232
    EVENTS = ("tavern", "tavern_gone", "gold", "game")
    BADGE_KIND = "shop"
    BADGE_PRIORITY = 10

    def __init__(self, app):
        super().__init__(app)
        self.rows, self.slots = [], []
        self.gold = 0
        self.lean = None
        self.roll = 0

    def reset(self):
        self.rows, self.slots, self.gold, self.lean, self.roll = [], [], 0, None, 0
        self.hide()

    def on_event(self, name, payload):
        if name == "tavern":
            # EVERY roll rebuilds: rows are replaced wholesale, never merged.
            self.rows = payload.get("rows") or []
            self.slots = payload.get("slots") or self.rows
            self.lean = payload.get("lean")
            self.roll = payload.get("roll", self.roll + 1)
            self.show()
            self.badges_show(self.slots, bg.MIN_SAMPLE)
        elif name == "tavern_gone":
            self.rows, self.slots = [], []
            self.hide()
        elif name == "gold":
            self.gold = payload
            if self.is_open:
                self.redraw()
        elif name == "game":
            self.reset()

    def draw(self, c):
        right = f"+{self.gold}g next" if self.gold else None
        y = self.header(c, right, AMBER)
        if self.lean:
            c.create_text(14, y + 7, anchor="w", fill=ACCENT, font=F_SUB,
                          text=f"building {self.lean}"[:44])
            y += 18
        if not self.rows:
            c.create_text(14, y + 8, text="shop empty", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 24
        for r in self.rows:
            s = r.get("stars", 0)
            ic = self.app.art.icon(r.get("card"), 18)
            if ic is not None:
                c.create_image(22, y + 10, image=ic, anchor="w")
            c.create_text(44, y + 10, text="★" * s, anchor="w",
                          fill=STAR_COLOR.get(s, DIM), font=F_STARS)
            c.create_text(90, y + 10, text=r["name"][:16], anchor="w",
                          fill=TEXT if r.get("mine") else SOFT, font=F_SUB)
            if r.get("mine"):
                c.create_text(self.WIDTH - 14, y + 10, text="▶ yours", anchor="e",
                              fill=ACCENT, font=F_SUB)
            elif r.get("comp"):
                c.create_text(self.WIDTH - 14, y + 10, text=r["comp"][:14],
                              anchor="e", fill=DIM, font=F_SUB)
            elif r.get("tier"):
                c.create_text(self.WIDTH - 14, y + 10, text=f"T{r['tier']}",
                              anchor="e", fill=DIM, font=F_SUB)
            y += 22
        c.create_text(14, y + 8, text=f"roll {self.roll}", anchor="w",
                      fill=DIM, font=F_TITLE)
        return y + 22
