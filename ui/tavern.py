"""TAVERN window - what is in the shop right now, and nothing else.

Lifecycle (independent of every other window):
  opens/rebuilds  on a ``tavern`` event, which the reader emits only while the
                  SCREEN is in the recruit phase
  closes          on ``tavern_gone`` (the screen entered combat)

Each row's right-hand slot carries ONE tag, and which one it carries is a
ranking: "▶ yours" (this minion is already in the build you are on), then the
mechanical read from ui/synergy.py ("Beasts 4" - this card pays off a tribe
you are holding four of, which needs no stats source at all), then the comp
tag, then the tavern tier. Most specific wins, and only one is ever drawn:
the row is 22px and it stays 22px, because the window's band is 232px and the
layout law in ui/__init__.py is what keeps it off the comps window.

The stars carry a second signal, and it is the one this window must never
blur: a FILLED colour-graded ★ is measured (the buy-it-vs-skip-it differential
out of a real card table). A minion nothing has measured gets NO star: a
rating computed from the card alone was built and measured, and it ranks
bodies (Brann Bronzebeard came out one star, a vanilla 10/11 came out five),
because what makes a card good here lives in the board around it
and the board is not printed on the card. The minion browser, which has the
room, shows the two things the card CAN prove instead: how its body compares
with its own tier's average, and which comps are built around it.

The reroll law: a refresh RE-USES the existing TB_BaconShop_DragBuy tokens, so
drag counts are zero on a reroll and nothing in the log ever says "this minion
entered the shop". The reader therefore samples the whole shop and pushes a
fresh ``tavern`` event whenever its contents change - a roll, a buy, a sell, a
tavern spell. This window simply rebuilds itself from that payload every
single time; it holds no memory of the previous shop.
"""

from __future__ import annotations

import bgtracker as bg

from .base import (ACCENT, AMBER, DIM, F_STARS, F_SUB, F_TITLE, GOOD, SOFT,
                   STAR_COLOR, TEXT, BaseWindow, art_frame, plate,
                   shadow_text, tile_row)


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
            mine = bool(r.get("mine"))
            # The row is the game's own deck-list tile, the way HSReplay and
            # Firestone draw a minion in the match (founder's direction,
            # 2026-08-14). No tile on disk - art not fetched, a brand-new
            # card - and the old icon-and-text row draws instead.
            tiled = tile_row(c, 8, y - 1, self.WIDTH - 8, y + 20,
                             r.get("card"), best=mine,
                             tier=r.get("tier") or None)
            if not tiled:
                # A shop row is 22px and there are up to seven of them, so
                # this is the one window where a plate per row would be a
                # wall of edges. Only the minion already in the build you are
                # on gets one - it is the row the eye is looking for.
                if mine:
                    plate(c, 8, y - 1, self.WIDTH - 8, y + 20, 7, best=True)
                ic = self.app.art.icon(r.get("card"), 18)
                if ic is not None:
                    c.create_image(22, y + 10, image=ic, anchor="w")
                    art_frame(c, 21, y + 1, 41, y + 20, mine)
            # A star is a MEASUREMENT here or it is nothing. A row that
            # arrives flagged graded carries a number read off the card, and
            # that number ranks bodies rather than cards (see the note up top),
            # so it is not drawn at all rather than drawn in another colour.
            # The name column clears FIVE stars (F_STARS measures 55px for
            # five - the review caught the fifth star under the name).
            star_x, name_x = (32, 92) if tiled else (44, 104)
            if s and not r.get("graded"):
                c.create_text(star_x, y + 10, text="★" * s, anchor="w",
                              font=F_STARS, fill=STAR_COLOR.get(s, DIM))
            c.create_text(name_x, y + 10, text=r["name"][:16], anchor="w",
                          fill=TEXT if r.get("mine") else SOFT, font=F_SUB)
            # The right-hand label sits over the art half of the tile, so it
            # wears the same dark halo the badges use over card art.
            def right(text, fill):
                if tiled:
                    shadow_text(c, self.WIDTH - 14, y + 10, text, fill,
                                F_SUB, anchor="e")
                else:
                    c.create_text(self.WIDTH - 14, y + 10, text=text,
                                  anchor="e", fill=fill, font=F_SUB)
            if r.get("mine"):
                right("▶ yours", ACCENT)
            elif r.get("syn"):
                # The mechanical read, and it outranks the comp tag whenever it
                # is here at all: overlay.py only fills it when there is a real
                # count behind it ("Beasts 4"), which is a fact about THIS
                # board, where the comp tag is a fact about the archetype.
                right(r["syn"][:16], GOOD)
            elif r.get("comp"):
                right(r["comp"][:14], DIM)
            elif r.get("tier"):
                right(f"T{r['tier']}", DIM)
            y += 22
        c.create_text(14, y + 8, text=f"roll {self.roll}", anchor="w",
                      fill=DIM, font=F_SUB)
        return y + 22
