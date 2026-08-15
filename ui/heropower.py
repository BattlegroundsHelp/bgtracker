"""HERO POWER window - the hero-power choose-one, on its own.

A hero power pick is its own dialog with its own options (three, typically),
and it is NOT a minion discover: the options are cards like
``TB_BaconShop_HP_054`` or ``BG36_HERO_105p``. It used to share a panel with
minion discovers and Dark Gifts, which is why picking a power looked like
picking a minion.

Lifecycle:
  opens   on its own choose-one block, delivered when the SCREEN is in the
          tavern (the block is written to the log during the fight before it)
  closes  when the screen enters combat, when a later tavern roll proves the
          dialog is gone, or on its timeout

Honesty: the numbers come from the hero-power feed and from nowhere else
(bgtracker.hero_power_table, built from the games players shared - no stats
site publishes these at any price). An option that feed does not carry, or
carries on too few games to stand behind, shows a dash. No number is ever
borrowed from the hero that owns the power, and none from the minion table -
a hero power is not a minion, which is why that lookup used to find nothing.
"""

from __future__ import annotations

from .base import (DIM, F_NAME, F_SUB, SOFT, TEXT, BaseWindow, art_frame,
                   avg_color, plate)


class HeroPowerWindow(BaseWindow):
    KEY = "heropower"
    TITLE = "PICK YOUR HERO POWER"
    COLUMN = "left"
    DY = 334
    RESERVE = 150
    MAX_H = 150
    EVENTS = ("heropower", "picks_over", "tavern", "game")
    BADGE_KIND = "choice"
    BADGE_PRIORITY = 35
    TIMEOUT_MS = 45_000

    def __init__(self, app):
        super().__init__(app)
        self.rows = []
        self.roll = -1          # tavern roll counter when this offer opened

    def reset(self):
        self.rows, self.roll = [], -1
        self.hide()

    def on_event(self, name, payload):
        if name == "heropower":
            self.rows = payload.get("rows") or []
            self.roll = payload.get("roll", -1)
            self.show()
            self.badges_show(self.rows)
        elif name == "picks_over":
            self.reset()
        elif name == "tavern":
            # A roll AFTER this offer opened means the modal is gone and the
            # player is shopping again.
            if self.is_open and payload.get("roll", 0) > self.roll:
                self.reset()
        elif name == "game":
            self.reset()

    def draw(self, c):
        y = self.header(c, f"{len(self.rows)} options" if self.rows else None)
        if not self.rows:
            c.create_text(14, y + 8, text="no hero-power pick open", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 24
        # Rows arrive best first (overlay.py sorts them), but no row wears the
        # gold "standout" edge the hero and trinket panels use: this window
        # draws no sample size beside its numbers, so it has nowhere to say
        # how thin the winner is, and crowning one on that would be a claim it
        # cannot back. Every option gets the same plate.
        for r in self.rows:
            plate(c, 8, y + 1, self.WIDTH - 8, y + 25, 8)
            ic = (self.app.art.icon(r.get("card"), 24)
                  or self.app.art.icon_for_name(r["name"], 24))
            tx = 18
            if ic is not None:
                c.create_image(16, y + 13, image=ic, anchor="w")
                art_frame(c, 15, y + 1, 41, y + 25)
                tx = 46
            c.create_text(tx, y + 13, text=r["name"][:24], anchor="w",
                          fill=TEXT, font=F_NAME)
            avg = r.get("avg")
            if avg is None:
                c.create_text(self.WIDTH - 14, y + 13, text="—", anchor="e",
                              fill=DIM, font=F_NAME)
            else:
                c.create_text(self.WIDTH - 14, y + 13, text=f"{avg:.2f}",
                              anchor="e", fill=avg_color(avg), font=F_NAME)
            y += 28
        if (not any(r.get("avg") is not None for r in self.rows)
                and y + 26 <= self.MAX_H):
            # Only when it FITS: four no-stat rows plus this line overran the
            # 150px band by 5px (review find, surfaced by the stats feed
            # 404ing) - and the dashes on every row already say "no numbers".
            c.create_text(14, y + 8, text="no hero-power stats - names only",
                          anchor="w", fill=SOFT, font=F_SUB)
            y += 20
        return y + 8
