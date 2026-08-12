"""COMPS window - the reference surface: what this lobby can build, the
minions each build actually runs, and what your own board is leaning into.

This is the only window that stays up the whole session. It never reacts to a
fight, a shop or a pick - it answers one slow question ("what am I building
towards?") and it is also where the overlay's own status and quit button live.

Blank-safe by construction: with no stats source at all, ``comp_table`` falls
back to the CURATED families (baseline=True, avg=None, n=0), whose core
minions are computed from the live card pool. Those rows are labelled
"curated" and show a dot instead of a placement - never a made-up average.

Click a row to open it and see the actual cards to look for, split into the
CORE the build cannot run without (filled marker) and the ADD-ONS that finish
it, with a computed difficulty word beside the measured inputs behind it
(bgtracker.comp_role_split / comp_difficulty - both paths, stats and curated,
get the same split because it is judged off the cards themselves). A comp no
roles entry covers keeps the flat list this window always drew. Click the
link in the header to switch between the best build per tribe and every build
this lobby can make.
"""

from __future__ import annotations

import threading
import tkinter as tk

import bgtracker as bg

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_NAME, F_STATUS, F_SUB,
                   F_TITLE, GOOD, LINE, PANEL, SOFT, TEXT, TRIBE_COLOR,
                   TRIBE_TAG, BaseWindow, avg_color, rrect)

# Difficulty word color: reads like the placement colors do - green is
# comfortable, red is a commitment.
DIFF_COLOR = {"easy": GOOD, "medium": AMBER, "hard": BAD}

# Comps need a real sample before they deserve a row: right after a patch the
# feed still lists last season's archetypes with frozen averages on tiny n.
COMP_MIN = 300

# ---------------------------------------------------------------- role warmup
#
# comp_role_split / comp_difficulty read the card pool, and a cold or expired
# pool cache means bgtracker.bg_pool() does a BLOCKING network fetch - on the
# Tk thread, where draw() runs, that freezes every window for as long as the
# socket takes (and draw() runs on every roll). The pool only changes on patch
# day, so it is warmed ONCE, on its own daemon thread: the pool by name, the
# roles file, and every family's difficulty, which fills bgtracker's own
# per-family cache. After that a draw-path call is dict lookups and regex -
# no I/O. Until the warmup has succeeded the wrappers answer None, which is a
# state the window already renders honestly (the flat list, no difficulty
# word) - a briefly plainer panel beats a frozen overlay. A failed warmup
# (offline, no cache) is retried on the next lobby event, never on the draw
# path.

_warm = {"thread": None, "ok": False}
_warm_lock = threading.Lock()


def _warm_roles():
    try:
        bg.pool_by_name()                      # the one call that can fetch
        for arch, entry in bg.comp_roles().items():
            bg.comp_difficulty(arch, entry["tribes"][0] if entry["tribes"]
                               else None)
        _warm["ok"] = True
    except Exception:
        pass                                   # stay cold; a lobby event retries


def warm_comp_roles(wait=False):
    """Start (or join) the one warmup thread. Cheap and re-callable: once the
    warmup has succeeded this returns immediately forever."""
    with _warm_lock:
        t = _warm["thread"]
        if not _warm["ok"] and (t is None or not t.is_alive()):
            t = threading.Thread(target=_warm_roles, name="comp-roles-warm",
                                 daemon=True)
            _warm["thread"] = t
            t.start()
    if wait and t is not None:
        t.join()
    return t


def _role_split(comp):
    """comp_role_split, gated so the Tk thread can never be the one fetching."""
    if not _warm["ok"]:
        return None
    try:
        return bg.comp_role_split(comp)
    except Exception:
        return None


def _difficulty(archetype, tribe):
    """comp_difficulty behind the same gate as _role_split."""
    if not _warm["ok"]:
        return None
    try:
        return bg.comp_difficulty(archetype, tribe)
    except Exception:
        return None


class CompsWindow(BaseWindow):
    KEY = "comps"
    TITLE = "bgtracker"
    COLUMN = "right"
    DY = 396
    RESERVE = 330
    MAX_H = 620
    EVENTS = ("lobby", "board", "status", "game")
    QUIT_BUTTON = True

    def __init__(self, app):
        super().__init__(app)
        self.tribes, self.exact = set(), False
        self.comps, self.all_comps = [], []
        self.board = None
        self.status = "loading"
        self.open_key = None       # archetype expanded inline
        self.show_all = False
        self._hits = []            # [(archetype|"__all__", y1, y2)] for clicks
        # Kick the role warmup off the draw path now, and repaint once when it
        # lands so the split appears without waiting for the next event.
        warm_comp_roles()
        self._warm_poll()

    def _warm_poll(self):
        try:
            if _warm["ok"]:
                if self._open:
                    self.redraw()
                return
            t = _warm["thread"]
            if t is not None and t.is_alive():
                self.after(400, self._warm_poll)
            # else: the warmup failed (offline, no cache); the next lobby
            # event retries it and re-arms this poll. No timer runs while
            # nothing can change.
        except tk.TclError:
            pass                     # the window was destroyed under the timer

    def reset(self):
        self.tribes, self.exact = set(), False
        self.comps, self.board = [], None
        self.open_key = None
        self.redraw()

    def on_event(self, name, payload):
        if name == "lobby":
            self.tribes = payload.get("seen") or set()
            self.exact = payload.get("exact", False)
            self.comps = payload.get("comps") or []
            if payload.get("all"):
                self.all_comps = payload["all"]
            if not _warm["ok"]:
                # A failed warmup gets its retry here - an event, never a
                # draw - and the poll repaints when the retry lands.
                warm_comp_roles()
                self._warm_poll()
        elif name == "board":
            self.board = payload
        elif name == "status":
            self.status = payload
        elif name == "game":
            self.reset()
            return
        self.show()

    # ------------------------------------------------------------- clicking

    def on_click(self, x, y):
        for key, y1, y2 in self._hits:
            if y1 <= y <= y2:
                if key == "__all__":
                    self.show_all = not self.show_all
                else:
                    self.open_key = None if self.open_key == key else key
                self.redraw()
                return True
        return False

    def _rows(self):
        if self.show_all:
            rows = [c for c in (self.all_comps or self.comps)
                    if c["tribe"] is None or c["tribe"] in self.tribes]
            rows.sort(key=lambda x: bg.comp_sort_key(x, COMP_MIN))
            return rows
        return self.comps

    # -------------------------------------------------------------- drawing

    def draw(self, c):
        dot = GOOD if self.exact else (AMBER if self.tribes else DIM)
        y = self.header(c, self.status, DIM, dot=dot)
        self._hits = []

        # tribe chips ------------------------------------------------------
        x = 12.0
        for t in bg.TRIBES:
            on = t in self.tribes
            col = TRIBE_COLOR[t]
            if on:
                rrect(c, x, y, x + 27, y + 15, 7, fill=col, outline="")
                c.create_text(x + 13.5, y + 8, text=TRIBE_TAG[t],
                              fill="#101116", font=F_CHIP)
            else:
                rrect(c, x, y, x + 27, y + 15, 7, fill=PANEL, outline=LINE)
                c.create_text(x + 13.5, y + 8, text=TRIBE_TAG[t],
                              fill="#4a4f59", font=F_CHIP)
            x += 29.5
        y += 24

        # your board -------------------------------------------------------
        b = self.board
        if b and b.get("size"):
            c.create_text(14, y + 7, text=f"YOUR BOARD ({b['size']})", anchor="w",
                          fill=DIM, font=F_TITLE)
            if b.get("lean"):
                c.create_text(self.WIDTH - 14, y + 7, anchor="e", fill=ACCENT,
                              font=F_SUB,
                              text=f"▶ {b['lean']}  {b['hits']}/{b['size']}")
            else:
                c.create_text(self.WIDTH - 14, y + 7, text="no comp match yet",
                              anchor="e", fill=DIM, font=F_SUB)
            y += 20

        # comps ------------------------------------------------------------
        rows = self._rows()
        if not rows:
            c.create_text(14, y + 10, text="waiting for a game", anchor="w",
                          fill=DIM, font=F_STATUS)
            return y + 28

        label = "COMPS IN THIS LOBBY" if self.exact else "COMPS SEEN SO FAR"
        c.create_text(14, y + 7, text=label, anchor="w", fill=DIM, font=F_TITLE)
        c.create_text(self.WIDTH - 14, y + 7, anchor="e", fill=ACCENT, font=F_SUB,
                      text="best per tribe ›" if self.show_all else "all ›")
        self._hits.append(("__all__", y, y + 14))
        y += 18

        for comp in rows:
            base = comp.get("baseline")
            thin = (not base) and comp["n"] < COMP_MIN
            name = comp["archetype"].replace("_", " ")
            col = DIM if (thin or base) else avg_color(comp["avg"])
            opened = self.open_key == comp["archetype"]
            is_lean = bool(self.board and self.board.get("lean")
                           and str(self.board["lean"]).startswith(name))
            top = y
            c.create_text(14, y + 10, anchor="w", fill=col, font=F_NAME,
                          text="·" if base else f"{comp['avg']:.2f}")
            c.create_oval(52, y + 6, 60, y + 14,
                          fill=TRIBE_COLOR.get(comp["tribe"], DIM), outline="")
            tag = name + (" · curated" if base else " · thin data" if thin else "")
            c.create_text(66, y + 10, text=("▶ " if is_lean else "") + tag,
                          anchor="w", font=F_NAME,
                          fill=ACCENT if is_lean else (DIM if thin else TEXT))
            c.create_text(self.WIDTH - 14, y + 10, text="▾" if opened else "▸",
                          anchor="e", fill=DIM, font=F_SUB)
            if opened:
                y += 22
                freq = comp.get("freq") or {}
                split = _role_split(comp)     # gated: never fetches on draw
                if split is None:
                    # No roles entry covers this comp (or nothing in its list
                    # proved core): the flat list, exactly as before.
                    for nm in (comp.get("key_wide") or [])[:8]:
                        y = self._minion(c, y, nm, freq)
                else:
                    diff = split["difficulty"]
                    if diff:
                        # The plain word plus the measured inputs behind it,
                        # so a player who disagrees with the label still sees
                        # the facts (comp_difficulty documents the bands).
                        c.create_text(66, y + 6, text="difficulty", anchor="w",
                                      fill=DIM, font=F_SUB)
                        c.create_text(68 + F_SUB.measure("difficulty "), y + 6,
                                      text=diff["word"], anchor="w",
                                      fill=DIFF_COLOR[diff["word"]], font=F_SUB)
                        c.create_text(self.WIDTH - 14, y + 6, anchor="e",
                                      fill=DIM, font=F_SUB,
                                      text=f"core ~t{diff['tier']:.1f} · "
                                           f"{diff['pieces']} in pool")
                        y += 16
                    # Eight minion rows fit the band, same budget as the flat
                    # list. Core comes first, but add-ons keep at least two
                    # rows when they exist - a split you can only see one half
                    # of is no split at all.
                    core = split["core"][:6 if split["addons"] else 8]
                    addons = split["addons"][:8 - len(core)]
                    c.create_text(66, y + 5, text="CORE", anchor="w",
                                  fill=DIM, font=F_CHIP)
                    y += 13
                    for nm in core:
                        y = self._minion(c, y, nm, freq, mark="●",
                                         mark_fill=AMBER)
                    if addons:
                        c.create_text(66, y + 5, text="ADD-ONS", anchor="w",
                                      fill=DIM, font=F_CHIP)
                        y += 13
                        # A hollow marker = the family's addon role vouches
                        # for the card; no marker = it merely shows up on
                        # winning boards. Both stay visible.
                        for nm, proven in addons:
                            y = self._minion(c, y, nm, freq,
                                             mark="○" if proven else None)
                y += 4
            else:
                if comp.get("key"):
                    diff = _difficulty(comp["archetype"], comp["tribe"])
                    line = " · ".join(comp["key"][:3])
                    if diff:
                        # The word and the core tier at a glance; the minion
                        # line gives up the width the tag needs (the full line
                        # budget is 46 characters).
                        if len(line) > 30:
                            line = line[:29] + "…"
                        c.create_text(self.WIDTH - 14, y + 26, anchor="e",
                                      fill=DIFF_COLOR[diff["word"]], font=F_SUB,
                                      text=f"{diff['word']} · t{round(diff['tier'])}")
                    elif len(line) > 46:
                        line = line[:45] + "…"
                    c.create_text(66, y + 26, text=line, anchor="w",
                                  fill=DIM, font=F_SUB)
                y += 38
            self._hits.append((comp["archetype"], top, y))
        return y + 8

    def _minion(self, c, y, name, freq, mark=None, mark_fill=DIM):
        """One minion line of an opened comp: optional role marker, icon,
        name, and how often it appears on this comp's real winning boards
        (stats path only; curated rows carry no frequencies and invent
        none)."""
        if mark:
            c.create_text(68, y + 9, text=mark, fill=mark_fill, font=F_SUB)
        ic = self.app.art.icon_for_name(name, 18)
        if ic is not None:
            c.create_image(76, y + 9, image=ic, anchor="w")
        c.create_text(98, y + 9, text=name[:24], anchor="w",
                      fill=SOFT, font=F_SUB)
        share = freq.get(name)
        if share:
            c.create_text(self.WIDTH - 14, y + 9, text=f"{share * 100:.0f}%",
                          anchor="e", fill=DIM, font=F_SUB)
        return y + 20
