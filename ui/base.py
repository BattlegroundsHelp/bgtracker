"""Shared window machinery: one frameless Tk window per concern.

Everything a window needs that is NOT about its own subject lives here - the
palette, the fonts, the rounded-canvas drawing, the anchoring to the
Hearthstone window, the per-window remembered position, the click-through
badge strips that put ratings ON the cards, and the manager that ticks them
all.

Three rules this module exists to enforce:

1. **One window, one concern, one lifecycle.** A window opens on its own
   trigger and closes on its own trigger. There is no shared "mode": nothing
   here can hide or morph another window's content, so a bug in one surface
   cannot make another surface lie.
2. **The screen is the truth.** Positioning and visibility follow the real
   Hearthstone window rect and the real foreground window, re-checked every
   tick and self-healed - never a flag that we hope still matches reality.
3. **A drawing error is contained.** ``handle()`` catches whatever a window
   throws so one bad payload cannot kill the Tk callback chain (that failure
   mode once left the overlay "visible" per heartbeat while it silently
   stopped repainting).

SCALING - the whole public surface (for whoever owns the settings window)
------------------------------------------------------------------------
The overlay was drawn against a 1920x1080 game window. On a 4K screen every
panel is half the size it should be, which is unreadable. Four names fix that,
and they are the only ones anything outside this package needs:

    ui.base.set_scale(1.75)   -> 1.75   apply a scale NOW, live. Every font,
                                        every panel, every badge follows, and
                                        open windows repaint. Returns the value
                                        actually used (clamped to
                                        SCALE_MIN..SCALE_MAX).
    ui.base.get_scale()       -> 1.75   what is in force
    ui.base.auto_scale()      -> 2.0    a suggestion read off the display: the
                                        Hearthstone window's height against the
                                        1080 the overlay was drawn for, in
                                        quarter steps. 1.0 if anything fails.
    ui.base.SCALE_MIN, SCALE_MAX        0.75 and 3.0
    ui.base.set_badge_scale(1.2) -> 1.2 nudge the badges ONLY, live. They are
                                        sized by the game window (badge_scale
                                        below), so this is a multiplier on top
                                        of that, not a size.
    ui.base.get_badge_scale() -> 1.2    what is in force
    ui.base.BADGE_USER_MIN, BADGE_USER_MAX   0.5 and 2.0

MOVING the badges is a mode rather than a slider, because a click-through
window cannot be dragged - see the block above BadgeStrip:

    ui.base.set_badge_edit(True)  -> True  drop click-through on every strip,
                                           show a numberless pattern, let the
                                           player drag each band onto its cards
    ui.base.set_badge_edit(False) -> False put click-through back and restore
                                           whatever was really on screen
    ui.base.badge_edit()          -> bool  is it on

The offsets are saved per badge KIND in .overlay.json under "badge", as
fractions of the game window, and applied on top of the measured SLOT_X /
BAND_Y.

Nothing here is persisted and no config file is read: storing the chosen value
and calling ``set_scale`` at startup belongs to the settings window, not to the
drawing code. A one-line wiring is the whole integration::

    ui.base.set_scale(saved_scale or ui.base.auto_scale())

THE ONE RULE A WINDOW MUST FOLLOW
---------------------------------
``draw()`` works in BASE pixels - the same numbers as before any of this
existed - and the canvas is scaled once, afterwards, in ``redraw()``. So a
window never multiplies anything by the scale, and its hard-coded
``create_text(14, y + 8, ...)`` coordinates keep meaning what they always
meant. Two consequences:

  * measure text with ``F_SUB.measure(text)`` or ``fit_text(...)``, which
    answer in base pixels. ``canvas.bbox()`` answers in the pixels actually
    painted, which are scaled - use ``advance(c, item)`` when you need the
    right-hand edge of something just drawn (it is exactly ``bbox()[2]`` at
    scale 1.0).
  * card art is the one thing ``Canvas.scale`` cannot resize for us, so
    ``ArtCache`` sizes it up itself: ask for the base px you always asked for.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
import tkinter as tk
import traceback
import weakref
from ctypes import wintypes
from pathlib import Path
from tkinter import font as tkfont

from paths import APP_DIR

from . import skin

# DPI awareness, and it has to be PER MONITOR rather than merely "aware".
#
# With the old system-DPI level, Windows lies to a process about any monitor
# whose scaling differs from the primary one: it hands back VIRTUALIZED
# coordinates, so GetWindowRect for a game on the second screen comes back in
# the wrong units. An overlay that positions itself from that rectangle lands
# offset, or the wrong size, on exactly the setup people run - a scaled 4K
# panel next to an unscaled 1080p one. Per-monitor v2 asks for the truth on
# every monitor instead, which is what the window-following code needs.
#
# Three levels, newest first, because the newest is Windows 10 1703 and up:
# an executable whose manifest already declares awareness makes all three fail
# harmlessly, which is why nothing here treats failure as an error.
for _dpi in (
    lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(-4),  # per-mon v2
    lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),          # per-monitor
    lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),          # system
):
    try:
        if _dpi():
            break
    except Exception:
        continue

# The folder the overlay owns: the repo when run from source, the folder
# holding the exe in a frozen build. Never __file__ - frozen, that resolves
# inside PyInstaller's private bundle, so saved window positions would be
# written where the user cannot find them and thrown away by the next update.
ROOT_DIR = APP_DIR
ASSETS = ROOT_DIR / "assets"
POS_FILE = ROOT_DIR / ".overlay.json"

try:
    from PIL import Image, ImageTk
    _PIL = True
except Exception:
    _PIL = False

# ------------------------------------------------------------------ palette

TRANS = "#000001"             # transparent-color key: this exact color is a hole
#
# THE COLOUR KEY IS LOAD-BEARING. Every window is built on a canvas whose
# background is TRANS and whose whole visible body is one filled shape on top
# of it, and the strips are nothing BUT that background - which is what makes
# them click-through holes. So TRANS never changes and nothing else in this
# table may drift onto #000001: a panel colour that collided with the key
# would punch the panel out of the screen, and a badge that painted the key
# would eat the click it is sitting on.
#
# The rest of the table moved 2026-08-12, from flat cool charcoal to the warm
# dark the game itself is lit in. Battlegrounds is stained wood, stone, aged
# parchment and lamplight, so a blue-grey slab beside it always read as a
# different program's window sitting on top of the game. Nothing here changes
# what a colour MEANS: the data colours (GOOD / AMBER / BAD, avg_color,
# STAR_COLOR, TRIBE_COLOR) are untouched, because their hue is the number.
PANEL = "#191410"             # stained wood, the panel face
PANEL_HI = "#241d15"          # a raised plate on that face
LINE = "#3b3126"              # a rule, warm rather than blue-grey
TEXT = "#f2ece0"              # parchment
SOFT = "#c6b89f"              # aged parchment
DIM = "#93876f"               # the quiet line. Measured against the new face
                              # it keeps the contrast the old #7c818c had on
                              # the old one (4.6:1), so nothing got harder to
                              # read in exchange for the warmth.
ACCENT = "#5fb2dc"            # "yours", links, anything clickable. Deliberately
                              # still cool: it is the one thing on a gold-and-
                              # wood panel that has to be found instantly, and
                              # a second gold would hide in the first.
AMBER = "#e0b45c"
GOOD = "#6fd693"
BAD = "#e07a5f"

# The metal. A rim that reads as a rim is three tones deep - a dark outline to
# sit in, a lit top and a shaded bottom - and that is drawn with concentric
# filled shapes rather than a gradient, because these panels repaint on every
# shop roll and a gradient on a Tk canvas is hundreds of line items per frame.
EDGE = "#0b0906"              # the dark the rim is set into
GOLD = "#a8854a"              # the rim body. Darker than the gold the game
                              # uses on its own frames on purpose: this sits
                              # OVER the board, and a bright ring around
                              # eleven panels was the loudest thing on the
                              # screen when it was tried at #c9a45c.
GOLD_HI = "#d8bd82"           # its lit top edge - one line, not a ring
GOLD_LO = "#5f4722"           # its shaded underside
GOLD_TEXT = "#d9bd80"         # window titles, struck in the same metal
                              # (not TITLE: every window class already owns a
                              # TITLE, and that one is words)
HEADER_BG = "#241c13"         # the header slab
BEVEL = "#3f3325"             # the highlight along a bevelled edge
SHADE = "#120e09"             # the shadow under one
ROW = "#1e1811"               # a card plate on the panel face
HALO = "#0b0805"              # the dark a badge is outlined in, over card art

# Chips - the little filled pills (tribes, the placement badge, the toggles).
# A lit chip's label sits IN the light, so it is near-black rather than the
# panel colour; warm, because the old #101116 read blue beside gold.
ON_CHIP = "#140f08"           # label on a lit chip
OFF_CHIP = "#8a7f6c"          # label on an unlit one
OFF_TRIBE = "#5a5045"         # ... and on a tribe that has not been seen

TRIBE_COLOR = {
    "BEAST": "#57a05e", "DEMON": "#a05ec2", "DRAGON": "#d1793e",
    "ELEMENTAL": "#4fb3c9", "MECHANICAL": "#8a94a8", "MURLOC": "#58b8a2",
    "NAGA": "#5f7fd9", "PIRATE": "#c2564f", "QUILBOAR": "#b08d4e",
    "UNDEAD": "#7a6fae",
}
TRIBE_TAG = {"BEAST": "BST", "DEMON": "DMN", "DRAGON": "DRG", "ELEMENTAL": "ELM",
             "MECHANICAL": "MEC", "MURLOC": "MUR", "NAGA": "NAG", "PIRATE": "PIR",
             "QUILBOAR": "QIL", "UNDEAD": "UND"}

# ------------------------------------------------------------------- scaling
#
# 1080 is the reference height everything below is measured against, and that
# is not a guess: the left column's default bands tile from y+8 to exactly
# y+1072 (discover, DY 772 + MAX_H 300), i.e. 1080 minus the 8px bottom
# margin, and tests/test_windows.py asserts that tiling against a 1920x1080
# rect. Every hard-coded pixel in this package - panel widths, band heights,
# font points, the badge strip's 40px band - was drawn to that one ruler.
REF_H = 1080
SCALE_MIN, SCALE_MAX = 0.75, 3.0
# The badge nudge is deliberately a narrow range and a MULTIPLIER, not a size:
# a badge that stops covering the card it belongs to is worse than one that is
# slightly small, and the honest size is the one badge_scale() computes from
# the game window. This is for the player who wants the number a little bolder
# over their own card art, and 0.5..2.0 is as far as that can go before the
# badge stops sitting on its card.
BADGE_USER_MIN, BADGE_USER_MAX = 0.5, 2.0

_scale = 1.0
_badge_user = 1.0


def _clamp(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return 1.0
    return max(SCALE_MIN, min(SCALE_MAX, s))


class ScaledFont:
    """One font, shared BY REFERENCE with every ``create_text`` in the package.

    The whole scaling feature hangs off this class being an OBJECT rather than
    the ``("Segoe UI", 8)`` tuple it replaces. Eleven window modules do
    ``from .base import F_SUB`` at import time, so rebinding a module-level
    name here could never reach them - they captured the old value. Handing
    them a mutable object instead means one ``configure`` restyles all eleven,
    including text already sitting on a canvas (measured: an item drawn at
    size 9 is 73px wide, 158px after its font is configured to 18, and 73
    again when it is put back).

    A tkinter Font cannot exist before there is a Tk root and this module is
    imported long before one, so the real font is built on first use, and
    rebuilt if the root is replaced - the window test builds and destroys a
    manager per log, and a Font outliving its interpreter raises on the next
    measure.

    ``measure()`` deliberately answers in BASE pixels, from a second font that
    is never rescaled: ``draw()`` lays out in base pixels and the canvas is
    scaled afterwards, so a layout that measured in painted pixels would cut
    its own text short at any scale above 1.
    """

    __slots__ = ("family", "base", "weight", "_font", "_measure", "_root", "_own")

    def __init__(self, family, size, weight="normal"):
        self.family, self.base, self.weight = family, size, weight
        self._font = self._measure = None
        self._root = None
        self._own = None       # set by _rescale_to: follow something other
                               # than the panel scale (badges follow the game)

    @property
    def ratio(self):
        return _scale if self._own is None else self._own

    @property
    def size(self):
        """The point size actually painted at the current scale."""
        return max(1, int(round(self.base * self.ratio)))

    def _resolve(self):
        root = tk._default_root
        if root is None:
            return None
        if self._font is None or self._root is not root:
            try:
                self._font = tkfont.Font(root=root, family=self.family,
                                         size=self.size, weight=self.weight)
                self._measure = tkfont.Font(root=root, family=self.family,
                                            size=self.base, weight=self.weight)
                self._root = root
            except Exception:
                self._font = self._measure = self._root = None
        return self._font

    def _rescale(self):
        f = self._resolve()
        if f is not None:
            try:
                f.configure(size=self.size)
            except Exception:
                self._font = self._measure = self._root = None

    def _rescale_to(self, s):
        """Follow ``s`` instead of the panel scale (the badge fonts do this:
        they are sized by the game window, which the panels are not)."""
        if self._own != s:
            self._own = s
            self._rescale()

    def measure(self, text):
        """Width of ``text`` in BASE pixels (the space ``draw()`` reasons in)."""
        self._resolve()
        if self._measure is not None:
            try:
                return self._measure.measure(text)
            except Exception:
                self._font = self._measure = self._root = None
        # No usable Tk: an average glyph width beats letting a redraw die.
        return int(len(text) * self.base * 0.62)

    def __str__(self):
        """Tk asks for this: a Font's own name, or a plain font spec when
        there is no interpreter to have registered one."""
        f = self._resolve()
        if f is not None:
            return str(f)
        spec = f"{{{self.family}}} {self.size}"
        return spec if self.weight == "normal" else f"{spec} {self.weight}"

    def __repr__(self):
        return f"ScaledFont({self.family!r}, {self.base}, x{_scale:g})"


F_BRAND = ScaledFont("Segoe UI Semibold", 9)
F_STATUS = ScaledFont("Segoe UI", 8)
F_TITLE = ScaledFont("Segoe UI Semibold", 9)
F_NAME = ScaledFont("Segoe UI Semibold", 10)
F_BIG = ScaledFont("Segoe UI Semibold", 14)
F_HUGE = ScaledFont("Segoe UI Semibold", 17)
F_DELTA = ScaledFont("Segoe UI Semibold", 8)
F_SUB = ScaledFont("Segoe UI", 8)
F_CHIP = ScaledFont("Segoe UI Semibold", 7)
F_STARS = ScaledFont("Segoe UI", 8)          # the ★ row inside a panel

# Badges live over the game's own cards, so they are sized by the GAME window
# and not by the panel preference - see badge_scale(). They get their own font
# objects for that reason: sharing the panel ones would resize every badge the
# moment somebody scaled the panels.
F_BADGE_BIG = ScaledFont("Segoe UI Semibold", 14)
F_BADGE_NAME = ScaledFont("Segoe UI Semibold", 10)
F_BADGE_CHIP = ScaledFont("Segoe UI Semibold", 7)
F_BADGE_STARS = ScaledFont("Segoe UI", 11)

_PANEL_FONTS = (F_BRAND, F_STATUS, F_TITLE, F_NAME, F_BIG, F_HUGE, F_DELTA,
                F_SUB, F_CHIP, F_STARS)
_BADGE_FONTS = (F_BADGE_BIG, F_BADGE_NAME, F_BADGE_CHIP, F_BADGE_STARS)

# Every live window, so set_scale can repaint them. Weak, because the window
# test destroys a manager and builds another in the same process.
_LIVE: "weakref.WeakSet" = weakref.WeakSet()


def get_scale():
    """The panel scale in force. 1.0 is the size the overlay was drawn at."""
    return _scale


def set_scale(s):
    """Apply a UI scale live. Returns the value actually used.

    Order matters: fonts first (they are shared objects, so this alone
    restyles text already on every canvas), then each window repaints, which
    is what re-runs the canvas transform and re-anchors the panel. Badge
    strips redraw from the rows they are already holding.
    """
    global _scale
    s = _clamp(s)
    if s == _scale:
        return _scale
    _scale = s
    for f in _PANEL_FONTS:
        f._rescale()
    for w in list(_LIVE):
        try:
            w._rescaled()
        except Exception:
            traceback.print_exc()
    return _scale


def repaint_all():
    """Repaint every live window from its current state.

    What the skin toggle needs: exactly what a scale change does, minus the
    scale - the next draw asks the skin again and gets the other answer.
    """
    for w in list(_LIVE):
        try:
            w._rescaled()
        except Exception:
            traceback.print_exc()


def badge_scale(game_h):
    """How big a badge should be over a game window ``game_h`` pixels tall.

    A badge is pinned to a real card on the real screen, so the thing that
    decides its size is the game window, not how big the player likes their
    side panels: a 2160px-tall game needs roughly twice the badge a 1080px one
    does whatever the panel setting says. The panel preference still rides on
    top, so someone who wants everything bigger gets bigger badges too, and so
    does the badge nudge from the settings panel (1.0 by default, i.e. absent).
    """
    try:
        if game_h and game_h > 0:
            return max(SCALE_MIN,
                       min(SCALE_MAX, (game_h / REF_H) * _scale * _badge_user))
    except Exception:
        pass
    return max(SCALE_MIN, min(SCALE_MAX, _scale * _badge_user))


def get_badge_scale():
    """The badge nudge in force. 1.0 means "exactly what the game window says"."""
    return _badge_user


def set_badge_scale(s):
    """Apply the badge nudge live. Returns the value actually used.

    A strip only sizes itself inside ``show()``, so a visible strip is re-shown
    from the rows it is already holding - the same call ``reposition`` makes
    when the game window moves. A strip that is not up needs nothing: it reads
    the value the next time it draws.
    """
    global _badge_user
    try:
        s = float(s)
    except (TypeError, ValueError):
        return _badge_user
    s = max(BADGE_USER_MIN, min(BADGE_USER_MAX, s))
    if s == _badge_user:
        return _badge_user
    _badge_user = s
    rect = hs_rect()
    for strip in list(_STRIPS):
        if strip.visible and strip.rows:
            try:
                strip.show(strip.rows, rect or strip.rect)
            except Exception:
                traceback.print_exc()
    return _badge_user


def auto_scale():
    """A scale suggested by the display: 1.0 at 1080p, 2.0 at 2160p.

    The Hearthstone window's own height is the honest input - it is what the
    overlay actually sits on - and the primary screen is the fallback for when
    the game is not running (the settings window opens from the menu as often
    as from a game). Quarter steps, because 1.33 and 1.25 look the same and
    the round number is the one a player can reason about.

    Never raises: a machine where the Win32 call fails gets 1.0, which is
    exactly today's overlay.
    """
    try:
        h = None
        r = hs_rect()
        if r is not None:
            h = r.bottom - r.top
        if not h:
            h = ctypes.windll.user32.GetSystemMetrics(1)     # SM_CYSCREEN
        if not h or h <= 0:
            return 1.0
        return _clamp(round(h / REF_H * 4) / 4)
    except Exception:
        return 1.0


STAR_COLOR = {5: GOOD, 4: GOOD, 3: "#b9d16f", 2: AMBER, 1: BAD, 0: DIM}

RADIUS = 14
MARGIN_X = 18                 # gap between a column and the game window edge
HEADER_H = 24

# Where the offered cards sit inside the Hearthstone window, as fractions of
# its size - this is what lets a badge land under the right character. Both
# rows measured off live screenshots (2026-08-10). Hero badges sit ABOVE the
# portraits (clear of reroll buttons); trinket badges sit below the cards. The
# trinket dialog is offset right of centre - that asymmetry is real.
SLOT_X = {
    "hero": {
        2: [0.422, 0.586],
        3: [0.340, 0.504, 0.669],
        4: [0.257, 0.422, 0.586, 0.751],
    },
    "trinket": {
        2: [0.487, 0.636],
        3: [0.412, 0.561, 0.711],
        4: [0.337, 0.487, 0.636, 0.786],
    },
    # Tavern row, measured off a live recruit frame (2026-08-10): centres sit
    # 0.0703 apart around 0.5165.
    "shop": {n: [0.5165 + (i - (n - 1) / 2) * 0.0703 for i in range(n)]
             for n in range(2, 8)},
    # Discover / Choose-One cards, MEASURED 2026-08-12 off a live three-option
    # dialog in a 1892x1000 game window - the same way the hero and shop rows
    # were measured, and the method reproduces the hero row's recorded
    # fractions to within 0.003 on the same recording. The dialog draws each
    # card inside a green glow, so the edges are findable to the pixel: the
    # glow columns sit at 448-465 / 708-731, 803-825 / 1066-1087, 1164-1184 /
    # 1424-1447, which puts the card centres at 588.0, 945.2, 1304.8 = 0.3108,
    # 0.4996, 0.6897 of the window - spacing 0.1894 about the centre. The old
    # value here was a guess of 0.165, and the same frame shows what that cost:
    # the first card's badge sat 46px right of its card, in the gap.
    # Only n=3 could be measured (three is what the game deals for a discover
    # or a Dark Gift), so the other counts keep the MEASURED spacing about the
    # same centre rather than inventing a second number.
    "choice": {n: [0.4996 + (i - (n - 1) / 2) * 0.1894 for i in range(n)]
               for n in range(2, 5)},
}
# Where a badge band sits inside the game window, as a fraction of its height.
# "choice" measured on the same frame: the dialog's cards run y 302-617 (side
# glow), with the name banner at ~475, the text box at 530-620 and the tribe
# and stat banners at 630-670 - so 0.63, the old value, landed the stars on
# top of the tribe banner. 0.30 puts them across the top of the card art,
# clear of the tier gems in the card's top-left corner and clear of every line
# of text the card itself prints.
BAND_Y = {"hero": 0.235, "trinket": 0.775, "shop": 0.305, "choice": 0.30}


def avg_color(v):
    """Placement number color: the greener, the better the expected finish."""
    if v is None:
        return DIM
    if v <= 3.45:
        return GOOD
    if v <= 3.85:
        return "#b9d16f"
    if v <= 4.25:
        return AMBER
    return BAD


def rrect(c, x1, y1, x2, y2, r, **kw):
    """A rounded rectangle on a plain canvas - smoothed polygon, no images."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def panel_frame(c, w, h, r=RADIUS):
    """The slab a panel is drawn on: a gold rim with depth, then the face.

    Six items, flat fills, no gradient - and that is the whole budget. These
    windows repaint on every shop roll (the tavern rebuilds itself on every
    refresh, a buy and a sell), so anything that costs per-frame work in
    proportion to the panel's SIZE - a gradient faked with one line per pixel
    row, a drop shadow drawn as rings - would be paid for on every one of
    those repaints. Concentric shapes cost the same six items at 316px as at
    4K, and Canvas.scale resizes them for free.

    Why three tones instead of the 1px outline this replaced: a single hairline
    reads as a border on a web page. Metal reads as metal because it is set
    into something dark, catches the light along its top edge and falls into
    shadow along its bottom, and those are exactly the three shapes below.
    Everything is inset in BASE pixels, so the rim thickens with the scale
    instead of staying a hairline on a 4K screen.

    Tagged "frame" so redraw() can drop the whole thing underneath the body in
    one call, with its own layers still in order.

    The skin, when data/skin/ is present, paints the same slab as ONE image
    item instead (generated wood + a nine-sliced gold frame), baked at the
    FINAL pixel size because Canvas.scale moves an image's anchor and nothing
    else. The anchor is (0, 0), which the scale maps to (0, 0), so the same
    coordinate path serves both chromes. A None from the skin - no folder, no
    Pillow, a bad file, headless - falls through to the vectors below.
    """
    t = ("frame",)
    img = skin.panel(c, round(w * _scale), round(h * _scale),
                     round(r * _scale), _scale)
    if img is not None:
        c.create_image(0, 0, image=img, anchor="nw", tags=t)
        return
    # The flat default, copied from how the shipped trackers present
    # (measured 2026-08-14: Firestone draws flat panels with no border and
    # no ornament on #190505; HSReplay the same on #1a0e1f). One face, one
    # hairline of the darkest tone so the panel still ends somewhere against
    # the game - the three-tone gold rim this replaced was invented here,
    # not copied from anything, and the founder called it.
    rrect(c, 0, 0, w, h, r, fill=PANEL, outline=EDGE, tags=t)


def header_slab(c, w, h=HEADER_H):
    """The raised bar the title sits on, and the groove under it.

    Four items. The slab is a rounded rectangle squared off along its bottom
    (a second rectangle over the lower corners), so it follows the panel's own
    corner radius at the top and butts flat into the body underneath - which
    is what makes it read as a bar laid ON the panel rather than a differently
    coloured stripe. The groove is one dark line with one lit line under it:
    a two-pixel bevel is the cheapest thing that has an edge.

    Skinned, the slab is the generated wood strip with its own gold rule
    along the bottom, top corners masked to the panel's radius. Same inset,
    same tag, same fallback rule as panel_frame.
    """
    t = ("header",)
    img = skin.header(c, round((w - 6) * _scale), round((h + 1) * _scale),
                      round((RADIUS - 3) * _scale))
    if img is not None:
        c.create_image(3, 3, image=img, anchor="nw", tags=t)
        return
    # Flat: the slab and one rule under it. The second (bevel) line was
    # ornament; the trackers separate a header from a body with one line.
    rrect(c, 3, 3, w - 3, h + 3, RADIUS - 3, fill=HEADER_BG, outline="",
          tags=t)
    c.create_rectangle(3, h - 6, w - 3, h + 3, fill=HEADER_BG, outline="",
                       tags=t)
    c.create_line(4, h + 3, w - 4, h + 3, fill=SHADE, tags=t)


def plate(c, x1, y1, x2, y2, r=9, best=False, tags=()):
    """One row drawn as a plate on the panel face.

    Two items: the plate and the hairline along its top edge that gives it a
    lip. ``best`` is the ONE place a gold outline is spent inside a panel -
    the row the player is being pointed at - so the accent still means
    something when it appears. Every other row is the same quiet plate.

    Skinned, the plate is the generated wooden plate (the gold-rimmed one for
    ``best``), stretched to the row. Its feathered edges are safe here - the
    plate lies entirely on the opaque panel, never over the click-through
    hole - and its lip and shadow are baked into the art.
    """
    img = skin.plate(c, round((x2 - x1) * _scale), round((y2 - y1) * _scale),
                     bool(best))
    if img is not None:
        c.create_image(x1, y1, image=img, anchor="nw", tags=tags)
        return
    # Flat: a lighter fill IS the row, the way the trackers do it (Firestone
    # rows are a translucent lightening of the backdrop and nothing else).
    # The lip hairline was ornament and is gone. ``best`` keeps its one thin
    # gold outline - the single accent this chrome spends anywhere.
    rrect(c, x1, y1, x2, y2, r, fill=PANEL_HI if best else ROW,
          outline=GOLD if best else "", tags=tags)


def tile_row(c, x1, y1, x2, y2, card, best=False, tags=(), tier=None):
    """A minion row drawn the way every Hearthstone tracker draws one: the
    game's own deck-list art slice IS the row, right-aligned, fading into
    the dark bar the name sits on (skin.tile). True when it painted; False
    means no tile on disk and the caller draws its icon-and-text row.

    ``tier`` completes the deck-list anatomy: the gem on the row's left with
    the number in it, exactly where a deck list wears its cost. The gem
    image is fetch-art's UI chrome; without it the number is drawn bare in
    the same spot, so the column exists either way."""
    img = skin.tile(c, card, round((x2 - x1) * _scale),
                    round((y2 - y1) * _scale), bool(best))
    if img is None:
        return False
    c.create_image(x1, y1, image=img, anchor="nw", tags=tags)
    if tier is not None:
        h = y2 - y1
        g = min(h - 2, 20)
        gy = y1 + (h - g) / 2
        # The game's own tavern-tier shield when extracted
        # (tools/extract_game_assets.py), the deck-list gem otherwise; the
        # number is drawn, because five baked stars at 18px are mush.
        gem = (skin.ui_icon(c, "game/shield", round(g * _scale))
               or skin.ui_icon(c, "gem", round(g * _scale)))
        if gem is not None:
            c.create_image(x1 + 3, gy, image=gem, anchor="nw", tags=tags)
        shadow_text(c, x1 + 3 + g / 2, y1 + h / 2, str(tier), TEXT, F_CHIP)
    return True


def art_frame(c, x1, y1, x2, y2, best=False):
    """A thin metal edge around a piece of card art - the game frames every
    card it draws, and unframed art on a dark panel reads as a sticker.

    Skinned, the edge is the generated brass frame, dimmed for the rows that
    are not ``best`` (the same GOLD vs GOLD_LO split the vector draws). The
    hole in its middle is real alpha, so the art shows through it."""
    img = skin.art_frame(c, round((x2 - x1) * _scale),
                         round((y2 - y1) * _scale), bool(best))
    if img is not None:
        c.create_image(x1, y1, image=img, anchor="nw")
        return
    c.create_rectangle(x1, y1, x2, y2, outline=GOLD if best else GOLD_LO,
                       fill="")


def shadow_text(c, cx, cy, text, fill, font, anchor="center"):
    """Text with a dark halo so it reads over any card art - no backdrop box.

    The halo is offset by whole pixels, so it has to grow with the text or a
    doubled badge would wear a one-pixel outline that reads as a blur instead
    of a shadow. One pixel at scale 1.0, unchanged.
    """
    o = max(1, int(round(getattr(font, "ratio", 1.0))))
    for dx, dy in ((-o, -o), (o, -o), (-o, o), (o, o), (0, 0)):
        col = HALO if (dx or dy) else fill
        c.create_text(cx + dx, cy + dy, text=text, fill=col, font=font, anchor=anchor)


_FONTS = {}


def fit_text(text, max_px, font=F_SUB):
    """``text`` shortened until it really fits ``max_px``, measured in the font
    it will be drawn in.

    A panel is a fixed width inside a fixed band, and canvas text does not
    wrap: one word too many runs under the number on the right or straight off
    the panel. Cutting on a word boundary and MEASURING (instead of guessing a
    character count) is what stops a contributed line of text from breaking a
    layout nobody re-tested.

    ``max_px`` is a base-pixel width taken from a base-pixel layout, so the
    measuring is done in base pixels too - a ScaledFont answers that way by
    design, and the scale is applied to the finished canvas afterwards.
    """
    text = " ".join((text or "").split())
    if not text:
        return ""
    try:
        if isinstance(font, ScaledFont):
            measure = font.measure
        else:
            # A Font belongs to ONE interpreter: keeping it past its root's
            # destroy raises "application has been destroyed" on the next
            # measure. The test harness builds and destroys a manager per log,
            # so the cache is keyed by the live root and a dead one simply
            # never matches.
            root = tk._default_root
            key = (id(root), font)
            m = _FONTS.get(key)
            if m is None:
                _FONTS.clear()
                m = _FONTS[key] = tkfont.Font(font=font)
            measure = m.measure
        if measure(text) <= max_px:
            return text
        words = text.split(" ")
        while len(words) > 1:
            words.pop()
            cut = " ".join(words) + "…"
            if measure(cut) <= max_px:
                return cut
        while text and measure(text + "…") > max_px:
            text = text[:-1]
        return text + "…"
    except Exception:
        # No usable Tk yet, or it went away mid-draw: fall back to an average
        # glyph width. Never let measuring text be what breaks a redraw.
        return text if len(text) * 5.4 <= max_px else text[:max(1, int(max_px / 5.4))]


def advance(c, item):
    """The right-hand edge of a canvas item just drawn, in BASE pixels.

    ``draw()`` positions in base pixels but paints in scaled fonts, so a text
    item is physically wider than the base layout expects and ``bbox()[2]``
    would push whatever comes next too far right. At scale 1.0 this returns
    ``c.bbox(item)[2]`` untouched - the same call, the same pixels, which is
    what keeps the default overlay identical to the one before scaling existed.
    """
    b = c.bbox(item)
    if b is None:
        return 0
    if _scale == 1.0:
        return b[2]
    return b[0] + (b[2] - b[0]) / _scale


def offer_rows(c, y, rows, width, art, min_sample=0):
    """Draw a ranked list of offered cards - one big color-graded placement
    number each, the standout highlighted, a bar whose length is the expected
    finish. Shared by the hero-draft and trinket windows because those two
    offers read identically; nothing else uses it.

    Returns the y below the last row. A row with no stats shows a dash - never
    a filled-in guess.

    A row may carry ``tip``: one line of community-written advice, drawn in the
    strip the placement bar would use. It replaces the bar rather than adding a
    line, so the row stays 48px and the window cannot grow past the band it is
    allotted (see the layout law in ui/__init__.py). No tip, no line - the
    space stays empty and the bar comes back.
    """
    best = next((r for r in rows
                 if r.get("avg") is not None and r.get("n", 0) >= min_sample), None)
    for r in rows:
        shown = r.get("adj") if r.get("adj") is not None else r.get("avg")
        is_best = r is best
        # Every row is a plate now, not just the standout - a list of floating
        # text on a dark face is what made this panel read as a debug console.
        # What still separates the standout is what always did: it is lighter,
        # it is the only thing in the panel wearing the gold edge, and it keeps
        # the colour-graded bar down its left side.
        plate(c, 8, y + 1, width - 8, y + 45, 9, best=is_best)
        if is_best:
            c.create_rectangle(8, y + 8, 11, y + 38, fill=avg_color(shown), outline="")
        ic = art.icon(r.get("card"), 30) or art.icon_for_name(r["name"], 30)
        tx = 20
        if ic is not None:
            c.create_image(18, y + 22, image=ic, anchor="w")
            art_frame(c, 17, y + 6, 49, y + 38, is_best)
            tx = 54
        c.create_text(tx, y + 14, text=r["name"][:22], anchor="w",
                      fill=TEXT if is_best else SOFT, font=F_NAME)
        if r.get("avg") is None:
            sub = "no data at this MMR"
        else:
            sub = (f"{r['pick']:.0f}% pick · {r['n']:,} games"
                   if r.get("pick") is not None else f"{r.get('n', 0):,} games")
            if r.get("n", 0) < min_sample:
                sub += " · thin!"
        c.create_text(tx, y + 31, text=sub, anchor="w", fill=DIM, font=F_SUB)
        tip = " ".join(str(r.get("tip") or "").split())
        # width-14, the doctrine's right margin - the polish review measured
        # a 4px stagger between these values and every header's right edge.
        if shown is not None:
            col = avg_color(shown)
            c.create_text(width - 14, y + 16, text=f"{shown:.2f}", anchor="e",
                          fill=col, font=F_BIG)
            if r.get("adj") is not None and r.get("avg") is not None:
                d = r["adj"] - r["avg"]
                c.create_text(width - 14, y + 32, text=f"{d:+.2f} here", anchor="e",
                              fill=col if d < 0 else DIM, font=F_DELTA)
            if not tip:
                frac = max(0.10, min(1.0, (5.2 - shown) / 2.2))
                c.create_rectangle(20, y + 41, width - 94, y + 43, fill=LINE, outline="")
                c.create_rectangle(20, y + 41, 20 + (width - 114) * frac, y + 43,
                                   fill=col, outline="")
        else:
            c.create_text(width - 14, y + 16, text="—", anchor="e",
                          fill=DIM, font=F_BIG)
        if tip:
            # F_CHIP inside the plate: the review measured the F_SUB tip's
            # descenders striking through the best row's gold outline.
            c.create_text(tx, y + 40, text=fit_text(tip, width - tx - 18),
                          anchor="w", fill=SOFT, font=F_CHIP)
        y += 48
    return y


def _on_any_screen(x, y, w, h):
    """True when any part of the rectangle shows on any monitor.

    This is the test that decides whether a saved window position is honored
    or rescued: "at least partially visible somewhere" is the user's own
    layout, "fully off every screen" is a display that no longer exists.
    MonitorFromRect with MONITOR_DEFAULTTONULL answers exactly that question -
    NULL means no display intersects the rect. The fallback is the virtual
    screen's bounding box, which is wrong only for L-shaped multi-monitor
    layouts and only in the safe direction (it can call a dead spot visible,
    never a visible window dead). When even that cannot be asked, the save is
    left alone: rescuing on ignorance would reintroduce the snap-back.
    """
    try:
        r = wintypes.RECT(int(x), int(y), int(x + w), int(y + h))
        u = ctypes.windll.user32
        u.MonitorFromRect.restype = ctypes.c_void_p
        u.MonitorFromRect.argtypes = (ctypes.POINTER(wintypes.RECT), wintypes.DWORD)
        return u.MonitorFromRect(ctypes.byref(r), 0) is not None   # DEFAULTTONULL
    except Exception:
        pass
    try:
        u = ctypes.windll.user32
        vx, vy = u.GetSystemMetrics(76), u.GetSystemMetrics(77)    # XVIRTUALSCREEN
        vw, vh = u.GetSystemMetrics(78), u.GetSystemMetrics(79)    # CXVIRTUALSCREEN
        return x < vx + vw and x + w > vx and y < vy + vh and y + h > vy
    except Exception:
        return True


def hs_hwnd():
    """Hearthstone's window handle, or 0."""
    u = ctypes.windll.user32
    return (u.FindWindowW("UnityWndClass", "Hearthstone")
            or u.FindWindowW(None, "Hearthstone"))


def hs_rect():
    """The Hearthstone window rectangle, or None when it isn't on screen."""
    u = ctypes.windll.user32
    hwnd = hs_hwnd()
    if not hwnd or not u.IsWindowVisible(hwnd):
        return None
    r = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    if r.right - r.left < 300:      # minimised
        return None
    return r


# Window styles, so the mode report below reads as words rather than hex.
_WS_CAPTION, _WS_POPUP, _WS_THICKFRAME = 0x00C00000, 0x80000000, 0x00040000


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def monitor_size(hwnd=None):
    """The size of the monitor a window is on, primary if none is given.

    GetSystemMetrics(0/1) is the PRIMARY monitor and nothing else, so anything
    that measures a window against it is wrong the moment the game is dragged
    to a second screen of a different size.
    """
    u = ctypes.windll.user32
    try:
        if hwnd:
            # MONITOR_DEFAULTTONEAREST: a window half off the edge still
            # belongs to the screen showing most of it.
            mon = u.MonitorFromWindow(wintypes.HWND(hwnd), 2)
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if mon and u.GetMonitorInfoW(mon, ctypes.byref(info)):
                m = info.rcMonitor
                return m.right - m.left, m.bottom - m.top
    except Exception:
        pass
    return u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def hs_window_mode():
    """What display mode Hearthstone is in, and whether we can draw over it.

    Worth being precise about what is knowable here, because the honest answer
    is "mostly": from outside the process, BORDERLESS fullscreen and EXCLUSIVE
    fullscreen look identical. Both are a caption-less popup filling the
    monitor; the difference is whether the GPU is flipping the game's buffer
    straight to the display, which is a property of the swap chain and not of
    the window.

    What makes it mostly academic on a current machine: Windows 10 and 11 turn
    on Fullscreen Optimizations by default, which runs a DirectX fullscreen app
    through the desktop compositor anyway. When that is in force, an ordinary
    topmost window composites over the game and this overlay works in
    "fullscreen" exactly as it does in borderless. That is also why the Discord
    and Steam overlays usually work in fullscreen now.

    So this reports the facts it can prove and stops there. Anything that could
    tell the two apart for certain means hooking the game's swap chain, which
    is code injection into another process, and this tool does not do that.

    Returns a dict, or None when the game is not running.
    """
    u = ctypes.windll.user32
    hwnd = hs_hwnd()
    if not hwnd:
        return None
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    style = u.GetWindowLongPtrW(hwnd, -16)          # GWL_STYLE
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    # The screen to compare against is the one the GAME is on, not the primary
    # one. GetSystemMetrics only ever describes the primary monitor, so on a
    # second screen of a different size it would call a perfectly ordinary
    # window "fullscreen", or a real fullscreen game a window.
    sw, sh = monitor_size(hwnd)
    titled = bool(style & _WS_CAPTION)
    full = w >= sw and h >= sh
    if titled:
        mode, ok = "windowed", True
    elif full:
        # The one honest label for the pair that cannot be separated here.
        mode, ok = "fullscreen or borderless", True
    else:
        mode, ok = "borderless (not filling the screen)", True
    return {"hwnd": hwnd, "mode": mode, "size": (w, h), "screen": (sw, sh),
            "titled": titled, "fills_screen": full, "can_draw": ok,
            "popup": bool(style & _WS_POPUP)}


# ------------------------------------------------------------------- assets

class ArtCache:
    """cardId -> a scaled Tk image of its card art, loaded once and kept.

    Tk garbage-collects images with no surviving reference, so every image is
    held in self._imgs for the life of the overlay.
    """

    def __init__(self, names_fn=None):
        self._imgs = {}
        self._name_id = None
        self._names_fn = names_fn

    def id_for(self, name: str):
        # Names collide across sets (a BG hero shares its name with a
        # constructed card), so prefer the Battlegrounds cardId - that's the
        # one we have art for.
        if self._name_id is None:
            m = {}
            names = self._names_fn() if self._names_fn else {}
            for cid, nm in names.items():
                bgpool = cid.startswith("BG") or cid.startswith("TB_BaconShop")
                if nm not in m or (bgpool and not m[nm][1]):
                    m[nm] = (cid, bgpool)
            self._name_id = {nm: cid for nm, (cid, _) in m.items()}
        return self._name_id.get(name)

    def icon(self, card_id, px=20):
        """``px`` is the BASE size, the same number every window has always
        asked for. An image is the one thing ``Canvas.scale`` moves but does
        not resize, so the scaling happens here instead: at 2.0 a 30px icon is
        decoded at 60px and lands in a slot the canvas transform has already
        made 60px wide. Cached per real size, so switching scale back and
        forth costs one decode each, not one per frame.
        """
        if not _PIL or not card_id:
            return None
        px = max(1, int(round(px * _scale)))
        key = (card_id, px)
        if key in self._imgs:
            return self._imgs[key]
        base = card_id[:-2] if card_id.endswith("_G") else card_id
        path = ASSETS / "crops" / f"{base}.jpg"
        if not path.exists():
            self._imgs[key] = None
            return None
        try:
            im = Image.open(path).convert("RGB").resize((px, px), Image.LANCZOS)
            img = ImageTk.PhotoImage(im)
        except Exception:
            img = None
        self._imgs[key] = img
        return img

    def icon_for_name(self, name, px=20):
        return self.icon(self.id_for(name), px)


# ------------------------------------------------------------- position file

class PosStore:
    """.overlay.json - one drag offset per window, under its own key.

    Every window remembers where IT was put, so moving the tavern never moves
    the combat odds. Written on every drop; a broken/absent file just means
    everything falls back to its default slot.
    """

    def __init__(self, path=POS_FILE):
        self.path = Path(path)
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            data = {}
        self.data = data if isinstance(data, dict) else {}
        self.win = self.data.setdefault("win", {})
        if not isinstance(self.win, dict):
            self.win = self.data["win"] = {}
        self.badge = self.data.setdefault("badge", {})
        if not isinstance(self.badge, dict):
            self.badge = self.data["badge"] = {}

    def get(self, key):
        v = self.win.get(key)
        return v if isinstance(v, dict) else {}

    def set(self, key, **kw):
        self.win.setdefault(key, {}).update(kw)
        self._write()

    def get_badge(self, kind):
        """(ox, oy) for one badge strip, as FRACTIONS of the game window.

        Fractions, not pixels, for the same reason SLOT_X and BAND_Y are
        fractions: the whole badge geometry follows the game window, so a
        correction saved on a 1080p window has to still be the same correction
        when the game is opened at 4K.
        """
        v = self.badge.get(kind)
        if not isinstance(v, dict):
            return 0.0, 0.0
        try:
            return float(v.get("ox", 0.0)), float(v.get("oy", 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    def set_badge(self, kind, ox, oy):
        self.badge[kind] = {"ox": round(float(ox), 5), "oy": round(float(oy), 5)}
        self._write()

    def _write(self):
        try:
            self.path.write_text(json.dumps(self.data))
        except Exception:
            pass


# -------------------------------------------------------------- badge strips

_STRIPS: list["BadgeStrip"] = []

# MOVING THE BADGES
# -----------------
# The strips are click-through so the game gets every click - which is exactly
# what makes them impossible to drag, because a drag is a click. The way out
# is a mode, not a permanent compromise: CALIBRATE MODE drops WS_EX_TRANSPARENT
# on every strip for as long as it is on, so the strips can be dragged, and
# puts it back on the way out. Normal play never runs with click-through off.
#
# WS_EX_NOACTIVATE deliberately STAYS on during calibration: the strip then
# receives the mouse without taking focus, so Hearthstone remains the
# foreground window and the overlay does not hide itself mid-drag (visibility
# follows the real foreground window - see _apply_visibility).
#
# What is saved is a per-KIND offset in fractions of the game window, on top of
# the measured SLOT_X / BAND_Y. Fractions, because everything else about a
# badge follows the game window; per kind, because the four bands sit on four
# different dialogs and being wrong about one says nothing about the others.
#
# THE MODE MUST CLOSE ITSELF. It is the one state in the whole overlay where a
# window deliberately stops being click-through. Measured on a 1920x1080 game
# by asking Windows itself (WindowFromPoint, the same hit test a real click
# goes through): with the mode ON, the point over a drawn marker answers with
# the strip; with it off, the same point answers with the window underneath.
# The blank parts of a band still pass through either way - the colour key
# makes untouched pixels holes - so the dead area is the glyphs themselves,
# and the glyphs are drawn exactly on the cards, which is the worst possible
# place for them. A player who opens the mode and forgets is playing with dead
# spots on his own board. (tests/test_badges.py checks the property this rests
# on, WS_EX_TRANSPARENT, read back out of Win32 before, during and after.)
# So there are three ways out and only one of them needs the player: the chip
# again, the next combat, or the deadline below.
_badge_edit = False
_badge_edit_at = 0.0            # monotonic time the mode closes itself at

# The cap. Every drag re-arms it (see nudge), so this is time spent doing
# NOTHING, not a limit on how long positioning may take: 90s of an untouched
# open mode is already longer than the four drags the job consists of, and it
# is short enough that a mode left on at the menu is gone before the next
# lobby. The countdown is drawn as a shrinking bar rather than a number,
# because a digit on a badge strip is the one thing this mode refuses to print
# (see _calib_rows).
BADGE_EDIT_MAX_S = 90.0

# Events that end the mode on their own. Combat is the honest boundary: the
# player got the whole recruit phase to line his badges up, and the fight is
# the moment the overlay must be out of the way again. Routed through
# BaseWindow.handle, so this needs no cooperation from overlay.py's router.
BADGE_EDIT_END_EVENTS = ("combat",)

# How far a badge may be nudged. Wide enough to fix a real mismatch (the worst
# measured error was 46px on a 1892px window = 0.024), tight enough that a
# fumbled drag cannot fling a strip off the game window and out of reach.
BADGE_OFF_MAX_X = 0.20
BADGE_OFF_MAX_Y = 0.40


def badge_edit() -> bool:
    """True while the badge strips are draggable (and NOT click-through)."""
    return _badge_edit


def badge_edit_left(now=None) -> float:
    """Seconds before the mode closes itself. 0 when it is not on."""
    if not _badge_edit:
        return 0.0
    return max(0.0, _badge_edit_at - (time.monotonic() if now is None else now))


def badge_edit_keepalive():
    """Push the deadline back: the player is still working the mode."""
    global _badge_edit_at
    if _badge_edit:
        _badge_edit_at = time.monotonic() + BADGE_EDIT_MAX_S


def badge_edit_tick(now=None) -> bool:
    """Close the mode if its time is up. True if this call closed it.

    Called from the manager poll (badge_edit_poll) and safe to call from
    anywhere: it does nothing at all while the mode is off.
    """
    if not _badge_edit:
        return False
    if (time.monotonic() if now is None else now) < _badge_edit_at:
        return False
    set_badge_edit(False)
    print("badge calibrate mode timed out - click-through restored",
          flush=True)
    return True


def badge_edit_event(name) -> bool:
    """End the mode on an event that means the game needs its clicks back.
    True if this call closed it."""
    if not _badge_edit or name not in BADGE_EDIT_END_EVENTS:
        return False
    set_badge_edit(False)
    print(f"badge calibrate mode closed by {name} - click-through restored",
          flush=True)
    return True


def set_badge_edit(on: bool) -> bool:
    """Enter or leave calibrate mode. Returns the state actually in force.

    Entering: every strip drops click-through, shows a calibration pattern -
    a marker per slot, carrying no numbers at all, because a placeholder
    number is still a made-up number - and starts listening for a drag.
    Leaving: click-through goes back on every strip, the calibration pattern
    is dropped, and whatever the strip was really showing comes back.
    """
    global _badge_edit, _badge_edit_at
    on = bool(on)
    if on == _badge_edit:
        return _badge_edit
    _badge_edit = on
    _badge_edit_at = time.monotonic() + BADGE_EDIT_MAX_S if on else 0.0
    rect = hs_rect()
    for s in list(_STRIPS):
        try:
            if on:
                s.calibrate_on(rect)
            else:
                s.calibrate_off()
        except Exception:
            traceback.print_exc()
    if not on:
        # calibrate_off puts each strip back to what IT was doing when the mode
        # opened, and a strip that was suppressed then (outranked, or an offer
        # that arrived while the mode was up) was doing nothing. Without this
        # the rows survive off screen until their own next event, which for the
        # tavern stars is a whole shop away. revive_strips is the arbiter that
        # decides who is on top now; it no-ops while _badge_edit is still set,
        # which is why it is called here rather than inside calibrate_off.
        revive_strips(rect)
    return _badge_edit


def badge_edit_poll(rect, game_front):
    """Keep the calibration strips honest about the game window.

    Called from the manager's poll. Calibration strips belong to windows that
    may well be closed, so nothing else re-anchors them or hides them when the
    game stops being the foreground window.

    This is also what enforces the deadline, and it runs whether or not the
    game is in front: a mode left on behind an alt-tab must still close, or it
    would be waiting with its dead spots when the player comes back.
    """
    if not _badge_edit or badge_edit_tick():
        return
    for s in list(_STRIPS):
        try:
            if not s.calib:
                continue
            if game_front and rect is not None:
                s.show(s.rows, rect)
            elif s.visible:
                s.visible = False
                s.withdraw()
        except Exception:
            traceback.print_exc()


# How many markers to show per kind while positioning: the count that dialog
# usually deals, so the pattern sits where the real badges will. The slots for
# three cards are not the slots for four, and lining a strip up against the
# wrong count would build the error back in.
_CALIB_N = {"hero": 4, "trinket": 4, "shop": 5, "choice": 3}


def revive_strips(rect=None):
    """Put back the best strip that still holds rows and is no longer
    outranked.

    Showing a strip SUPPRESSES the lower-priority ones (rows kept, see
    BadgeStrip.suppress), and nothing else would bring the victims back before
    their next event - for the tavern stars that is the next roll, a whole
    shop away. So whoever is now on top is re-shown here, and its own show()
    re-suppresses anything under it.
    """
    if _badge_edit:
        return                       # the mode owns every strip while it is on
    for s in sorted(_STRIPS, key=lambda s: -s.priority):
        r = rect if rect is not None else s.rect
        if s.visible or s.calib or not s.rows or r is None:
            continue
        # Never bring a strip back onto a screen the game is not on. A strip
        # is withdrawn on alt-tab with its rows intact, so without this a
        # dialog closing in the background would paint badges over whatever
        # the player switched to. (headless keeps game_front True by design.)
        app = getattr(s.master, "app", None)
        if app is not None and not getattr(app, "game_front", True):
            continue
        if any(o.visible and o.priority > s.priority for o in _STRIPS):
            continue
        try:
            s.show(s.rows, r)
        except Exception:
            traceback.print_exc()


def _calib_rows(kind):
    """The pattern a strip shows while it is being positioned.

    Markers and the strip's own name - never a number, not even a fake one:
    the point of the mode is to line the badges up with the cards, and a
    plausible-looking 4.21 sitting on a card the player is about to click is
    exactly the lie this project refuses to tell.
    """
    return [{"pos": i + 1, "name": kind, "calib": True}
            for i in range(_CALIB_N.get(kind, 3))]


class BadgeStrip(tk.Toplevel):
    """A click-through, fully transparent band over the Hearthstone window,
    drawing one badge under (or over) each offered card - the number attached
    to the character it belongs to, not a list in a corner.

    Strips arbitrate by PRIORITY instead of by a shared mode: showing a strip
    hides every visible strip of lower priority. That is how the tavern stars
    get out of the way when a discover opens, without either window knowing
    the other exists.
    """

    def __init__(self, master, kind, priority=0, store=None):
        super().__init__(master)
        self.kind, self.priority = kind, priority
        self.store = store
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.97)
        self.attributes("-transparentcolor", TRANS)
        self.configure(bg=TRANS)
        self.canvas = tk.Canvas(self, bg=TRANS, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.rows, self.rect = [], None
        self.min_sample = 0
        self.visible = False
        self.calib = False          # showing the calibration pattern
        self._saved = None          # the real rows, parked during calibration
        self._drag = None
        self.ox, self.oy = (store.get_badge(kind) if store is not None
                            else (0.0, 0.0))
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.withdraw()
        _STRIPS.append(self)
        self.after(120, self.clickthrough)

    # -- click-through -----------------------------------------------------

    def _hwnd(self):
        """The wrapper window Windows actually hit-tests, not the Tk child."""
        u = ctypes.windll.user32
        return u.GetParent(self.winfo_id()) or self.winfo_id()

    def ex_style(self):
        """The strip's current extended window style, or None if it cannot be
        read. Exists so the click-through property can be CHECKED - by the
        window test, and by anyone debugging a strip that eats clicks - rather
        than assumed from the fact that we called SetWindowLongPtrW once."""
        try:
            u = ctypes.windll.user32
            u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
            return u.GetWindowLongPtrW(self._hwnd(), -20)     # GWL_EXSTYLE
        except Exception:
            return None

    def clickthrough(self):
        """Let clicks pass through to the game underneath.

        Except while calibrate mode is on, which is the one state where the
        strip has to receive the mouse itself so it can be dragged onto the
        cards. WS_EX_NOACTIVATE stays on either way, so even a strip that is
        taking clicks never takes FOCUS away from the game.
        """
        try:
            GWL_EXSTYLE = -20
            WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x8000000
            u = ctypes.windll.user32
            # Without explicit signatures these calls silently corrupt args on
            # 64-bit Python - the style write "succeeds" and changes nothing.
            u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
            u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
            hwnd = self._hwnd()
            style = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_NOACTIVATE
            if _badge_edit:
                style &= ~WS_EX_TRANSPARENT
            else:
                style |= WS_EX_TRANSPARENT
            u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass    # worst case the badges eat clicks in their own band

    # -- calibrate mode ----------------------------------------------------

    def calibrate_on(self, rect):
        """Take the click-through off and show the positioning pattern.

        ``rect`` may be None when the game window cannot be found this
        instant; the strip's own last known rect is used instead, so the mode
        still comes up while the game is mid-loading screen. With neither, the
        manager's next poll brings it up (badge_edit_poll).
        """
        self.calib = True
        if self._saved is None:
            self._saved = (list(self.rows), self.min_sample, self.visible)
        self.clickthrough()
        self.rows = _calib_rows(self.kind)
        rect = rect if rect is not None else self.rect
        if rect is not None:
            self.show(self.rows, rect)

    def calibrate_off(self):
        """Put the click-through back and restore whatever was really up."""
        self.calib = False
        self._drag = None
        rows, min_sample, was_visible = self._saved or ([], 0, False)
        self._saved = None
        self.rows, self.min_sample = rows, min_sample
        if was_visible and rows and self.rect is not None:
            self.show(rows, self.rect)
        else:
            self.visible = False
            self.withdraw()
        # After the withdraw, and unconditionally: the style must be back on
        # even for a strip that is not on screen, because the next show() of a
        # hidden strip happens on an offer, in the middle of a game.
        self.clickthrough()

    def nudge(self, ox, oy, save=True):
        """Move this KIND of badge by a fraction of the game window.

        Kind, not strip: two windows can own the same band (the discover panel
        and the hero-power panel are both dealt on the Choose-One frame, so
        both carry kind "choice"), they share one saved offset, and dragging
        one of them has to move the other or the correction would apply to
        whichever dialog happened to be open when it was made.
        """
        self.ox = max(-BADGE_OFF_MAX_X, min(BADGE_OFF_MAX_X, float(ox)))
        self.oy = max(-BADGE_OFF_MAX_Y, min(BADGE_OFF_MAX_Y, float(oy)))
        if save and self.store is not None:
            self.store.set_badge(self.kind, self.ox, self.oy)
        for s in _STRIPS:
            if s is self or s.kind != self.kind:
                continue
            s.ox, s.oy = self.ox, self.oy
            if s.visible and s.rows and s.rect is not None:
                s.show(s.rows, s.rect)
        if self.visible and self.rows and self.rect is not None:
            self.show(self.rows, self.rect)
        return self.ox, self.oy

    def _press(self, e):
        if not (_badge_edit and self.calib):
            return
        # Touching a strip is the player saying he is still on the job, so the
        # auto-close deadline starts again from here. Without this a careful
        # drag could be interrupted by the very timeout that exists to protect
        # somebody who walked away.
        badge_edit_keepalive()
        self._drag = (e.x_root, e.y_root, self.ox, self.oy)

    def _motion(self, e):
        if not self._drag or self.rect is None:
            return
        badge_edit_keepalive()
        px, py, ox0, oy0 = self._drag
        gw = max(1, self.rect.right - self.rect.left)
        gh = max(1, self.rect.bottom - self.rect.top)
        self.nudge(ox0 + (e.x_root - px) / gw, oy0 + (e.y_root - py) / gh,
                   save=False)

    def _release(self, e):
        if not self._drag:
            return
        badge_edit_keepalive()
        self._drag = None
        if self.store is not None:
            self.store.set_badge(self.kind, self.ox, self.oy)

    def show(self, rows, rect, min_sample=None):
        """Draw one badge per row. Rows carry either stars (shop/discover) or
        an avg/adj placement (hero/trinket); both shapes are read defensively.

        ``min_sample`` rides WITH the rows: the owning window passes it on a
        real show, and it is stored so the re-shows that do not come from the
        window - the settings panel's badge nudge, the game window moving -
        repaint with the same threshold instead of silently dropping it to 0
        and crowning a 3-game average "best". None means "keep what the last
        real show set".

        WHERE a badge goes has always followed the game window - SLOT_X and
        BAND_Y are fractions of it. How BIG it is did not: the band was a flat
        40px and the fonts flat points, so on a 4K game the badges landed
        perfectly on the cards at half the size they should be. That is what
        badge_scale fixes, and it is driven by the game window's height rather
        than by the panel preference (the cards under it grew with the game,
        not with the side panels).
        """
        if rect is None or not rows:
            return
        if self.calib and not rows[0].get("calib"):
            # A REAL offer arrived while this band is being positioned. It is
            # parked, not drawn and not dropped: drawing it would replace the
            # pattern the player is dragging (and with the offer's own slot
            # count, so he would be lining up markers that move under him),
            # and dropping it would cost him the badges on a dialog that is
            # open right now the moment the mode closes. calibrate_off shows
            # whatever is parked here.
            self._saved = (list(rows),
                           self.min_sample if min_sample is None else min_sample,
                           True)
            self.rect = rect
            # The offer still tells us where the game window is, which is the
            # one thing a strip needs and may not have yet (calibrate_on runs
            # with whatever hs_rect answered, and that can be nothing during a
            # loading screen). So the band comes up now, with the PATTERN -
            # self.rows are the calibration rows, so this recurses exactly one
            # level and takes the branch below. The test is on the rows rather
            # than on self.calib: anything else would call itself forever if a
            # strip ever reached this line holding real rows.
            if self.rows and self.rows[0].get("calib"):
                self.show(self.rows, rect)
            return
        if min_sample is not None:
            self.min_sample = min_sample
        min_sample = self.min_sample
        self.rows, self.rect = rows, rect
        # Priority arbitration is about which OFFER matters, and in calibrate
        # mode no offer is up: every band is deliberately on screen at once so
        # all four can be positioned in one pass.
        #
        # It has to work in BOTH directions. Suppressing everything lower only
        # covers the strip that comes up last; a shop roll arriving UNDER an
        # open discover used to draw itself anyway, and since the two bands are
        # 5px apart on a 1080p game (BAND_Y shop 0.305, choice 0.30) that is
        # two sets of badges printed over each other. So a strip that is
        # outranked right now keeps its rows and stays off screen instead -
        # hide() brings it back when the winner goes away.
        if not _badge_edit:
            for s in _STRIPS:
                if s is not self and s.visible and s.priority < self.priority:
                    try:
                        # Suppressed, not hidden: the rows stay, so the strip
                        # can come back if this one goes away (hide, and
                        # WindowManager.disable).
                        s.suppress()
                    except Exception:
                        s.visible = False  # already destroyed; drop the claim
            if any(s is not self and s.visible and s.priority > self.priority
                   for s in _STRIPS):
                self.suppress()
                return
        rows = sorted(rows, key=lambda r: r.get("pos") or 0)
        n = len(rows)
        xs = (SLOT_X.get(self.kind, {}).get(n)
              or [0.5 + (i - (n - 1) / 2) * 0.135 for i in range(n)])
        gw = rect.right - rect.left
        gh = rect.bottom - rect.top
        bs = badge_scale(gh)
        for f in _BADGE_FONTS:
            f._rescale_to(bs)

        def b(v):
            return int(round(v * bs))

        band_h = b(40)
        y0 = rect.top + int(gh * (BAND_Y.get(self.kind, 0.7) + self.oy))

        c = self.canvas
        c.delete("all")
        self.geometry(f"{gw}x{band_h}+{rect.left}+{y0}")
        c.config(width=gw, height=band_h)

        if self.calib:
            self._draw_calibration(c, gw, xs, b)
            self.visible = True
            self.deiconify()
            self.lift()
            self.clickthrough()
            return

        def score(r):
            return r.get("adj") if r.get("adj") is not None else r.get("avg")

        scored = [r for r in rows
                  if score(r) is not None and r.get("n", 0) >= min_sample]
        best = min(scored, key=score, default=None)
        for r, fx in zip(rows, xs):
            cx = int(gw * (fx + self.ox))
            shown = score(r)
            col = avg_color(shown)
            if r.get("stars") is not None:
                s = r.get("stars", 0)
                # Same two-glyph rule as the tavern row it mirrors: filled and
                # colour graded means measured, hollow and muted means read off
                # the card (grades.py). The badge sits ON the card art, so it
                # is the one place the distinction must survive a scale change
                # and a busy background - a glyph does, a hairline would not.
                graded = bool(r.get("graded"))
                shadow_text(c, cx, b(12), "★" * s,
                            SOFT if graded else STAR_COLOR.get(s, DIM),
                            F_BADGE_STARS)
                # Same ranking as the tavern row: the mechanical read wins the
                # one line under the stars whenever it has a count behind it,
                # because that one is about the board in front of the player.
                if r.get("mine"):
                    shadow_text(c, cx, b(28), "▶ your build", ACCENT, F_BADGE_CHIP)
                elif r.get("syn"):
                    shadow_text(c, cx, b(28), r["syn"][:16], GOOD, F_BADGE_CHIP)
                elif r.get("comp"):
                    shadow_text(c, cx, b(28), r["comp"][:14], SOFT, F_BADGE_CHIP)
            elif shown is None:
                shadow_text(c, cx, b(14), "—", DIM, F_BADGE_NAME)
            else:
                # HSReplay's hero-pick cells, looked up and copied (their
                # overlay page, 2026-08-14): one labelled cell per stat above
                # the card - the label tiny and muted, the value under it -
                # in flat dark boxes. The best offer wears the one gold
                # accent as its cells' outline; nothing says "best" in words.
                # Cell width is capped by the slot spacing so neighbouring
                # offers' cells cannot overlap at high badge scales (review
                # find: two b(58) cells x bs 3.0 out-ran the hero slots).
                if len(xs) > 1:
                    gap = int(gw * min(abs(b2 - a2) for a2, b2
                                       in zip(xs, xs[1:])))
                else:
                    gap = gw
                cells = [("AVG", f"{shown:.2f}", col)]
                if r.get("pick") is not None:
                    cells.append(("PICK", f"{r['pick']:.0f}%", TEXT))
                cw = min(b(58), (gap - b(8)) // len(cells) - b(2))
                ch = b(33)
                total = len(cells) * cw + (len(cells) - 1) * b(4)
                x = cx - total // 2
                for label, value, vcol in cells:
                    c.create_rectangle(x, b(3), x + cw, b(3) + ch, fill=HALO,
                                       outline=GOLD if r is best else LINE)
                    c.create_text(x + cw // 2, b(10), text=label, fill=DIM,
                                  font=F_BADGE_CHIP)
                    c.create_text(x + cw // 2, b(24), text=value, fill=vcol,
                                  font=F_BADGE_NAME)
                    x += cw + b(4)
        self.visible = True
        self.deiconify()
        self.lift()
        # Re-assert click-through on every show, and AFTER the deiconify.
        # It is first set 120ms after the strip is built, when the strip has
        # never been mapped: until it is, GetParent hands back 0 and the style
        # lands on the child instead of the wrapper Windows actually hit-tests.
        # Measured with the timer suppressed: set before the deiconify the
        # wrapper reads 0x80088 (no WS_EX_TRANSPARENT, so the strip eats clicks
        # in its band); set after it, 0x80800A8. Four Win32 calls per show.
        #
        # And once more on the next idle, because deiconify() only QUEUES the
        # map: on the very first show of a strip the window is still unmapped
        # when the line above runs, GetParent still answers 0, and the style
        # lands on the Tk child instead of the wrapper Windows hit-tests -
        # i.e. the first offer of a session would have had a strip eating
        # clicks in its band. Measured by reading the style back (see
        # tests/test_badges.py): without this line the first show of the
        # discover strip reads 0x80088.
        self.clickthrough()
        self.after_idle(self.clickthrough)

    def _draw_calibration(self, c, gw, xs, b):
        """The positioning pattern: one marker per slot, this strip's own name,
        what the mode is costing the player, and how long it has left.

        No numbers - see _calib_rows - and that includes the countdown, which
        is a bar that shrinks rather than a digit: this strip sits on the
        cards, and the rule that nothing here may look like a rating does not
        get an exception for a clock.
        """
        label = {"hero": "hero badges", "trinket": "trinket badges",
                 "shop": "shop badges", "choice": "pick badges"}.get(
                     self.kind, self.kind)
        # Hard against the left edge of the band rather than beside the first
        # marker: the leftmost slot moves with the offset, and a label that
        # follows it ends up printed over its own "here" (seen on screen).
        #
        # "clicks blocked" is the important half. With the mode on, a click on
        # any pixel drawn here is answered by the strip instead of by the game
        # (measured with WindowFromPoint - see the mode's own note above), so
        # the player is told, on every one of the four bands, in the same
        # place he is being asked to drag.
        shadow_text(c, b(12), b(14), f"⇕ {label} · drag", ACCENT,
                    F_BADGE_CHIP, anchor="w")
        shadow_text(c, b(12), b(26), "clicks blocked here", BAD,
                    F_BADGE_CHIP, anchor="w")
        # The deadline as a bar under the words: full when the mode opens or a
        # drag re-arms it, empty when it is about to close itself.
        left = badge_edit_left() / BADGE_EDIT_MAX_S if BADGE_EDIT_MAX_S else 0
        x0, x1 = b(12), b(12) + b(96)
        c.create_rectangle(x0, b(33), x1, b(36), fill=HALO, outline="")
        c.create_rectangle(x0, b(33), x0 + (x1 - x0) * max(0.0, min(1.0, left)),
                           b(36), fill=ACCENT, outline="")
        for fx in xs:
            cx = int(gw * (fx + self.ox))
            shadow_text(c, cx, b(12), "▼", ACCENT, F_BADGE_STARS)
            shadow_text(c, cx, b(28), "here", ACCENT, F_BADGE_CHIP)

    def reposition(self, rect):
        """The game window moved: redraw in place, keeping the same rows (and
        the same min_sample - show() keeps the stored one when none is
        passed)."""
        if self.visible and self.rows:
            self.show(self.rows, rect)

    def suppress(self):
        """Outranked by a higher-priority strip: off screen, but the rows and
        the threshold are KEPT so this strip can be revived when the winner
        goes away (hide, and WindowManager.disable).
        ``hide()`` is the owning window saying "these rows are done" - this is
        the arbiter saying "not right now"."""
        self.visible = False
        self.withdraw()

    def hide(self):
        if self.calib:
            # The owning window closed while the player is positioning this
            # band. Park the real rows and keep the pattern on screen - the
            # alternative is a strip that vanishes the moment you go to move
            # it, which is the bug this mode exists to fix.
            self._saved = ([], 0, False)
            return
        was_visible = self.visible
        self.visible = False
        self.rows = []
        self.min_sample = 0
        self.withdraw()
        if was_visible:
            # This strip may have been the arbiter holding somebody down: the
            # tavern stars are suppressed by a discover, and their next event
            # is a whole shop away.
            revive_strips()


# ------------------------------------------------------------------- windows

class BaseWindow(tk.Toplevel):
    """A frameless, anchored, draggable panel that shows exactly one concern.

    Subclasses set the class attributes below and implement ``draw`` and
    ``on_event``. They never touch another window.

    Class attributes
      KEY        unique id; also the key under "win" in .overlay.json
      TITLE      header text
      WIDTH      panel width in px
      COLUMN     "right" or "left" edge of the Hearthstone window
      DY         default y offset from the top of the Hearthstone window
      RESERVE    nominal height this window claims in the default stack
      EVENTS     event names the router should deliver here
      BADGE_KIND "hero"|"trinket"|"shop"|"choice" -> this window owns a strip
      BADGE_PRIORITY  higher wins when two strips would be up at once
      TIMEOUT_MS auto-close after this long with no new event (0 = never)
      QUIT_BUTTON  draw a X that quits the whole overlay

    Instance protocol
      show()/hide()   open or close THIS window; nothing else is affected
      redraw()        repaint now (cheap; safe to call from any handler)
      reset()         a new game started - drop everything

    WIDTH, DY, RESERVE and MAX_H are all BASE pixels and stay that way. The
    scale is applied where a number becomes screen geometry (``_w``, ``_dy``,
    ``self._h``), never by rewriting the class attributes: a class attribute
    multiplied in place drifts a little further on every call to set_scale,
    and the layout law in ui/__init__.py - which the window test checks
    against a 1920x1080 rect - is stated in base pixels and has to stay
    readable in them.
    """

    KEY = "base"
    TITLE = ""
    WIDTH = 316
    COLUMN = "right"
    DY = 70
    RESERVE = 120
    MAX_H = 700
    #: The shortest this window may be drawn. 40 is the floor a panel with a
    #: header needs to not look clipped; a window with no header (the micro
    #: counters) sets its own, or it is padded into a box its content sits in
    #: the corner of.
    MIN_H = 40
    EVENTS: tuple = ()
    BADGE_KIND = None
    BADGE_PRIORITY = 0
    TIMEOUT_MS = 0
    QUIT_BUTTON = False

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.headless = app.headless
        self._open = False
        self._mapped = False
        self._h_base = 80        # what draw() returned, in base pixels
        self._h = self._px(80)   # what is on screen
        self._xy = (60, 60)
        self._drag = None
        self._timer = None
        self._draws = 0
        self.opens = 0
        self.closes = 0
        self.errors = 0
        self.badges = None

        saved = app.pos.get(self.KEY)
        self.dx, self.dy = saved.get("dx", 0), saved.get("dy", 0)
        self.free = (saved.get("x", 60), saved.get("y", 60))

        # overrideredirect BEFORE building the widgets, or the window balloons
        # to fullscreen the first time it is mapped (tkinter trap, v1).
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.96)
        self.attributes("-transparentcolor", TRANS)
        self.configure(bg=TRANS)
        self.geometry(f"{self._wpx()}x{self._h}+{self.free[0]}+{self.free[1]}")
        self.canvas = tk.Canvas(self, bg=TRANS, highlightthickness=0, bd=0,
                                width=self._wpx(), height=self._h)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.withdraw()
        self._no_activate()

        if self.BADGE_KIND and not self.headless:
            self.badges = BadgeStrip(self, self.BADGE_KIND, self.BADGE_PRIORITY,
                                     store=app.pos)
        _LIVE.add(self)

    def _no_activate(self):
        """Never take focus from the game. Ever.

        The badge strips have carried WS_EX_NOACTIVATE since they were
        written; these windows did not, and it showed the moment the overlay
        was started or restarted mid-game (founder, 2026-08-15: "stop opening
        it in front of my game, that glitches everything"). A window mapping
        without this flag can be activated by Windows, which pulls focus off
        a fullscreen or borderless Hearthstone and makes the client stutter,
        drop the cursor, or minimise outright.

        Dragging still works: NOACTIVATE stops a window becoming the ACTIVE
        one, it does not stop it receiving the mouse.
        """
        if self.headless:
            return
        try:
            GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x8000000
            u = ctypes.windll.user32
            # Explicit signatures, for the reason spelled out in the badge
            # strip's copy: without them the write silently does nothing on
            # 64-bit Python.
            u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
            u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            u.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int,
                                            ctypes.c_ssize_t)
            hwnd = wintypes.HWND(int(self.winfo_id()))
            style = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            pass        # not Windows, or a window that has not been mapped

    # -------------------------------------------------------------- scaling

    @staticmethod
    def _px(v):
        """A base-pixel number as the screen pixels it becomes."""
        return int(round(v * _scale))

    def _wbase(self):
        """This window's width in BASE pixels. Overridden by a window that
        sizes itself to its content (ui/micro.py); everything else is the
        class constant it always was."""
        return self.WIDTH

    def _wpx(self):
        return self._px(self._wbase())

    def _rescaled(self):
        """set_scale ran. Repaint if we are up; otherwise the next redraw
        picks the new scale up on its own (it reads _scale every time)."""
        if self.headless:
            return
        if self._open:
            self.redraw()
        else:
            self._h = self._px(self._h_base)
            self.canvas.config(width=self._wpx(), height=self._h)

    # ---------------------------------------------------------- subclass API

    def draw(self, c) -> int:
        """Paint the panel body; return the total height in px."""
        raise NotImplementedError

    def on_event(self, name, payload):
        """React to one routed event. Call show()/hide()/redraw() as needed."""

    def on_click(self, x, y) -> bool:
        """Return True if the click was consumed (so no drag starts)."""
        return False

    def reset(self):
        """A new game began - forget everything and close."""
        self.hide()

    # -------------------------------------------------------------- plumbing

    def handle(self, name, payload):
        """Router entry point. A window that throws is reported and skipped -
        it must never break the dispatch chain for the other windows."""
        # The badge calibrate mode is the one state where the strips are not
        # click-through, and the router is the only thing in the overlay that
        # knows the game moved on. This runs before the window's own handler
        # so the click-through is back BEFORE anything paints for the new
        # phase; it is a no-op unless the mode is on (badge_edit_event).
        try:
            badge_edit_event(name)
        except Exception:
            traceback.print_exc()
        try:
            self.on_event(name, payload)
        except Exception:
            self.errors += 1
            print(f"[{self.KEY}] {name} failed:", file=sys.stderr)
            traceback.print_exc()

    def show(self):
        if not self._open:
            self._open = True
            self.opens += 1
            # Re-assert it on the first real map: the style is set at build
            # time, and a window that had never been mapped can come back
            # without it. Cheap, and the alternative is the game losing
            # focus the first time this window appears.
            self._no_activate()
        self._arm_timeout()
        self.redraw()
        self._apply_visibility()

    def hide(self):
        if self._open:
            self._open = False
            self.closes += 1
        self._cancel_timeout()
        if self.badges is not None:
            self.badges.hide()
        if not self.headless:
            self._mapped = False
            self.withdraw()

    @property
    def is_open(self):
        return self._open

    def redraw(self):
        """Paint in base pixels, then scale the finished canvas once.

        Scaling HERE rather than transforming the existing items when the
        scale changes, because a window repaints itself constantly - every
        roll rebuilds the tavern - and a transform applied outside the paint
        would be thrown away by the next one. Doing it as the last step of a
        paint that starts with ``delete("all")`` makes it idempotent by
        construction: items are created at base coordinates and transformed
        exactly once, so no sequence of redraws and scale changes can compound.
        """
        self._draws += 1
        if self.headless or not self._open:
            return
        c = self.canvas
        c.delete("all")
        h = int(self.draw(c) or 80)
        h = max(self.MIN_H, min(h, self.MAX_H))
        # The frame is drawn to the width the window ACTUALLY has. Reading
        # WIDTH here was fine while every window was a fixed size, and wrong
        # the moment one sized itself to its content: the micro counters
        # measure their own value, so a frame at the class width left the row
        # pinned to the top-left of an oversized box (founder, 2026-08-15,
        # "looks way off center").
        panel_frame(c, self._wbase(), h)
        # One call, and the frame's own six layers keep their order underneath
        # everything draw() put down (Tk's lower preserves relative order
        # inside the tag).
        c.tag_lower("frame")
        if _scale != 1.0:
            c.scale("all", 0, 0, _scale, _scale)
            # Canvas.scale moves coordinates and nothing else, so a 1px rule
            # or panel border would stay a hairline on a 4K screen. Outlines
            # are re-widened here; text items are skipped because their
            # -width is a wrap column, not a stroke.
            for i in c.find_all():
                if c.type(i) == "text":
                    continue
                try:
                    w = float(c.itemcget(i, "width"))
                except (ValueError, tk.TclError):
                    continue
                if w:
                    c.itemconfigure(i, width=max(1, round(w * _scale)))
        self._h_base = h
        h = self._px(h)
        if h != self._h or c.winfo_reqwidth() != self._wpx():
            self._h = h
            c.config(width=self._wpx(), height=h)
        self._place()

    # -- header ------------------------------------------------------------

    def header(self, c, right_text=None, right_fill=DIM, dot=None,
               right_from=None):
        """The 24px title bar every window shares. Returns the body's top y.

        Same 24px, same text, same right-hand slot: what changed is that the
        bar is now a raised slab with a groove under it (header_slab) and the
        title is struck in the rim's metal instead of the link colour. The
        link colour had to move off the title - it is the overlay's "you can
        click this", and spending it on eleven headings that are not clickable
        is what made the panels read as a wall of blue labels.

        ``right_from`` is the x a caller has already spent inside this same
        row - the comps window draws its badge chip there - and the right-hand
        text is FITTED into what is left of it rather than trusted to be
        short. The status is whatever the reader hands over, including
        "loading failed: <whatever python said>", so a layout that only works
        for the short ones is a layout that collides the first time something
        goes wrong. Base pixels on both sides (fit_text measures that way), so
        the clearance is the same at every UI scale.
        """
        header_slab(c, self.WIDTH)
        x = 14
        if dot is not None:
            # The status dot gets a dark socket so it reads as a lamp set into
            # the bar rather than a coloured pixel floating on it.
            c.create_oval(11, 9, 21, 19, fill=SHADE, outline="")
            c.create_oval(12, 10, 20, 18, fill=dot, outline="")
            x = 26
        c.create_text(x, 14, text=self.TITLE, anchor="w", fill=GOLD_TEXT,
                      font=F_BRAND)
        rx = self.WIDTH - 14
        if self.QUIT_BUTTON:
            c.create_text(self.WIDTH - 14, 13, text="✕", fill=DIM, font=F_STATUS)
            rx = self.WIDTH - 30
            # The way back to the settings panel. It has to hang off a window
            # that is always up, because every overlay window is click-through
            # except at these two hit boxes, so there is nowhere else on screen
            # a click can land. The panel's own close button hides it rather
            # than destroying it, and this brings the same one back.
            if getattr(self.app, "open_settings", None) is not None:
                c.create_text(self.WIDTH - 32, 13, text="⚙", fill=DIM, font=F_STATUS)
                rx = self.WIDTH - 48
        if right_text:
            if right_from is not None:
                right_text = fit_text(right_text, max(24, rx - right_from),
                                      F_SUB)
            c.create_text(rx, 14, text=right_text, anchor="e",
                          fill=right_fill, font=F_SUB)
        return HEADER_H + 4

    # -- timeouts ----------------------------------------------------------

    def _arm_timeout(self):
        if not self.TIMEOUT_MS or self.headless:
            return
        self._cancel_timeout()
        self._timer = self.after(self.TIMEOUT_MS, self.hide)

    def _cancel_timeout(self):
        if self._timer is not None:
            try:
                self.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    # -- geometry ----------------------------------------------------------

    def default_xy(self, rect):
        """Where this window sits when the user has never dragged it: down one
        edge of the game window, in its own reserved band, so no two windows
        cover each other.

        THE INVARIANT: every geometry in the tiling scales by the same factor.
        Band starts (DY), heights (MAX_H, applied in redraw) and margins are
        all base pixels multiplied by the one _scale, so the column tiles at
        2.0x exactly as it tiles at 1.0x - the registry's guarantee that
        DY + MAX_H never crosses the next band holds at every scale because
        both sides of that inequality are scaled together. When the scaled
        column is taller than the game window the excess runs off the BOTTOM
        edge and stays in band order. There used to be a clamp here that
        pulled an overflowing window back up to the bottom edge instead: that
        mixed an unscaled bound (the game rect) into scaled tiling math, and
        above ~1.4x on a 1080p window it stacked the left column onto itself -
        every overflowing window landed on the one above it. A window off the
        bottom edge is recovered by lowering the scale (the DISPLAY section
        names the automatic fit); a window on top of another is readable
        never.
        """
        margin = self._px(MARGIN_X)
        if self.COLUMN == "left":
            x = rect.left + margin
        else:
            x = rect.right - self._wpx() - margin
        return x, rect.top + self._px(self.DY)

    def _place(self):
        if self.headless or self._drag is not None:
            return
        rect = self.app.rect
        if rect is not None:
            bx, by = self.default_xy(rect)
            if (self.dx, self.dy) == (0, 0):
                # Never dragged: the default anchor, which is inside the game
                # window by construction (default_xy).
                x, y = bx, by
            else:
                # A saved drag offset is a SCREEN-pixel delta and is never
                # rescaled: rescaling it would round a little further off on
                # every scale change, and .overlay.json would slowly rot. What
                # moves when the scale changes is the anchor the offset hangs
                # off, so a panel dragged to the middle stays roughly in the
                # middle.
                #
                # The offset itself is honored WHEREVER it points: a window
                # deliberately parked outside the game rect - beside the game,
                # on a second monitor - is a position the user chose, and the
                # old clamp-to-game-rect here snapped it back on every start.
                # The one save worth overriding is one no monitor shows at all
                # (the screen it sat on was unplugged, the resolution shrank):
                # that alone is rescued to the default anchor.
                x, y = bx + self.dx, by + self.dy
                if not _on_any_screen(x, y, self._wpx(), self._h):
                    x, y = bx, by
            self._xy = (int(x), int(y))
        else:
            self._xy = self.free
        self.geometry(f"{self._wpx()}x{self._h}+{self._xy[0]}+{self._xy[1]}")

    def tick(self, rect, game_front):
        """Called by the manager every poll: re-anchor and re-apply visibility."""
        if self.headless:
            return
        if rect is not None and self._drag is None and self._open:
            self._place()
            if self.badges is not None:
                self.badges.reposition(rect)
        self._apply_visibility(game_front)

    def _apply_visibility(self, game_front=None):
        """Visible exactly when this window is open AND the game is in front.

        Self-healing on observed state, not on a flag we hope is still true.
        """
        if self.headless:
            return
        if game_front is None:
            game_front = self.app.game_front
        want = bool(self._open and game_front)
        if want and not self._mapped:
            self._mapped = True
            self.deiconify()
            self.lift()
            if self.badges is not None and self.badges.rows:
                self.badges.reposition(self.app.rect)
        elif not want and self._mapped:
            self._mapped = False
            self.withdraw()
            if self.badges is not None and not self.badges.calib:
                # A calibration strip is owned by the mode, not by this
                # window: badge_edit_poll hides it when the game is not in
                # front and brings it back when it is.
                self.badges.withdraw()
                self.badges.visible = False

    # -- drag --------------------------------------------------------------

    def _press(self, e):
        # Back into base pixels before anything looks at the coordinates: hit
        # boxes are recorded by draw(), which works in base pixels, so every
        # on_click in the package compares against unscaled numbers.
        ex, ey = e.x / _scale, e.y / _scale
        if self.QUIT_BUTTON and ey <= HEADER_H:
            if ex >= self.WIDTH - 28:
                self.app.quit()
                return
            opener = getattr(self.app, "open_settings", None)
            if opener is not None and ex >= self.WIDTH - 46:
                opener()
                return
        try:
            if self.on_click(ex, ey):
                return
        except Exception:
            self.errors += 1
            traceback.print_exc()
        self._drag = (e.x_root, e.y_root, self.winfo_x(), self.winfo_y())

    def _motion(self, e):
        if not self._drag:
            return
        ox, oy, wx, wy = self._drag
        self.geometry(f"+{wx + e.x_root - ox}+{wy + e.y_root - oy}")

    def _release(self, e):
        if not self._drag:
            return
        self._drag = None
        rect = self.app.rect
        if rect is not None:
            bx, by = self.default_xy(rect)
            self.dx, self.dy = self.winfo_x() - bx, self.winfo_y() - by
            self.app.pos.set(self.KEY, dx=self.dx, dy=self.dy)
        else:
            self.free = (self.winfo_x(), self.winfo_y())
            self.app.pos.set(self.KEY, x=self.free[0], y=self.free[1])

    # -- badges ------------------------------------------------------------

    def badges_show(self, rows, min_sample=0):
        if self.badges is not None and self.app.rect is not None:
            self.badges.show(rows, self.app.rect, min_sample)

    def badges_hide(self):
        if self.badges is not None:
            self.badges.hide()

    # -- diagnostics -------------------------------------------------------

    def heartbeat(self):
        state = "open" if self._open else "-"
        if self._open and not self._mapped and not self.headless:
            state = "open(hidden)"
        return f"{self.KEY}={state}"


class WindowManager:
    """Owns the Tk root, every window, the anchor poll and the heartbeat.

    The manager knows nothing about Battlegrounds. It answers two questions
    for all windows at once - where is the game, and is it in front - so nine
    windows do not each hammer the Win32 API.
    """

    POLL_MS = 700

    def __init__(self, classes, headless=False, pos_file=POS_FILE, names_fn=None):
        self.headless = headless
        # Tk() reads init.tcl off disk and that read transiently fails on
        # Windows under interp churn ("couldn't read file ... No error") -
        # measured live at roughly 1-in-4 across a test battery, and a real
        # launch on a busy machine rolls the same dice. Three tries covers it;
        # a machine that fails all three has a broken Tcl install and the
        # original error is the right report.
        for attempt in (1, 2, 3):
            try:
                self.root = tk.Tk()
                break
            except tk.TclError:
                if attempt == 3:
                    raise
                time.sleep(0.3)
        self.root.withdraw()
        # The taskbar/alt-tab face for every window this root owns. Guarded
        # like the rest of the skin: no folder, no icon, no error.
        try:
            ico = skin.icon(self.root)
            if ico is not None:
                self.root.iconphoto(True, ico)
        except Exception:
            pass
        self.pos = PosStore(pos_file)
        # Every window draws card art through this one cache (built before the
        # windows, because they reach for app.art inside their first redraw).
        self.art = ArtCache(names_fn)
        self.rect = None
        self.game_front = bool(headless)   # headless: never hide on focus
        self.on_quit = None
        self.open_settings = None    # set by whoever owns the settings panel;
                                     # a header ⚙ appears only once it is set
        self.extra_hwnds = []        # windows that are ours but not in the
                                     # registry - see _our_ids
        self.on_windows_changed = None    # the router has to be rebuilt
        self.windows = [cls(self) for cls in classes]
        self.by_key = {w.KEY: w for w in self.windows}
        self._tick = 0

    # -- the registry, live -----------------------------------------------

    def enable(self, cls):
        """Build a window that was switched off, without a restart.

        Returns the window, or the existing one if it is already up. Whoever
        holds a Router must rebuild it afterwards, which ``on_windows_changed``
        asks for: the router indexes windows by event at construction, so a
        window added behind its back would simply never be dispatched to.
        """
        w = self.by_key.get(cls.KEY)
        if w is not None:
            return w
        w = cls(self)
        self.windows.append(w)
        self.by_key[w.KEY] = w
        if self.on_windows_changed is not None:
            self.on_windows_changed()
        return w

    def disable(self, key):
        """Destroy a window and its badge strip. Returns True if one went.

        Destroying rather than hiding is the point: a hidden window still eats
        its events, still holds a strip in the priority list that can hide
        somebody else's badges, and still repaints. "Off" has to mean the same
        thing it means at startup - the class is never built.
        """
        w = self.by_key.pop(key, None)
        if w is None:
            return False
        self.windows.remove(w)
        try:
            if w.badges is not None:
                if w.badges in _STRIPS:
                    _STRIPS.remove(w.badges)
                w.badges.destroy()
            w.destroy()
        except Exception:
            traceback.print_exc()
        # The strip that just died may have been the arbiter holding others
        # down - same job as after a strip hides, so it is the same helper.
        if not self.headless and self.game_front:
            revive_strips(self.rect or hs_rect())
        if self.on_windows_changed is not None:
            self.on_windows_changed()
        return True

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if not self.headless:
            self.root.after(400, self._poll)

    def quit(self):
        if self.on_quit is not None:
            try:
                self.on_quit()
            except Exception:
                traceback.print_exc()
        try:
            self.root.destroy()
        except Exception:
            pass

    def reset_all(self):
        for w in self.windows:
            try:
                w.reset()
            except Exception:
                traceback.print_exc()

    # -- polling -----------------------------------------------------------

    def _our_ids(self):
        ids = set()
        for w in self.windows:
            for wnd in (w, w.badges):
                if wnd is None:
                    continue
                try:
                    wid = wnd.winfo_id()
                    ids.add(wid)
                    ids.add(ctypes.windll.user32.GetParent(wid))
                except Exception:
                    pass
        # The settings panel is ours too, and it is the one window here that
        # TAKES focus. Without it in this set, opening the panel reads as the
        # game losing focus and the whole overlay withdraws - which would hide
        # the very thing the scale sliders are there to let you watch. (Same
        # bug the comps window had before it was added to the allow-set.)
        for hwnd in list(self.extra_hwnds):
            try:
                ids.add(hwnd)
                ids.add(ctypes.windll.user32.GetParent(hwnd))
            except Exception:
                pass
        return ids

    def _poll(self):
        self.rect = hs_rect()
        u = ctypes.windll.user32
        fg = u.GetForegroundWindow()
        hs = (u.FindWindowW("UnityWndClass", "Hearthstone")
              or u.FindWindowW(None, "Hearthstone"))
        # Clicking one of OUR windows must not read as the game losing focus,
        # or the whole overlay would vanish while you drag it.
        self.game_front = bool((hs and fg == hs) or fg in self._our_ids())
        for w in self.windows:
            try:
                w.tick(self.rect, self.game_front)
            except Exception:
                traceback.print_exc()
        badge_edit_poll(self.rect, self.game_front)
        self._tick += 1
        if self._tick % 6 == 0:      # heartbeat for post-mortems, ~4s apart
            print("hb " + " ".join(w.heartbeat() for w in self.windows)
                  + f" front={self.game_front} anchored={self.rect is not None}",
                  flush=True)
        self.root.after(self.POLL_MS, self._poll)
