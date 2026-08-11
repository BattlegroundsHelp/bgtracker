"""COMPS window - the reference surface: what this lobby can build, the
minions each build actually runs, and what your own board is leaning into.

This is the only window that stays up the whole session. It never reacts to a
fight, a shop or a pick - it answers one slow question ("what am I building
towards?") and it is also where the overlay's own status and quit button live.

Blank-safe by construction: with no stats source at all, ``comp_table`` falls
back to the CURATED families (baseline=True, avg=None, n=0), whose core
minions are computed from the live card pool. Those rows are labelled
"curated" and show a dot instead of a placement - never a made-up average.

Click a row to open it and see the actual cards to look for; click the link in
the header to switch between the best build per tribe and every build this
lobby can make.
"""

from __future__ import annotations

import bgtracker as bg

from .base import (ACCENT, AMBER, DIM, F_CHIP, F_NAME, F_STATUS, F_SUB, F_TITLE,
                   GOOD, LINE, PANEL, SOFT, TEXT, TRIBE_COLOR, TRIBE_TAG,
                   BaseWindow, avg_color, rrect)

# Comps need a real sample before they deserve a row: right after a patch the
# feed still lists last season's archetypes with frozen averages on tiny n.
COMP_MIN = 300


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
                for nm in (comp.get("key_wide") or [])[:8]:
                    ic = self.app.art.icon_for_name(nm, 18)
                    if ic is not None:
                        c.create_image(76, y + 9, image=ic, anchor="w")
                    c.create_text(98, y + 9, text=nm[:24], anchor="w",
                                  fill=SOFT, font=F_SUB)
                    share = freq.get(nm)
                    if share:
                        c.create_text(self.WIDTH - 14, y + 9,
                                      text=f"{share * 100:.0f}%", anchor="e",
                                      fill=DIM, font=F_SUB)
                    y += 20
                y += 4
            else:
                if comp.get("key"):
                    line = " · ".join(comp["key"][:3])
                    if len(line) > 46:
                        line = line[:45] + "…"
                    c.create_text(66, y + 26, text=line, anchor="w",
                                  fill=DIM, font=F_SUB)
                y += 38
            self._hits.append((comp["archetype"], top, y))
        return y + 8
