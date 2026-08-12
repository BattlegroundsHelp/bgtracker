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
import tkinter as tk
import traceback
import weakref
from ctypes import wintypes
from pathlib import Path
from tkinter import font as tkfont

from paths import APP_DIR

try:  # crisp text on scaled displays
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

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
PANEL = "#14161c"
PANEL_HI = "#1c1f27"
LINE = "#262a33"
TEXT = "#e9e7e2"
SOFT = "#b9b6b0"
DIM = "#7c818c"
ACCENT = "#4aa3e2"
AMBER = "#e0b45c"
GOOD = "#6fd693"
BAD = "#e07a5f"

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
    # Discover / Choose-One cards are centred on the game window.
    "choice": {n: [0.5 + (i - (n - 1) / 2) * 0.165 for i in range(n)]
               for n in range(2, 5)},
}
BAND_Y = {"hero": 0.235, "trinket": 0.775, "shop": 0.305, "choice": 0.63}


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


def shadow_text(c, cx, cy, text, fill, font, anchor="center"):
    """Text with a dark halo so it reads over any card art - no backdrop box.

    The halo is offset by whole pixels, so it has to grow with the text or a
    doubled badge would wear a one-pixel outline that reads as a blur instead
    of a shadow. One pixel at scale 1.0, unchanged.
    """
    o = max(1, int(round(getattr(font, "ratio", 1.0))))
    for dx, dy in ((-o, -o), (o, -o), (-o, o), (o, o), (0, 0)):
        col = "#0a0b0e" if (dx or dy) else fill
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
        if is_best:
            rrect(c, 8, y + 1, width - 8, y + 45, 9, fill=PANEL_HI, outline="")
            c.create_rectangle(8, y + 8, 11, y + 38, fill=avg_color(shown), outline="")
        ic = art.icon(r.get("card"), 30) or art.icon_for_name(r["name"], 30)
        tx = 20
        if ic is not None:
            c.create_image(18, y + 22, image=ic, anchor="w")
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
        if shown is not None:
            col = avg_color(shown)
            c.create_text(width - 18, y + 16, text=f"{shown:.2f}", anchor="e",
                          fill=col, font=F_BIG)
            if r.get("adj") is not None and r.get("avg") is not None:
                d = r["adj"] - r["avg"]
                c.create_text(width - 18, y + 32, text=f"{d:+.2f} here", anchor="e",
                              fill=col if d < 0 else DIM, font=F_DELTA)
            if not tip:
                frac = max(0.10, min(1.0, (5.2 - shown) / 2.2))
                c.create_rectangle(20, y + 41, width - 98, y + 43, fill=LINE, outline="")
                c.create_rectangle(20, y + 41, 20 + (width - 118) * frac, y + 43,
                                   fill=col, outline="")
        else:
            c.create_text(width - 18, y + 16, text="—", anchor="e",
                          fill=DIM, font=F_BIG)
        if tip:
            c.create_text(tx, y + 41, text=fit_text(tip, width - tx - 18),
                          anchor="w", fill=SOFT, font=F_SUB)
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


def hs_rect():
    """The Hearthstone window rectangle, or None when it isn't on screen."""
    u = ctypes.windll.user32
    hwnd = (u.FindWindowW("UnityWndClass", "Hearthstone")
            or u.FindWindowW(None, "Hearthstone"))
    if not hwnd or not u.IsWindowVisible(hwnd):
        return None
    r = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    if r.right - r.left < 300:      # minimised
        return None
    return r


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

    def get(self, key):
        v = self.win.get(key)
        return v if isinstance(v, dict) else {}

    def set(self, key, **kw):
        self.win.setdefault(key, {}).update(kw)
        try:
            self.path.write_text(json.dumps(self.data))
        except Exception:
            pass


# -------------------------------------------------------------- badge strips

_STRIPS: list["BadgeStrip"] = []


class BadgeStrip(tk.Toplevel):
    """A click-through, fully transparent band over the Hearthstone window,
    drawing one badge under (or over) each offered card - the number attached
    to the character it belongs to, not a list in a corner.

    Strips arbitrate by PRIORITY instead of by a shared mode: showing a strip
    hides every visible strip of lower priority. That is how the tavern stars
    get out of the way when a discover opens, without either window knowing
    the other exists.
    """

    def __init__(self, master, kind, priority=0):
        super().__init__(master)
        self.kind, self.priority = kind, priority
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
        self.withdraw()
        _STRIPS.append(self)
        self.after(120, self.clickthrough)

    def clickthrough(self):
        """Let clicks pass through to the game underneath."""
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
            hwnd = u.GetParent(self.winfo_id()) or self.winfo_id()
            style = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE,
                                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
        except Exception:
            pass    # worst case the badges eat clicks in their own band

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
        if min_sample is not None:
            self.min_sample = min_sample
        min_sample = self.min_sample
        self.rows, self.rect = rows, rect
        for s in _STRIPS:
            if s is not self and s.visible and s.priority < self.priority:
                try:
                    # Suppressed, not hidden: the rows stay, so the strip can
                    # come back if this one goes away (WindowManager.disable).
                    s.suppress()
                except Exception:
                    s.visible = False      # already destroyed; drop the claim
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
        y0 = rect.top + int(gh * BAND_Y.get(self.kind, 0.7))

        c = self.canvas
        c.delete("all")
        self.geometry(f"{gw}x{band_h}+{rect.left}+{y0}")
        c.config(width=gw, height=band_h)

        def score(r):
            return r.get("adj") if r.get("adj") is not None else r.get("avg")

        scored = [r for r in rows
                  if score(r) is not None and r.get("n", 0) >= min_sample]
        best = min(scored, key=score, default=None)
        for r, fx in zip(rows, xs):
            cx = int(gw * fx)
            shown = score(r)
            col = avg_color(shown)
            if r.get("stars") is not None:
                s = r.get("stars", 0)
                shadow_text(c, cx, b(12), "★" * s, STAR_COLOR.get(s, DIM),
                            F_BADGE_STARS)
                if r.get("mine"):
                    shadow_text(c, cx, b(28), "▶ your build", ACCENT, F_BADGE_CHIP)
                elif r.get("comp"):
                    shadow_text(c, cx, b(28), r["comp"][:14], SOFT, F_BADGE_CHIP)
            elif shown is None:
                shadow_text(c, cx, b(14), "—", DIM, F_BADGE_NAME)
            else:
                shadow_text(c, cx, b(13), f"{shown:.2f}", col,
                            F_BADGE_BIG if r is best else F_BADGE_NAME)
                if r is best:
                    shadow_text(c, cx, b(30), "best", col, F_BADGE_CHIP)
                elif r.get("pick") is not None:
                    shadow_text(c, cx, b(29), f"{r['pick']:.0f}%", DIM, F_BADGE_CHIP)
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
        self.clickthrough()

    def reposition(self, rect):
        """The game window moved: redraw in place, keeping the same rows (and
        the same min_sample - show() keeps the stored one when none is
        passed)."""
        if self.visible and self.rows:
            self.show(self.rows, rect)

    def suppress(self):
        """Outranked by a higher-priority strip: off screen, but the rows and
        the threshold are KEPT so this strip can be revived if the winner is
        destroyed mid-offer (WindowManager.disable does exactly that).
        ``hide()`` is the owning window saying "these rows are done" - this is
        the arbiter saying "not right now"."""
        self.visible = False
        self.withdraw()

    def hide(self):
        self.visible = False
        self.rows = []
        self.min_sample = 0
        self.withdraw()


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

        if self.BADGE_KIND and not self.headless:
            self.badges = BadgeStrip(self, self.BADGE_KIND, self.BADGE_PRIORITY)
        _LIVE.add(self)

    # -------------------------------------------------------------- scaling

    @staticmethod
    def _px(v):
        """A base-pixel number as the screen pixels it becomes."""
        return int(round(v * _scale))

    def _wpx(self):
        return self._px(self.WIDTH)

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
        h = max(40, min(h, self.MAX_H))
        bg = rrect(c, 0, 0, self.WIDTH, h, RADIUS, fill=PANEL, outline=LINE)
        c.tag_lower(bg)
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

    def header(self, c, right_text=None, right_fill=DIM, dot=None):
        """The 24px title bar every window shares. Returns the body's top y."""
        x = 14
        if dot is not None:
            c.create_oval(12, 10, 20, 18, fill=dot, outline="")
            x = 26
        c.create_text(x, 14, text=self.TITLE, anchor="w", fill=ACCENT, font=F_BRAND)
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
            if self.badges is not None:
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
        self.root = tk.Tk()
        self.root.withdraw()
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
        # down: showing a strip SUPPRESSES every lower-priority one (rows
        # kept, see BadgeStrip.suppress), and nothing else would bring the
        # victims back before their next event - for the tavern stars that is
        # the next roll, a whole shop away. So whatever still holds rows and
        # is no longer outranked is re-shown here, highest priority first
        # (show() re-suppresses anything below whatever comes back on top).
        if not self.headless and self.game_front:
            rect = self.rect or hs_rect()
            if rect is not None:
                for s in sorted(_STRIPS, key=lambda s: -s.priority):
                    if not s.rows or s.visible:
                        continue
                    if any(o.visible and o.priority > s.priority for o in _STRIPS):
                        continue
                    try:
                        s.show(s.rows, rect)
                    except Exception:
                        traceback.print_exc()
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
        self._tick += 1
        if self._tick % 6 == 0:      # heartbeat for post-mortems, ~4s apart
            print("hb " + " ".join(w.heartbeat() for w in self.windows)
                  + f" front={self.game_front} anchored={self.rect is not None}",
                  flush=True)
        self.root.after(self.POLL_MS, self._poll)
