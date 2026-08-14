"""BUFFS - the standing tavern effects as their own little window of pills.

Copied from the reference, not invented: HSReplay's overlay page shows each
counter as a separate floating pill - a circular crop of the source card's
art, then "+6 / +12" in plain bright text on a dark rounded pill - movable
on its own, away from every other widget. This window is that cluster: it
holds one pill per standing effect (the Waveling-class stamps under the name
the game shows, the tribe-wide shop buffs, Blood Gems), and being a normal
overlay window it drags anywhere and remembers where it was put, separately
from the counters strip.

It owns no parser: the numbers are read from the counters window's
CounterState (state.effects()), the single source both surfaces share, so
the pill and the strip can never disagree. No effects, no window - it hides
rather than showing an empty box.
"""

from __future__ import annotations

from .base import (AMBER, DIM, F_NAME, F_SUB, LINE, PANEL_HI, SOFT, TEXT,
                   TRIBE_COLOR, BaseWindow, rrect)
from . import skin

# The pill grid: sized for "+123/+456" beside a 20px icon, two per row -
# the same cluster shape the reference shows.
PILL_W, PILL_H, GAP = 118, 26, 6


def _colour(eff):
    if eff["kind"] == "gem":
        return TRIBE_COLOR["QUILBOAR"]
    if eff["kind"] in ("shopbuff", "legacy"):
        return TRIBE_COLOR.get(eff["label"], SOFT)
    return AMBER


class EffectsWindow(BaseWindow):
    KEY = "effects"
    TITLE = "BUFFS"
    COLUMN = "float"                # not part of either tiled column: it is
    DY = 792                        # the one window whose whole point is
    RESERVE = 64                    # being moved wherever the player wants
    MAX_H = 92
    WIDTH = 8 + 2 * PILL_W + GAP + 8
    EVENTS = ("game",)

    def __init__(self, app):
        super().__init__(app)
        self._seen = -1

    def reset(self):
        self.hide()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()

    def _counters_state(self):
        w = self.app.by_key.get("counters")
        return w.state if w is not None else None

    def tick(self, rect, game_front):
        s = self._counters_state()
        if s is not None and s.version != self._seen:
            self._seen = s.version
            if s.effects() and s.known():
                self.show()
            else:
                self.hide()
        super().tick(rect, game_front)

    def draw(self, c):
        s = self._counters_state()
        effects = s.effects() if s is not None else []
        if not effects:
            return 24
        x, y, col = 8, 6, 0
        for eff in effects[:6]:
            px1, py1 = x + col * (PILL_W + GAP), y
            rrect(c, px1, py1, px1 + PILL_W, py1 + PILL_H, PILL_H // 2,
                  fill=PANEL_HI, outline=LINE)
            cy = py1 + PILL_H // 2
            icon = skin.round_icon(c, eff["card"], 20) if eff["card"] else None
            if icon is None:
                # No card art for this source (a bookkeeping id, or the CDN
                # has none): the designed emblem for what the effect IS -
                # its tribe's, Blood Gems the quilboar one, a stamper the
                # buff arrow.
                name = {"gem": "tribe_quilboar",
                        "stamper": "tribe_buff"}.get(eff["kind"])
                if name is None:
                    name = "tribe_" + (eff["label"] or "buff").lower()
                icon = skin.ui_icon(c, name, 20)
            if icon is not None:
                c.create_image(px1 + 4, cy - 10, image=icon, anchor="nw")
            else:
                c.create_oval(px1 + 4, cy - 10, px1 + 24, cy + 10,
                              fill=_colour(eff), outline="")
            c.create_text(px1 + 30, cy, anchor="w", fill=TEXT, font=F_NAME,
                          text=f"+{eff['atk']} / +{eff['hp']}")
            col += 1
            if col == 2:
                col, y = 0, y + PILL_H + GAP
        if col:
            y += PILL_H + GAP
        # One tiny line naming the sources, in draw order - the pills only
        # carry numbers, and two nameless pills of the same colour would be
        # a guessing game.
        names = " · ".join((e["label"] or "?").title()[:14] for e in effects[:6])
        c.create_text(10, y + 2, anchor="nw", fill=DIM, font=F_SUB,
                      text=names[:52])
        return y + 16
