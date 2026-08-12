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
"""

from __future__ import annotations

import ctypes
import json
import sys
import tkinter as tk
import traceback
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

F_BRAND = ("Segoe UI Semibold", 9)
F_STATUS = ("Segoe UI", 8)
F_TITLE = ("Segoe UI Semibold", 9)
F_NAME = ("Segoe UI Semibold", 10)
F_BIG = ("Segoe UI Semibold", 14)
F_HUGE = ("Segoe UI Semibold", 17)
F_DELTA = ("Segoe UI Semibold", 8)
F_SUB = ("Segoe UI", 8)
F_CHIP = ("Segoe UI Semibold", 7)

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
    """Text with a dark halo so it reads over any card art - no backdrop box."""
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)):
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
    """
    text = " ".join((text or "").split())
    if not text:
        return ""
    try:
        # A Font belongs to ONE interpreter: keeping it past its root's destroy
        # raises "application has been destroyed" on the next measure. The test
        # harness builds and destroys a manager per log, so the cache is keyed
        # by the live root and a dead one simply never matches.
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
        if not _PIL or not card_id:
            return None
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

    def show(self, rows, rect, min_sample=0):
        """Draw one badge per row. Rows carry either stars (shop/discover) or
        an avg/adj placement (hero/trinket); both shapes are read defensively."""
        if rect is None or not rows:
            return
        self.rows, self.rect = rows, rect
        for s in _STRIPS:
            if s is not self and s.visible and s.priority < self.priority:
                try:
                    s.hide()
                except Exception:
                    s.visible = False      # already destroyed; drop the claim
        rows = sorted(rows, key=lambda r: r.get("pos") or 0)
        n = len(rows)
        xs = (SLOT_X.get(self.kind, {}).get(n)
              or [0.5 + (i - (n - 1) / 2) * 0.135 for i in range(n)])
        gw = rect.right - rect.left
        gh = rect.bottom - rect.top
        band_h = 40
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
                shadow_text(c, cx, 12, "★" * s, STAR_COLOR.get(s, DIM),
                            ("Segoe UI", 11))
                if r.get("mine"):
                    shadow_text(c, cx, 28, "▶ your build", ACCENT, F_CHIP)
                elif r.get("comp"):
                    shadow_text(c, cx, 28, r["comp"][:14], SOFT, F_CHIP)
            elif shown is None:
                shadow_text(c, cx, 14, "—", DIM, F_NAME)
            else:
                shadow_text(c, cx, 13, f"{shown:.2f}", col,
                            F_BIG if r is best else F_NAME)
                if r is best:
                    shadow_text(c, cx, 30, "best", col, F_CHIP)
                elif r.get("pick") is not None:
                    shadow_text(c, cx, 29, f"{r['pick']:.0f}%", DIM, F_CHIP)
        self.visible = True
        self.deiconify()
        self.lift()

    def reposition(self, rect):
        """The game window moved: redraw in place, keeping the same rows."""
        if self.visible and self.rows:
            self.show(self.rows, rect)

    def hide(self):
        self.visible = False
        self.rows = []
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
        self._h = 80
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
        self.geometry(f"{self.WIDTH}x{self._h}+{self.free[0]}+{self.free[1]}")
        self.canvas = tk.Canvas(self, bg=TRANS, highlightthickness=0, bd=0,
                                width=self.WIDTH, height=self._h)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.withdraw()

        if self.BADGE_KIND and not self.headless:
            self.badges = BadgeStrip(self, self.BADGE_KIND, self.BADGE_PRIORITY)

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
        self._draws += 1
        if self.headless or not self._open:
            return
        c = self.canvas
        c.delete("all")
        h = int(self.draw(c) or 80)
        h = max(40, min(h, self.MAX_H))
        bg = rrect(c, 0, 0, self.WIDTH, h, RADIUS, fill=PANEL, outline=LINE)
        c.tag_lower(bg)
        if h != self._h:
            self._h = h
            c.config(width=self.WIDTH, height=h)
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
        cover each other."""
        if self.COLUMN == "left":
            x = rect.left + MARGIN_X
        else:
            x = rect.right - self.WIDTH - MARGIN_X
        y = rect.top + self.DY
        bottom = rect.bottom - 8
        if y + self._h > bottom:
            y = max(rect.top + 8, bottom - self._h)
        return x, y

    def _place(self):
        if self.headless or self._drag is not None:
            return
        rect = self.app.rect
        if rect is not None:
            bx, by = self.default_xy(rect)
            self._xy = (bx + self.dx, by + self.dy)
        else:
            self._xy = self.free
        self.geometry(f"{self.WIDTH}x{self._h}+{self._xy[0]}+{self._xy[1]}")

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
        if self.QUIT_BUTTON and e.y <= HEADER_H and e.x >= self.WIDTH - 28:
            self.app.quit()
            return
        try:
            if self.on_click(e.x, e.y):
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
        self.windows = [cls(self) for cls in classes]
        self.by_key = {w.KEY: w for w in self.windows}
        self._tick = 0

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
