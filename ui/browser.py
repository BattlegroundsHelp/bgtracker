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
3. **No stats, no invented stats.** A NUMBER here only ever comes from a
   configured card table: placements, sample sizes and the turn strip are
   measured or they are absent. What a minion nobody has measured yet gets
   instead is NO star and two facts it can check: how its body compares with
   its own tier's average, and which comps are built around it. A rating
   computed from the card alone was built and measured first, and it ranked
   bodies - Brann Bronzebeard one star, a vanilla 10/11 five - so it was not
   shipped. With neither a table nor a warm pool the browser still browses:
   names, tiers, tribes, traits and card text.

An opened row also answers WHEN a minion pays off, if the configured feed
carries a per-turn breakdown: four stretches of the game, each showing the
same buy-it-vs-skip-it difference the stars use. Splitting one card's games
across fourteen turns is exactly how a healthy sample becomes fourteen small
ones, so a stretch under the sample floor is drawn as the word "thin" with
its game count and never as a number, and a stretch nobody played it in shows
a dash. A feed with no breakdown says so in one line - see TURN_BANDS.

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
import grades

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_STARS, F_SUB, F_TITLE,
                   GOOD, LINE, OFF_CHIP, ON_CHIP, PANEL, SHADE, SOFT,
                   STAR_COLOR, TEXT, TRIBE_COLOR, TRIBE_TAG, BaseWindow,
                   art_frame, plate, rrect, shadow_text, tile_row)

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

# "type" first and default: the reference browser (HSReplay's, measured off
# their overlay page 2026-08-14) groups the list under tribe section headers,
# tiers within each - that IS its resting view, not an option it hides.
SORTS = ("type", "tier", "name", "rating")

# TURN-BY-TURN
# ------------
# A cards feed may carry a per-turn breakdown beside the whole-game numbers:
#
#   {"cardId": "BG00_000", "averagePlacement": 3.4, "averagePlacementOther": 3.9,
#    "turnStats": [{"turn": 1, "totalPlayed": 40, "averagePlacement": 3.9,
#                   "totalOther": 60, "averagePlacementOther": 3.8}, ...]}
#
# ``bgtracker.card_table`` keeps only avg/n/delta, so nothing in the overlay
# ever saw this; the browser reads the same feed a second time, raw, to get at
# it. Fourteen separate turns will not fit a 336px panel and would be mostly
# noise anyway, so they are aggregated into four stretches of the game. A
# stretch is scored the way the stars are - the buy-it-vs-skip-it DIFFERENTIAL
# - because a raw average by turn mostly measures who is still alive by then.
#
# A stretch under MIN_SAMPLE is drawn as "thin" and NOT as a number. That is
# exactly the case a per-turn split creates: splitting one card's games
# fourteen ways turns a healthy sample into fourteen small ones.
TURN_BANDS = ((1, 4), (5, 8), (9, 12), (13, 99))

# A marker in the detail list: draw the turn strip here, not a line of text.
TURNS = object()

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
        self.turns = {}              # cardId -> [(turn, avg, other, n, other_n)]
        self.bands = {}              # tavern tier -> star cut points
        self.traits = [(None, "any trait", 0)]
        self.trait_i = 0
        self.sel_tiers = set()       # empty = every tier
        self.sel_tribes = set()
        self.tribe_touched = False   # once true, the lobby stops overriding
        self.lobby, self.exact = set(), False
        self.sort = "type"
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
            turns = self._read_turns(mmr, period)
        except Exception:
            turns = {}                    # the breakdown is optional, always
        try:
            tiers = bg.card_tiers()
        except Exception:
            tiers = {}
        for m in pool:                    # the pool already knows its own tier
            tiers.setdefault(m["id"], m["techLevel"])
        try:
            # The card-derived grade for everything the table has not measured.
            # Warmed HERE, on the loader thread, for the same reason the pool
            # is: a cold build reads the card pool and the draw path may never
            # wait on that. It failing costs the grades, nothing else.
            grades.table()
        except Exception:
            pass
        self.pool = pool
        self.cards = cards
        self.turns = turns
        self.bands = self._make_bands(cards, tiers)
        self.traits = self._make_traits(pool)
        self.trait_i = min(self.trait_i, len(self.traits) - 1)
        self._key = (mmr, period)
        self.loading, self._dirty = False, True

    @staticmethod
    def _read_turns(mmr, period):
        """cardId -> [(turn, avg, other, played)] from the raw cards feed.

        Read raw because ``card_table`` throws the breakdown away. Anything
        malformed is skipped rather than repaired: a turn with no placement or
        no turn number cannot be plotted, and guessing which one it meant
        would be inventing the number this panel exists to report honestly.
        The whole feed is already in memory from card_table's own call, so
        this costs a dict walk, not a fetch.
        """
        data = bg.load_bucket(bg.source_kind("cards", False), "cardStats",
                              mmr, period)
        out = {}
        for row in data.get("cardStats") or ():
            cid, ts = row.get("cardId"), row.get("turnStats")
            if not cid or not isinstance(ts, list):
                continue
            got = []
            for t in ts:
                if not isinstance(t, dict):
                    continue
                turn, avg = t.get("turn"), t.get("averagePlacement")
                other = t.get("averagePlacementOther")
                if not isinstance(turn, int) or avg is None or other is None:
                    continue
                got.append((turn, float(avg), float(other),
                            int(t.get("totalPlayed") or 0),
                            int(t.get("totalOther") or 0)))
            if got:
                out[cid] = sorted(got)
        return out

    @staticmethod
    def _turn_bands(rows):
        """The four stretches of a game: (label, delta|None, played, thin).

        ``delta`` is None when the stretch has no games at all - a dash, not a
        zero. ``thin`` says the stretch has games but not enough of them, and
        the caller draws that as the word rather than as a number.
        """
        out = []
        for lo, hi in TURN_BANDS:
            got = [r for r in rows if lo <= r[0] <= hi]
            played = sum(r[3] for r in got)
            label = f"t{lo}-{hi}" if hi < 99 else f"t{lo}+"
            if not got or not played:
                out.append((label, None, 0, False))
                continue
            # Each side is weighted by ITS OWN game count - the played average
            # by how many bought it that turn, the comparison average by how
            # many did not. Using one weight for both would silently reweight
            # the comparison group into something nobody measured.
            other_n = sum(r[4] for r in got)
            avg = sum(r[1] * r[3] for r in got) / played
            other = (sum(r[2] * r[4] for r in got) / other_n if other_n
                     else sum(r[2] for r in got) / len(got))
            out.append((label, avg - other, played, played < bg.MIN_SAMPLE))
        return out

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

    @property
    def graded(self):
        """True when the card-derived fallback is warm. It needs no stats
        source at all - only the card database the browser already reads."""
        return grades.ready()

    def stars(self, m):
        """1..5 against its OWN tier, or None when nothing measured it."""
        st = self.cards.get(m["id"])
        delta = (st or {}).get("delta")
        cut = self.bands.get(m["techLevel"]) or self.bands.get(0)
        if delta is None or not cut:
            return None
        return (5 if delta <= cut[0] else 4 if delta <= cut[1] else
                3 if delta <= cut[2] else 2 if delta <= cut[3] else 1)

    def rating(self, m):
        """(stars, graded) - what this row should draw.

        MEASURED WINS, per card and not per table: a card with a real
        differential is measured even in a pool where almost nothing else is,
        and the day the pool can measure a card it stops being graded. Only
        where the table has nothing does the card's own grade answer, and the
        second value says which of the two it was so the row can draw an
        opinion differently from a measurement.
        """
        s = self.stars(m)
        if s is not None:
            return s, False
        # No computed star. See the note in overlay.py's star(): a grade read
        # off the card alone ranks bodies, so it put Brann Bronzebeard at 1
        # star and a vanilla 10/11 at 5. The row still carries what the card
        # really says (its tier, its tribe, its text, and the comps it is core
        # to), which is useful and cannot be wrong.
        return None, False

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

    def _group(self, m):
        """The section a card files under when the list is grouped by type:
        its tribe (a two-tribe card goes under the alphabetically first, the
        same rule _pick_tribe uses for naming), Amalgams under their own
        heading, the tribeless last."""
        races = [r for r in m["races"] if r in TRIBE_TAG]
        if races:
            return min(races).title()
        if "ALL" in m["races"]:
            return "All tribes"
        return "No tribe"

    def _rows(self):
        rows = [m for m in self.pool if self._match(m)]
        if self.sort == "type":
            order = {"All tribes": "zz", "No tribe": "zzz"}
            rows.sort(key=lambda m: (order.get(self._group(m),
                                               self._group(m)),
                                     m["techLevel"], m["name"].lower()))
        elif self.sort == "name":
            rows.sort(key=lambda m: m["name"].lower())
        elif self.sort == "rating" and (self.rated or self.graded):
            # Equal stars: measured before graded. One is what happened in real
            # games and the other is an opinion about a card, so a tie between
            # them is not a tie.
            def key(m):
                s, graded = self.rating(m)
                return (s is None, -(s or 0), graded, -m["techLevel"],
                        m["name"].lower())
            rows.sort(key=key)
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
            opts = [s for s in SORTS
                    if s != "rating" or self.rated or self.graded]
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
            c.create_text(x + w / 2, y + h / 2 + 1, text=label, fill=ON_CHIP,
                          font=font)
        else:
            rrect(c, x, y, x + w, y + h, 7, fill=SHADE, outline=LINE)
            c.create_text(x + w / 2, y + h / 2 + 1, text=label, fill=OFF_CHIP,
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
        last_group = None
        for m in rows[self.top:]:
            opened = self.open_id == m["id"]
            detail = self._detail(m) if opened else []
            need = self.ROW_H + (self._detail_h(detail) + 6 if opened else 0)
            # Grouped by type: a slim section header the way the reference
            # draws its Demon / Dragon / ... bars, once per tribe change.
            if self.sort == "type":
                g = self._group(m)
                if g != last_group:
                    if y + 16 + need > limit:
                        break
                    c.create_rectangle(8, y + 1, self.WIDTH - 8, y + 15,
                                       fill=SHADE, outline="")
                    c.create_text(14, y + 8, text=g, anchor="w",
                                  fill=SOFT, font=F_TITLE)
                    y += 17
                    last_group = g
            if y + need > limit:
                break
            if opened:
                # The opened card is the one thing this window is pointing
                # at, so it gets the gold-edged plate the offer rows use.
                plate(c, 8, y, self.WIDTH - 8, y + need - 2, 8, best=True)
            self._row(c, y, m, opened)
            self._hit(("row", m["id"]), 8, y, self.WIDTH - 8, y + self.ROW_H)
            y += self.ROW_H
            for text, fill in detail:
                if text is TURNS:
                    y = self._turn_strip(c, y, fill)
                    continue
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
        # The row is the game's own deck-list tile - how HSReplay and
        # Firestone draw a minion in the match (founder's direction,
        # 2026-08-14). No tile on disk and the icon-and-text row returns.
        tiled = tile_row(c, 8, y + 1, self.WIDTH - 8, y + 27, m["id"],
                         best=opened)
        name_x = 14 if tiled else 44
        if not tiled:
            # The pool's own cardId is the art id; the name lookup is the same
            # fallback the offer rows use, for a card whose art landed
            # elsewhere.
            ic = (self.app.art.icon(m["id"], 22)
                  or self.app.art.icon_for_name(m["name"], 22))
            if ic is not None:
                c.create_image(14, y + 14, image=ic, anchor="w")
                art_frame(c, 13, y + 3, 37, y + 25, opened)
            else:                          # no art on disk: keep the column
                col = TRIBE_COLOR.get(m["races"][0] if m["races"] else "", LINE)
                rrect(c, 14, y + 3, 36, y + 25, 5, fill=PANEL, outline=col)
        c.create_text(name_x, y + 14, anchor="w", font=F_SUB,
                      fill=TEXT if opened else SOFT, text=m["name"][:30])
        if tiled:
            shadow_text(c, self.WIDTH - 14, y + 14, f"T{m['techLevel']}",
                        DIM, F_SUB, anchor="e")
        else:
            c.create_text(self.WIDTH - 14, y + 14, anchor="e", fill=DIM,
                          font=F_SUB, text=f"T{m['techLevel']}")
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
        if self.rated or self.graded:
            s, graded = self.rating(m)
            if s is None:
                c.create_text(self.WIDTH - 74, y + 14, text="—", anchor="e",
                              fill=DIM, font=F_SUB)
            else:
                # Filled and colour graded = measured. Hollow and muted = read
                # off the card. Same glyph rule as the tavern row, so the two
                # windows never say the same thing two ways.
                c.create_text(self.WIDTH - 74, y + 14, anchor="e", font=F_STARS,
                              text="★" * s,
                              fill=SOFT if graded else STAR_COLOR.get(s, DIM))

    def _detail(self, m):
        """The opened row: what it is, what it does, and - only with a real
        table behind it - what buying it actually did, and when."""
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
        else:
            out.extend(self._grade_lines(m))
        rows = self.turns.get(m["id"])
        if rows:
            out.append((TURNS, self._turn_bands(rows)))
        elif st.get("delta") is not None:
            # There IS a stats source and it rated this card, it just carries
            # no per-turn split. Say which of the two it is rather than
            # leaving a silence that reads like "this card is never good".
            out.append(("no turn-by-turn split in this source", DIM))
        return out

    @staticmethod
    def _grade_lines(m):
        """The opened row for a minion NOBODY HAS MEASURED.

        There is deliberately no star here. A rating computed from the card
        alone was built and measured, and it ranks BODIES: it put Brann
        Bronzebeard at one star and a vanilla 10/11 at five, because the value
        of "your Battlecries trigger twice" lives in the board around it and
        the board is not on the card. Labelling that opinion hollow would not
        have made it right.

        What is left is what the card really says, and every line of it is
        checkable: how its body compares with its own tier's average, and which
        comps are built around it. Those come from the same pass that scored
        the card, so they cannot drift from anything else the window draws.
        """
        why = [w for w in (grades.why(m["id"]) or [])
               if "body" in w or "core" in w or "supports" in w]
        if not why:
            return []
        out = [("no games have measured this one yet", AMBER)]
        for line in textwrap.wrap(", ".join(why), 52)[:2]:
            out.append((line, DIM))
        return out

    def _detail_h(self, detail):
        """How tall the opened block will be. The turn strip is two lines."""
        return sum(self.LINE_H * (2 if text is TURNS else 1)
                   for text, _ in detail)

    def _turn_strip(self, c, y, bands):
        """WHEN this minion pays: four stretches of the game, each showing the
        buy-it-vs-skip-it difference, a dash where nothing was measured and
        the word "thin" where too little was."""
        c.create_text(44, y + 5, text="BY TURN", anchor="w", fill=DIM,
                      font=F_TITLE)
        c.create_text(self.WIDTH - 14, y + 5, anchor="e", fill=DIM, font=F_SUB,
                      text="placement vs not buying it")
        y += self.LINE_H
        x, w = 44, (self.WIDTH - 58 - 44) / len(bands)
        for label, delta, played, thin in bands:
            c.create_text(x, y + 5, text=label, anchor="w", fill=DIM, font=F_CHIP)
            if delta is None:
                c.create_text(x + 30, y + 5, text="—", anchor="w", fill=DIM,
                              font=F_SUB)
            elif thin:
                c.create_text(x + 30, y + 5, text=f"thin {played}", anchor="w",
                              fill=AMBER, font=F_CHIP)
            else:
                c.create_text(x + 30, y + 5, text=f"{delta:+.2f}", anchor="w",
                              fill=GOOD if delta < 0 else BAD, font=F_SUB)
            x += w
        return y + self.LINE_H

    def _footer(self, c, y, total, drawn):
        c.create_line(12, y + 2, self.WIDTH - 12, y + 2, fill=LINE)
        y += 6
        self._chip(c, 14, y, 26, "▲", False, "up")
        self._chip(c, 44, y, 26, "▼", False, "down")
        # "1-20", with a plain hyphen. No em or en dashes anywhere the player
        # can read them - the same rule the rest of this project's text
        # follows, and a range is the one place a typographer's dash sneaks
        # back in. (The lone "—" this file draws for a missing number is not
        # text: it is the no-data marker, and it stays.)
        c.create_text(78, y + 8, anchor="w", fill=DIM, font=F_SUB,
                      text=f"{self.top + 1 if drawn else 0}-{self.top + drawn}"
                           f" of {total}")
        # What the stars on screen actually are, in the smallest honest words.
        # Both halves get named whenever both are on screen: a player who never
        # opens a row still has to be able to tell an opinion from a
        # measurement.
        if self.rated and self.graded:
            note, fill = f"★ measured top {self.mmr}%", DIM
        elif self.rated:
            note, fill = f"rated vs own tier · top {self.mmr}%", DIM
        elif self.graded:
            note, fill = "no games have measured these yet", AMBER
        else:
            note, fill = "no stats source", AMBER
        c.create_text(self.WIDTH - 14, y + 8, anchor="e", font=F_SUB,
                      fill=fill, text=note)
        return y + 24
