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
                   TRIBE_COLOR, BaseWindow, fit_text, get_scale, rrect)
from . import skin

# The pill grid: sized for "+123/+456" beside a 16px icon, two per row -
# the same cluster shape the reference shows. Tightened 2026-08-15 on founder
# feedback that the window sat too heavy over the board: the pill is measured
# to the widest real string and nothing more.
PILL_W, PILL_H, GAP = 96, 21, 4
ICON_PX = 16


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
    MAX_H = 122                     # header + three pill rows + the names
                                    # line, at the tightened pill size; two
                                    # reviews taught the shape of this number
                                    # (a short one clips the third row, and
                                    # the header needs its own band)
    WIDTH = 8 + 2 * PILL_W + GAP + 8
    EVENTS = ("game",)

    def __init__(self, app):
        super().__init__(app)
        self._seen = -1

    def reset(self):
        # Re-arm the version watch too: new_game() resets the counter
        # state's version to 0, and a _seen left at an old value could
        # EQUAL a fresh version and swallow the first update of the next
        # game (review find, 2026-08-14).
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
            # The counters window is switched OFF (it is this window's only
            # data source) - hide rather than freeze on the last paint. The
            # review caught both halves: never-shows when counters starts
            # disabled, AND stale pills when it is disabled mid-game.
            self._seen = -1
            self.hide()
        elif s.version != self._seen:
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
        # The header names the window (the review found this was the one
        # surface with no title - unidentifiable when dragging it).
        y = self.header(c)
        x, col = 8, 0
        y += 4
        for eff in effects[:6]:
            px1, py1 = x + col * (PILL_W + GAP), y
            rrect(c, px1, py1, px1 + PILL_W, py1 + PILL_H, PILL_H // 2,
                  fill=PANEL_HI, outline=LINE)
            cy = py1 + PILL_H // 2
            # Icons bake at FINAL pixels (base 20 x the UI scale): the canvas
            # transform moves an image's anchor and never resizes the bitmap.
            ipx = max(10, round(ICON_PX * get_scale()))
            icon = (skin.round_icon(c, eff["card"], ipx)
                    if eff["card"] else None)
            if icon is None:
                # No card art for this source (a bookkeeping id, or the CDN
                # has none): the designed emblem for what the effect IS -
                # its tribe's, Blood Gems the quilboar one, a stamper the
                # buff arrow.
                name = {"gem": "tribe_quilboar",
                        "stamper": "tribe_buff"}.get(eff["kind"])
                if name is None:
                    name = "tribe_" + (eff["label"] or "buff").lower()
                icon = skin.ui_icon(c, name, ipx)
            half = ICON_PX // 2
            if icon is not None:
                c.create_image(px1 + 3, cy - half, image=icon, anchor="nw")
            else:
                c.create_oval(px1 + 3, cy - half, px1 + 3 + ICON_PX, cy + half,
                              fill=_colour(eff), outline="")
            c.create_text(px1 + ICON_PX + 8, cy, anchor="w", fill=TEXT,
                          font=F_SUB, text=f"+{eff['atk']}/+{eff['hp']}")
            col += 1
            if col == 2:
                col, y = 0, y + PILL_H + GAP
        if col:
            y += PILL_H + GAP
        # One tiny line naming the sources, in draw order - the pills only
        # carry numbers, and two nameless pills of the same colour would be
        # a guessing game.
        names = " · ".join((e["label"] or "?").title()[:14] for e in effects[:6])
        c.create_text(8, y + 2, anchor="nw", fill=DIM, font=F_SUB,
                      text=fit_text(names, self.WIDTH - 16))
        return y + 16
