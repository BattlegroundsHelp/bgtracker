"""MINION BROWSER window - the whole Battlegrounds pool, on demand.

The other windows answer "what is in front of me right now". This one answers
the slow question a player asks between fights: *what exists*? It browses the
entire current minion pool from ``bgtracker.bg_pool()`` - the live
HearthstoneJSON card data, so it is always this patch's pool and nobody's
hand-written list - filtered by TAVERN TIER, TRIBE and TRAIT (mechanic), with
the real card art next to every name.

Three rules it exists to keep:

1. **It opens on a click, not a key.** The overlay has no keyboard hook (the
   badge strips are click-through, the game owns the keyboard), so the window
   is always on screen as a slim one-line bar with a ``browse`` button in its
   own title row. Clicking that button expands it into the full browser and
   clicking it again collapses it. Nothing else can open or close it.
2. **It starts where the player is.** The default tribe filter is the tribes
   actually in THIS lobby (the ``lobby`` event), plus the tribeless minions,
   which are in every lobby. Touching a tribe chip hands control to the
   player; the ``lobby`` chip gives it back. The header dot says whether the
   lobby is exact (memory read) or only what has been seen so far.
3. **No stats, no numbers.** Ratings come from a configured card table only.
   With none - which is the default, since the stats feed is bring-your-own -
   the browser still browses: names, tiers, tribes, traits and card text, and
   the footer says plainly that there is no stats source. A minion inside a
   configured table that has no row of its own shows a dash, never a guess.

Ratings, when there IS a table, use the same scale as the tavern stars: the
buy-it-vs-skip-it DIFFERENTIAL (averagePlacement - averagePlacementOther)
banded inside the minion's OWN tavern tier. Raw averages rate an entire
seven-tier pool five stars, because they measure who buys a card rather than
whether it helps.

Drag it by the title row; the body is all controls.
"""

from __future__ import annotations

import re
import textwrap
import threading

import bgtracker as bg

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_SUB, F_TITLE, GOOD, LINE,
                   PANEL, PANEL_HI, SOFT, STAR_COLOR, TEXT, TRIBE_COLOR,
                   TRIBE_TAG, BaseWindow, rrect)

# A minion with no tribe at all is in EVERY lobby, so it is a filter of its
# own rather than something the tribe chips can express.
NEUTRAL = "NEUTRAL"

# Mechanics that are an internal marker, not something a player can play
# around. TRIGGER_VISUAL is on 95 of the 274 pool minions and means nothing.
TRAIT_NOISE = {"TRIGGER_VISUAL", "InvisibleDeathrattle"}

# The traits players actually search for, in the order they think of them.
# Anything else the live pool carries is appended by frequency, so a mechanic
# introduced by a future patch appears on its own instead of being invisible.
TRAIT_ORDER = ["DEATHRATTLE", "BATTLECRY", "TAUNT", "DIVINE_SHIELD", "REBORN",
               "WINDFURY", "VENOMOUS", "POISONOUS", "MAGNETIC", "AVENGE",
               "START_OF_COMBAT", "END_OF_TURN_TRIGGER", "BACON_SPELLCRAFT_ID",
               "BACON_RALLY", "AURA", "STEALTH", "CHOOSE_ONE", "DISCOVER"]
TRAIT_LABELS = {
    "DIVINE_SHIELD": "Divine Shield", "START_OF_COMBAT": "Start of Combat",
    "END_OF_TURN_TRIGGER": "End of Turn", "BACON_SPELLCRAFT_ID": "Spellcraft",
    "BACON_RALLY": "Rally", "CHOOSE_ONE": "Choose One",
}

SORTS = ("tier", "name", "rating")

_MARKUP = re.compile(r"<[^>]+>|\[x\]")
# The status line the reader emits states the stats slice: "top 25% · all-time".
_STATUS_RE = re.compile(r"top (\S+)% . (\S+)")


def trait_label(key: str) -> str:
    """'BACON_SPELLCRAFT_ID' -> 'Spellcraft'; unknown keys read tidily too."""
    if key in TRAIT_LABELS:
        return TRAIT_LABELS[key]
    k = re.sub(r"^BACON_", "", key)
    k = re.sub(r"_ID$", "", k)
    return k.replace("_", " ").title()


def plain(text: str) -> str:
    """Card text without the game's markup, on one line."""
    return re.sub(r"\s+", " ", _MARKUP.sub("", text or "")).strip()


class BrowserWindow(BaseWindow):
    KEY = "browser"
    TITLE = "MINIONS"
    WIDTH = 336
    COLUMN = "left"
    # The one free band on the left edge: above heropick's y+70, so the slim
    # bar never covers a window that opens by itself. Expanding is a deliberate
    # click and does cover the left column - it is a browser, it is draggable,
    # and a new game collapses it again.
    DY = 8
    RESERVE = 34
    MAX_H = 560
    EVENTS = ("lobby", "game", "status")

    ROW_H = 28
    LINE_H = 14

    def __init__(self, app):
        super().__init__(app)
        self.pool = []               # the live minion pool, loaded once
        self.cards = {}              # cardId -> stats row; {} with no source
        self.bands = {}              # tavern tier -> star cut points
        self.traits = [(None, "any trait", 0)]
        self.trait_i = 0
        self.sel_tiers = set()       # empty = every tier
        self.sel_tribes = set()
        self.tribe_touched = False   # once true, the lobby stops overriding
        self.lobby, self.exact = set(), False
        self.sort = "tier"
        self.top = 0                 # index of the first visible row
        self.open_id = None          # the minion expanded inline
        self.expanded = False
        self.loading = False
        self.error = None
        self.mmr, self.period = "100", "last-patch"
        self._key = None             # the (mmr, period) the stats came from
        self._hits = []              # [(key, x1, y1, x2, y2)]
        self._dirty = False          # set off-thread; picked up by tick()
        self._page = 1               # rows drawn last time, for paging
        self._shown = 0              # rows the filter matched last time
        if not self.headless:
            self.canvas.bind("<MouseWheel>", self._wheel)
        self._default_tribes()
        self.show()                  # the bar is always up; only the body toggles

    # -------------------------------------------------------------- lifecycle

    def reset(self):
        """A new game: back to the slim bar, filters back to the new lobby."""
        self.lobby, self.exact = set(), False
        self.tribe_touched = False
        self.open_id, self.top = None, 0
        self.expanded = False
        self._default_tribes()
        self.show()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()
            return
        if name == "lobby":
            self.lobby = set(payload.get("seen") or ())
            self.exact = bool(payload.get("exact"))
            if not self.tribe_touched:
                self._default_tribes()
        elif name == "status":
            self._read_status(payload)
        self.show()

    def tick(self, rect, game_front):
        # A background load finished: repaint on the Tk thread, never from the
        # loader (Tk is not thread-safe and a half-drawn canvas is a crash).
        if self._dirty:
            self._dirty = False
            self.redraw()
        super().tick(rect, game_front)

    # ------------------------------------------------------------------ data

    def _read_status(self, payload):
        """Learn which stats slice the rest of the overlay is using.

        The reader owns the --mmr/--time flags and no window is handed them, so
        the status line ("top 25% · all-time") is how the browser rates minions
        off the same table the tavern does. An unparseable status (e.g.
        "loading failed: ...") leaves the overlay's own defaults in place.
        """
        m = _STATUS_RE.match(str(payload or ""))
        if not m:
            return
        if (m.group(1), m.group(2)) != (self.mmr, self.period):
            self.mmr, self.period = m.group(1), m.group(2)
            if self._key is not None and self._key != (self.mmr, self.period):
                self._load_async()

    def _load_async(self):
        if self.loading:
            return
        self.loading, self.error = True, None
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        """Pool + stats, off the UI thread. Nothing here touches Tk."""
        mmr, period = self.mmr, self.period
        try:
            pool = bg.bg_pool()
        except Exception as e:            # offline on a machine with no cache
            self.error = f"card pool unavailable ({e.__class__.__name__})"
            self.loading, self._dirty = False, True
            return
        try:
            cards = bg.card_table(mmr, period)
        except Exception:
            cards = {}                    # no source configured -> no numbers
        try:
            tiers = bg.card_tiers()
        except Exception:
            tiers = {}
        for m in pool:                    # the pool already knows its own tier
            tiers.setdefault(m["id"], m["techLevel"])
        self.pool = pool
        self.cards = cards
        self.bands = self._make_bands(cards, tiers)
        self.traits = self._make_traits(pool)
        self.trait_i = min(self.trait_i, len(self.traits) - 1)
        self._key = (mmr, period)
        self.loading, self._dirty = False, True

    @staticmethod
    def _make_bands(cards, tiers):
        """Star cut points per tavern tier, from the differential.

        Top-heavy on purpose (top 8% = five stars, top quarter = four): even
        quintiles left half of every decent shop at five stars, which
        recommends nothing. A tier with fewer than ten rated minions gets no
        band at all, so its minions show a dash instead of a rank invented out
        of three samples.
        """
        by_tier = {}
        for cid, v in cards.items():
            if v.get("delta") is not None and v.get("n", 0) >= bg.MIN_SAMPLE:
                by_tier.setdefault(tiers.get(cid, 0), []).append(v["delta"])
        cut = {}
        for t, vals in by_tier.items():
            vals.sort()
            if len(vals) >= 10:
                cut[t] = [vals[int(len(vals) * k)] for k in (0.08, 0.25, 0.50, 0.75)]
        return cut

    @staticmethod
    def _make_traits(pool):
        """[(mechanic|None, label, count)] for the traits this pool really has."""
        counts = {}
        for m in pool:
            for k in m["mechanics"]:
                if k not in TRAIT_NOISE:
                    counts[k] = counts.get(k, 0) + 1
        keys = [k for k in TRAIT_ORDER if counts.get(k)]
        keys += sorted((k for k in counts if k not in TRAIT_ORDER),
                       key=lambda k: -counts[k])
        return ([(None, "any trait", len(pool))]
                + [(k, trait_label(k), counts[k]) for k in keys])

    @property
    def rated(self):
        """True only when a real card table is behind the stars."""
        return bool(self.bands)

    def stars(self, m):
        """1..5 against its OWN tier, or None when nothing measured it."""
        st = self.cards.get(m["id"])
        delta = (st or {}).get("delta")
        cut = self.bands.get(m["techLevel"]) or self.bands.get(0)
        if delta is None or not cut:
            return None
        return (5 if delta <= cut[0] else 4 if delta <= cut[1] else
                3 if delta <= cut[2] else 2 if delta <= cut[3] else 1)

    # --------------------------------------------------------------- filters

    def _default_tribes(self):
        """The lobby's own tribes - plus the tribeless minions, which are in
        every lobby. With no lobby known yet, everything."""
        self.sel_tribes = (set(self.lobby) | {NEUTRAL} if self.lobby
                           else set(bg.TRIBES) | {NEUTRAL})

    def _trait(self):
        return self.traits[min(self.trait_i, len(self.traits) - 1)]

    def _match(self, m):
        if self.sel_tiers and m["techLevel"] not in self.sel_tiers:
            return False
        trait = self._trait()[0]
        if trait and trait not in m["mechanics"]:
            return False
        races = m["races"]
        if not races:
            return NEUTRAL in self.sel_tribes
        if "ALL" in races:                       # an Amalgam is every tribe
            return bool(self.sel_tribes - {NEUTRAL})
        return any(r in self.sel_tribes for r in races)

    def _rows(self):
        rows = [m for m in self.pool if self._match(m)]
        if self.sort == "name":
            rows.sort(key=lambda m: m["name"].lower())
        elif self.sort == "rating" and self.rated:
            rows.sort(key=lambda m: (self.stars(m) is None, -(self.stars(m) or 0),
                                     -m["techLevel"], m["name"].lower()))
        else:
            rows.sort(key=lambda m: (m["techLevel"], m["name"].lower()))
        return rows

    # -------------------------------------------------------------- clicking

    def _hit(self, key, x1, y1, x2, y2):
        self._hits.append((key, x1, y1, x2, y2))

    def on_click(self, x, y):
        for key, x1, y1, x2, y2 in self._hits:
            if x1 - 2 <= x <= x2 + 2 and y1 - 2 <= y <= y2 + 2:
                self._act(key)
                self.redraw()
                return True
        return False        # not a control: let the click start a drag

    def _act(self, key):
        kind = key[0] if isinstance(key, tuple) else key
        if kind == "toggle":
            self.expanded = not self.expanded
            if self.expanded and not self.pool and not self.loading:
                self._load_async()
        elif kind == "tier":
            val = key[1]
            if val is None:
                self.sel_tiers.clear()
            elif val in self.sel_tiers:
                self.sel_tiers.discard(val)
            else:
                self.sel_tiers.add(val)
            self.top = 0
        elif kind == "tribe":
            self.tribe_touched = True
            if key[1] in self.sel_tribes:
                self.sel_tribes.discard(key[1])
            else:
                self.sel_tribes.add(key[1])
            self.top = 0
        elif kind == "tribes_lobby":
            self.tribe_touched = False
            self._default_tribes()
            self.top = 0
        elif kind == "tribes_all":
            self.tribe_touched = True
            self.sel_tribes = set(bg.TRIBES) | {NEUTRAL}
            self.top = 0
        elif kind in ("trait_next", "trait_prev", "trait_any"):
            if kind == "trait_any":
                self.trait_i = 0
            else:
                step = 1 if kind == "trait_next" else -1
                self.trait_i = (self.trait_i + step) % max(1, len(self.traits))
            self.top = 0
        elif kind == "sort":
            opts = [s for s in SORTS if s != "rating" or self.rated]
            self.sort = (opts[(opts.index(self.sort) + 1) % len(opts)]
                         if self.sort in opts else opts[0])
            self.top = 0
        elif kind == "up":
            self.top = max(0, self.top - self._page)
        elif kind == "down":
            self.top = min(max(0, self._shown - self._page), self.top + self._page)
        elif kind == "row":
            self.open_id = None if self.open_id == key[1] else key[1]

    def _wheel(self, e):
        """Bonus scrolling. The wheel only reaches a window that has focus, so
        the ▲▼ buttons stay the control this window is designed around."""
        if not self.expanded:
            return None
        step = 3 if e.delta < 0 else -3
        self.top = max(0, min(max(0, self._shown - 1), self.top + step))
        self.redraw()
        return "break"

    # --------------------------------------------------------------- drawing

    def _chip(self, c, x, y, w, label, on, key, color=ACCENT, h=15, font=F_CHIP):
        if on:
            rrect(c, x, y, x + w, y + h, 7, fill=color, outline="")
            c.create_text(x + w / 2, y + h / 2 + 1, text=label, fill="#101116",
                          font=font)
        else:
            rrect(c, x, y, x + w, y + h, 7, fill=PANEL, outline=LINE)
            c.create_text(x + w / 2, y + h / 2 + 1, text=label, fill="#767c88",
                          font=font)
        if key is not None:
            self._hit(key, x, y, x + w, y + h)

    def draw(self, c):
        self._hits = []
        dot = GOOD if self.exact else (AMBER if self.lobby else DIM)
        y = self.header(c, None, dot=dot)

        # The toggle - the whole reason this window is always on screen.
        self._chip(c, self.WIDTH - 84, 4, 72,
                   "close ✕" if self.expanded else "browse ▸",
                   self.expanded, "toggle")
        c.create_text(88, 14, anchor="w", font=F_SUB, text=self._hint()[:30],
                      fill=BAD if self.error else DIM)
        if not self.expanded:
            return y + 4

        if self.error:
            c.create_text(14, y + 12, anchor="w", fill=BAD, font=F_SUB,
                          text=self.error[:52])
            return y + 30
        if not self.pool:
            c.create_text(14, y + 12, anchor="w", fill=DIM, font=F_SUB,
                          text="loading the card pool…")
            return y + 30

        y = self._filters(c, y)
        c.create_line(12, y, self.WIDTH - 12, y, fill=LINE)
        return self._list(c, y + 6)

    def _hint(self):
        if self.error:
            return self.error
        if self.loading:
            return "loading…"
        if self.expanded:
            return f"{len(self.pool)} in the pool"
        if self.lobby:
            n = len(self.lobby)
            return f"{n} tribe{'s' if n != 1 else ''} in this lobby"
        return "browse the pool"

    def _filters(self, c, y):
        # -- tavern tier ---------------------------------------------------
        c.create_text(12, y + 8, text="TIER", anchor="w", fill=DIM, font=F_TITLE)
        self._chip(c, 46, y, 26, "all", not self.sel_tiers, ("tier", None))
        x = 78
        for t in range(1, 8):
            self._chip(c, x, y, 22, str(t), t in self.sel_tiers, ("tier", t))
            x += 26
        y += 20

        # -- tribe (default = this lobby) ----------------------------------
        c.create_text(12, y + 18, text="TRIBE", anchor="w", fill=DIM, font=F_TITLE)
        for i, t in enumerate(bg.TRIBES):
            self._chip(c, 46 + (i % 5) * 30, y + (i // 5) * 20, 27, TRIBE_TAG[t],
                       t in self.sel_tribes, ("tribe", t), color=TRIBE_COLOR[t])
        self._chip(c, 200, y, 30, "NTR", NEUTRAL in self.sel_tribes,
                   ("tribe", NEUTRAL), color=SOFT)
        self._chip(c, 236, y, 46, "lobby", not self.tribe_touched, "tribes_lobby")
        self._chip(c, 288, y, 34, "all",
                   len(self.sel_tribes) > len(bg.TRIBES), "tribes_all")
        self._chip(c, 200, y + 20, 122, f"sort · {self.sort} ›", False, "sort")
        y += 40

        # -- trait ---------------------------------------------------------
        key, label, count = self._trait()
        c.create_text(12, y + 8, text="TRAIT", anchor="w", fill=DIM, font=F_TITLE)
        self._chip(c, 46, y, 18, "‹", False, "trait_prev")
        self._chip(c, 68, y, 170, f"{label} · {count}", key is not None, "trait_any")
        self._chip(c, 242, y, 18, "›", False, "trait_next")
        return y + 22

    def _list(self, c, y):
        rows = self._rows()
        self._shown = len(rows)
        if self.top >= len(rows):
            self.top = 0
        limit = self.MAX_H - 32           # leave the footer its band
        drawn = 0
        for m in rows[self.top:]:
            opened = self.open_id == m["id"]
            detail = self._detail(m) if opened else []
            need = self.ROW_H + (len(detail) * self.LINE_H + 6 if opened else 0)
            if y + need > limit:
                break
            if opened:
                rrect(c, 8, y, self.WIDTH - 8, y + need - 2, 8,
                      fill=PANEL_HI, outline="")
            self._row(c, y, m, opened)
            self._hit(("row", m["id"]), 8, y, self.WIDTH - 8, y + self.ROW_H)
            y += self.ROW_H
            for text, fill in detail:
                c.create_text(44, y + 5, text=text, anchor="w", fill=fill,
                              font=F_SUB)
                y += self.LINE_H
            if opened:
                y += 6
            drawn += 1
        self._page = max(1, drawn)
        if not rows:
            c.create_text(14, y + 10, anchor="w", fill=DIM, font=F_SUB,
                          text="nothing matches these filters")
            y += 26
        return self._footer(c, y, len(rows), drawn)

    def _row(self, c, y, m, opened):
        # The pool's own cardId is the art id; the name lookup is the same
        # fallback the offer rows use, for a card whose art landed elsewhere.
        ic = self.app.art.icon(m["id"], 22) or self.app.art.icon_for_name(m["name"], 22)
        if ic is not None:
            c.create_image(14, y + 14, image=ic, anchor="w")
        else:                              # no art on disk: keep the column
            col = TRIBE_COLOR.get(m["races"][0] if m["races"] else "", LINE)
            rrect(c, 14, y + 3, 36, y + 25, 5, fill=PANEL, outline=col)
        c.create_text(44, y + 14, anchor="w", font=F_SUB,
                      fill=TEXT if opened else SOFT, text=m["name"][:30])
        c.create_text(self.WIDTH - 14, y + 14, anchor="e", fill=DIM, font=F_SUB,
                      text=f"T{m['techLevel']}")
        races = [r for r in m["races"] if r in TRIBE_TAG]
        if races:
            col = TRIBE_COLOR[races[0]]
            rrect(c, self.WIDTH - 66, y + 6, self.WIDTH - 39, y + 21, 7,
                  fill=PANEL, outline=col)
            c.create_text(self.WIDTH - 52, y + 14, font=F_CHIP, fill=col,
                          text=TRIBE_TAG[races[0]] if len(races) == 1 else "MIX")
        elif "ALL" in m["races"]:
            c.create_text(self.WIDTH - 52, y + 14, text="ALL", fill=SOFT,
                          font=F_CHIP)
        if self.rated:
            s = self.stars(m)
            if s is None:
                c.create_text(self.WIDTH - 74, y + 14, text="—", anchor="e",
                              fill=DIM, font=F_SUB)
            else:
                c.create_text(self.WIDTH - 74, y + 14, text="★" * s, anchor="e",
                              fill=STAR_COLOR.get(s, DIM), font=("Segoe UI", 8))

    def _detail(self, m):
        """The opened row: what it is, what it does, and - only with a real
        table behind it - what buying it actually did."""
        out = []
        races = ", ".join(r.title() for r in m["races"]) or "No tribe"
        meta = f"Tier {m['techLevel']} · {races}"
        mechs = [trait_label(k) for k in m["mechanics"] if k not in TRAIT_NOISE]
        if mechs:
            meta += " · " + ", ".join(mechs[:3])
        out.append((meta[:56], SOFT))
        for line in textwrap.wrap(plain(m["text"]), 52)[:3]:
            out.append((line, DIM))
        st = self.cards.get(m["id"]) or {}
        if st.get("delta") is not None:
            out.append((f"{st['avg']:.2f} avg when bought vs "
                        f"{st['avg'] - st['delta']:.2f} without · "
                        f"{st.get('n', 0):,} games", ACCENT))
        return out

    def _footer(self, c, y, total, drawn):
        c.create_line(12, y + 2, self.WIDTH - 12, y + 2, fill=LINE)
        y += 6
        self._chip(c, 14, y, 26, "▲", False, "up")
        self._chip(c, 44, y, 26, "▼", False, "down")
        c.create_text(78, y + 8, anchor="w", fill=DIM, font=F_SUB,
                      text=f"{self.top + 1 if drawn else 0}–{self.top + drawn}"
                           f" of {total}")
        c.create_text(self.WIDTH - 14, y + 8, anchor="e", font=F_SUB,
                      fill=DIM if self.rated else AMBER,
                      text=(f"rated vs own tier · top {self.mmr}%"
                            if self.rated else "no stats source"))
        return y + 24
