"""DISCOVER window - minion discovers and Dark Gifts. Not trinkets, not
heroes, not hero powers: those have their own windows.

Lifecycle:
  opens   on a discover choose-one block, delivered when the SCREEN is back in
          the tavern - the block is written to the log during the fight that
          precedes it, so delivering it on sight put a pick panel over a fight
  closes  when the screen enters combat, when a later tavern roll proves the
          dialog is gone, or on its timeout

Scoring rule that has to stay: score every option we CAN and show the rest as
no-data. Requiring all options to be known dropped the whole panel whenever a
token or a brand-new card was among them - which is most Dark Gifts.
"""

from __future__ import annotations

from .base import (ACCENT, DIM, F_STARS, F_SUB, SOFT, STAR_COLOR, TEXT,
                   BaseWindow)


class DiscoverWindow(BaseWindow):
    KEY = "discover"
    TITLE = "PICK ONE"
    COLUMN = "left"
    DY = 772
    RESERVE = 300
    MAX_H = 300
    EVENTS = ("discover", "picks_over", "tavern", "game")
    BADGE_KIND = "choice"
    BADGE_PRIORITY = 30
    TIMEOUT_MS = 25_000

    def __init__(self, app):
        super().__init__(app)
        self.rows = []
        self.roll = -1

    def reset(self):
        self.rows, self.roll = [], -1
        self.hide()

    def on_event(self, name, payload):
        if name == "discover":
            self.rows = payload.get("rows") or []
            self.roll = payload.get("roll", -1)
            self.show()
            self.badges_show(self.rows)
        elif name == "picks_over":
            self.reset()
        elif name == "tavern":
            if self.is_open and payload.get("roll", 0) > self.roll:
                self.reset()
        elif name == "game":
            self.reset()

    def draw(self, c):
        y = self.header(c, f"{len(self.rows)} options" if self.rows else None)
        if not self.rows:
            c.create_text(14, y + 8, text="no discover open", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 24
        for r in self.rows:
            s = r.get("stars", 0)
            ic = (self.app.art.icon(r.get("card"), 22)
                  or self.app.art.icon_for_name(r["name"], 22))
            if ic is not None:
                c.create_image(20, y + 11, image=ic, anchor="w")
            c.create_text(46, y + 11, text="★" * s, anchor="w",
                          fill=STAR_COLOR.get(s, DIM), font=F_STARS)
            c.create_text(92, y + 11, text=r["name"][:16], anchor="w",
                          fill=TEXT if r.get("mine") else SOFT, font=F_SUB)
            if r.get("mine"):
                c.create_text(self.WIDTH - 14, y + 11, text="▶ yours", anchor="e",
                              fill=ACCENT, font=F_SUB)
            elif r.get("comp"):
                c.create_text(self.WIDTH - 14, y + 11, text=r["comp"][:14],
                              anchor="e", fill=DIM, font=F_SUB)
            elif r.get("tier"):
                c.create_text(self.WIDTH - 14, y + 11, text=f"T{r['tier']}",
                              anchor="e", fill=DIM, font=F_SUB)
            y += 26
        return y + 10
