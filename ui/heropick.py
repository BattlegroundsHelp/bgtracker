"""HERO PICK window - the heroes on offer in the draft. Nothing else.

Lifecycle:
  opens   on the hero-draft burst (the four heroes dealt into your HAND)
  updates on a slot correction - the client shuffles the offered heroes into
          their final on-screen order AFTER the burst, sharing its timestamp,
          so the badges move to the right portraits instead of being wrong
  closes  on ``hero_over``, which the reader raises off the first PowerTaskList
          CARDRACE line: shop minions on screen means the hero is picked
  closes  on its timeout as a belt-and-braces backstop

It sits down the LEFT edge of the game window by default because the hero
portraits occupy the middle and the badge strip already writes each hero's
number above its own portrait.
"""

from __future__ import annotations

import bgtracker as bg

from .base import AMBER, DIM, F_SUB, F_TITLE, BaseWindow, offer_rows


class HeroPickWindow(BaseWindow):
    KEY = "heropick"
    TITLE = "PICK YOUR HERO"
    COLUMN = "left"
    DY = 70
    RESERVE = 256
    MAX_H = 256
    EVENTS = ("hero", "hero_slots", "hero_over", "game")
    BADGE_KIND = "hero"
    BADGE_PRIORITY = 40
    TIMEOUT_MS = 75_000        # hero select is at most ~60s

    def __init__(self, app):
        super().__init__(app)
        self.rows, self.tuned = [], False

    def reset(self):
        self.rows, self.tuned = [], False
        self.hide()

    def on_event(self, name, payload):
        if name == "hero":
            self.rows = payload.get("rows") or []
            self.tuned = payload.get("tuned", False)
            self.show()
            self.badges_show(self.rows, bg.MIN_SAMPLE)
        elif name == "hero_slots":
            # Same offer, corrected on-screen order: move the badges, do not
            # re-open the window (it may have been closed by the pick).
            self.rows = payload.get("rows") or self.rows
            if self.is_open:
                self.badges_show(self.rows, bg.MIN_SAMPLE)
                self.redraw()
        elif name in ("hero_over", "game"):
            self.reset()

    def draw(self, c):
        y = self.header(c, "tuned to this lobby" if self.tuned else None, AMBER)
        if not self.rows:
            c.create_text(14, y + 8, text="waiting for the draft", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 24
        y = offer_rows(c, y, self.rows, self.WIDTH, self.app.art, bg.MIN_SAMPLE)
        if not any(r.get("avg") is not None for r in self.rows):
            c.create_text(14, y + 8, text="NO HERO STATS CONFIGURED", anchor="w",
                          fill=DIM, font=F_TITLE)
            y += 20
        return y + 8
