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

Honesty: there is no hero-power stats feed. If a configured source happens to
carry a row for the power's cardId it is shown; otherwise every option shows a
dash. No number is ever borrowed from the hero that owns the power.
"""

from __future__ import annotations

from .base import DIM, F_NAME, F_SUB, SOFT, TEXT, BaseWindow, avg_color


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
        for r in self.rows:
            ic = (self.app.art.icon(r.get("card"), 24)
                  or self.app.art.icon_for_name(r["name"], 24))
            tx = 18
            if ic is not None:
                c.create_image(16, y + 13, image=ic, anchor="w")
                tx = 46
            c.create_text(tx, y + 13, text=r["name"][:24], anchor="w",
                          fill=TEXT, font=F_NAME)
            avg = r.get("avg")
            if avg is None:
                c.create_text(self.WIDTH - 16, y + 13, text="—", anchor="e",
                              fill=DIM, font=F_NAME)
            else:
                c.create_text(self.WIDTH - 16, y + 13, text=f"{avg:.2f}",
                              anchor="e", fill=avg_color(avg), font=F_NAME)
            y += 28
        if not any(r.get("avg") is not None for r in self.rows):
            c.create_text(14, y + 8, text="no hero-power stats - names only",
                          anchor="w", fill=SOFT, font=F_SUB)
            y += 20
        return y + 8
