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

Each option also carries the MECHANICAL read (ui/synergy.py) on its own line:
what the card's own text says it pays off, against what your board is made of.
That line comes out of the card database alone, so it is the one rating in
this panel that is there with no stats source configured at all.
"""

from __future__ import annotations

from .base import (ACCENT, DIM, F_STARS, F_SUB, GOOD, SOFT, STAR_COLOR, TEXT,
                   BaseWindow, art_frame, fit_text, plate, shadow_text,
                   tile_row)


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
        # The mechanical read gets its own line here, where the tavern row only
        # has room for the short form. A discover is at most four options and
        # this window's band is 300px, so 40px rows still fit with room over
        # (28 + 4x40 + 10 = 198). The rows only grow when a line actually
        # exists, so a dialog with nothing to say stays exactly as compact as
        # it always was.
        step = 40 if any(r.get("syn_full") for r in self.rows) else 26
        for r in self.rows:
            s = r.get("stars", 0)
            mine = bool(r.get("mine"))
            # At most four options, so every one of them can be a plate here
            # (unlike the seven-row tavern) - and the one already in your
            # build is the only one wearing the gold edge.
            # The deck-list tile first (the rows-are-tiles rule); the plate
            # and icon row stay for options with no tile - Dark Gifts and
            # spells often have none.
            tiled = tile_row(c, 8, y, self.WIDTH - 8, y + step - 4,
                             r.get("card"), best=mine, tier=r.get("tier"))
            if not tiled:
                plate(c, 8, y, self.WIDTH - 8, y + step - 4, 8, best=mine)
                ic = (self.app.art.icon(r.get("card"), 22)
                      or self.app.art.icon_for_name(r["name"], 22))
                if ic is not None:
                    c.create_image(20, y + 11, image=ic, anchor="w")
                    art_frame(c, 19, y, 43, y + 22, mine)
            star_x, name_x = (32, 92) if tiled else (46, 92)
            c.create_text(star_x, y + 11, text="★" * s, anchor="w",
                          fill=STAR_COLOR.get(s, DIM), font=F_STARS)
            right_w = 74
            c.create_text(name_x, y + 11, anchor="w",
                          text=fit_text(r["name"],
                                        self.WIDTH - 14 - right_w - name_x),
                          fill=TEXT if r.get("mine") else SOFT, font=F_SUB)

            def right(text, fill):
                if tiled:
                    shadow_text(c, self.WIDTH - 14, y + 11, text, fill,
                                F_SUB, anchor="e")
                else:
                    c.create_text(self.WIDTH - 14, y + 11, text=text,
                                  anchor="e", fill=fill, font=F_SUB)
            if r.get("mine"):
                right("▶ yours", ACCENT)
            elif r.get("comp"):
                right(r["comp"][:14], DIM)
            elif r.get("tier") and not tiled:
                right(f"T{r['tier']}", DIM)
            if step > 26 and r.get("syn_full"):
                c.create_text(46, y + 28, anchor="w", fill=GOOD, font=F_SUB,
                              text=fit_text(r["syn_full"], self.WIDTH - 60))
            y += step
        return y + 10
