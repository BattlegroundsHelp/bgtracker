"""OTHER PLAYERS window - the leaderboard, and the last board each of them was
actually seen holding.

WHERE THE DATA COMES FROM, AND WHY THIS WINDOW CAN BE ABSENT
------------------------------------------------------------
Power.log does not state a single thing about another player's board while you
are shopping - that has been checked against real logs repeatedly, and it is
still true. The only source is the game's own memory, read by the OPTIONAL
``native/msync`` helper. So this window is one of the few surfaces that simply
DOES NOT APPEAR unless you built that helper: with no ``players`` event, it
never opens, and nothing else in the overlay changes. That is the intended
degraded state, not a failure.

THE HONESTY RULES, which are the whole point of the feature
-----------------------------------------------------------
* A board is shown only if it was really read, and it is stamped with the
  round it was read in ("seen r7"), plus how long ago that was. Nothing here
  is ever extrapolated forward.
* A player nobody has fought yet has NO board line at all - a dash, not an
  empty board, and never a guess assembled from tavern tier or comp odds.
* The hero, health, armour and tier ARE live: they come from the leaderboard
  every reading. Only the board is historical, and only the board carries the
  "seen" stamp.
* What that board means for the fight ahead is your inference to make, not
  ours: this window states what was seen and when, nothing more.

LAYOUT
------
Shares the left column's trinket band (see ui/__init__.py). A trinket dialog
owns that band while it is up and this window steps aside for it, exactly as
the session panel steps aside for the hero draft; it comes back on
``picks_over``, and only while it still sits in its default slot - drag it
somewhere else and it stays put.

Two views, one click apart: the list of players, and one player's last-seen
board. Only one is ever drawn, which is what keeps both inside the band with
no clipping.
"""

from __future__ import annotations

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_NAME, F_SUB, F_TITLE,
                   GOOD, LINE, SOFT, TEXT, BaseWindow, art_frame, plate)

# Backstop for the shared band: if the trinket window's "picks are over" event
# never arrives, come back on our own instead of staying hidden all game.
YIELD_MS = 60_000


class PlayersWindow(BaseWindow):
    KEY = "players"
    TITLE = "OTHER PLAYERS"
    COLUMN = "left"
    DY = 492
    RESERVE = 272
    MAX_H = 272
    WIDTH = 316
    EVENTS = ("players", "trinket", "picks_over", "game")

    ROW_H = 27
    MINION_H = 18

    def __init__(self, app):
        super().__init__(app)
        self.rows = []            # other seats, already sorted by place
        self.round = None         # the round the reader is currently in
        self.you = None           # your own leaderboard row
        self.open_card = None     # the hero whose board is expanded
        self._hits = []           # [(cardId, y1, y2)] for clicks
        self._yielded = False
        self._unyield_timer = None

    # ----------------------------------------------------------------- events

    def reset(self):
        self.rows, self.you, self.round = [], None, None
        self.open_card = None
        self._hits = []
        self.hide()

    def on_event(self, name, payload):
        if name == "players":
            rows = payload.get("rows") or []
            self.round = payload.get("round")
            self.you = next((r for r in rows if r.get("you")), None)
            self.rows = [r for r in rows if not r.get("you")]
            # An expanded player who left the leaderboard takes the detail view
            # with them rather than leaving their old board on screen.
            if self.open_card and not any(r["card"] == self.open_card
                                          for r in self.rows):
                self.open_card = None
            if self.rows and not self._yielded:
                self.show()
        elif name == "trinket":
            # The trinket dialog wants this exact band. Stand aside - but only
            # while we are still in the default slot it would cover.
            if not self.dx and not self.dy and not self._yielded:
                self._yielded = True
                self.hide()
                if not self.headless:
                    self._unyield_timer = self.after(YIELD_MS, self._unyield)
        elif name == "picks_over":
            self._unyield()
        elif name == "game":
            self.reset()

    def _unyield(self):
        if self._unyield_timer is not None:
            try:
                self.after_cancel(self._unyield_timer)
            except Exception:
                pass
            self._unyield_timer = None
        self._yielded = False
        if self.rows:
            self.show()

    # --------------------------------------------------------------- clicking

    def on_click(self, x, y):
        for card, y1, y2 in self._hits:
            if y1 <= y <= y2:
                self.open_card = None if self.open_card == card else card
                self.redraw()
                return True
        return False

    # ---------------------------------------------------------------- drawing

    def _ago(self, seen):
        """'seen r7 - 2 rounds ago' - the whole point of the stamp."""
        if seen is None:
            return None
        if self.round is None or self.round <= seen:
            return f"seen r{seen}"
        gap = self.round - seen
        return f"seen r{seen} · {gap} round{'s' if gap > 1 else ''} ago"

    def _hp_color(self, row):
        total = (row.get("health") or 0) + (row.get("armor") or 0)
        if total <= 0:
            return DIM
        return BAD if total <= 10 else (AMBER if total <= 20 else SOFT)

    def draw(self, c):
        if self.open_card:
            return self._draw_board(c)
        return self._draw_list(c)

    def _draw_list(self, c):
        alive = [r for r in self.rows
                 if (r.get("health") or 0) + (r.get("armor") or 0) > 0]
        head = f"{len(alive)} left"
        if self.you and self.you.get("place"):
            head = f"you {self.you['place']}{_ord(self.you['place'])} · " + head
        y = self.header(c, head, DIM)
        self._hits = []

        if not self.rows:
            c.create_text(14, y + 10, text="waiting for a lobby", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 28

        for r in self.rows:
            dead = (r.get("health") or 0) + (r.get("armor") or 0) <= 0
            top = y
            seen = self._ago(r.get("seen_round"))
            if seen and not dead:
                plate(c, 8, y + 1, self.WIDTH - 8, y + self.ROW_H - 3, 7)

            c.create_text(16, y + 12, text=str(r["place"]), anchor="w",
                          fill=DIM, font=F_CHIP)
            ic = self.app.art.icon(r.get("card"), 18)
            tx = 28
            if ic is not None:
                c.create_image(28, y + 12, image=ic, anchor="w")
                art_frame(c, 27, y + 3, 47, y + 22)
                tx = 50
            name = r.get("name") or r.get("card") or "?"
            c.create_text(tx, y + 12, text=name[:18], anchor="w",
                          fill=DIM if dead else TEXT, font=F_NAME)

            # tier and health, right-aligned: live values, every reading
            rx = self.WIDTH - 14
            if dead:
                c.create_text(rx, y + 12, text="out", anchor="e", fill=DIM,
                              font=F_SUB)
            else:
                hp = f"{r.get('health', 0)}"
                if r.get("armor"):
                    hp += f"+{r['armor']}"
                c.create_text(rx, y + 12, text=hp, anchor="e",
                              fill=self._hp_color(r), font=F_NAME)
                if r.get("tier"):
                    c.create_text(rx - 42, y + 12, text=f"T{r['tier']}",
                                  anchor="e", fill=SOFT, font=F_SUB)

            # what was seen of their board - or nothing at all
            if seen and not dead:
                n = len(r.get("board") or [])
                c.create_text(rx - 74, y + 12, text=f"{n} ›", anchor="e",
                              fill=ACCENT, font=F_SUB)
                self._hits.append((r["card"], top, y + self.ROW_H))
            y += self.ROW_H

        if self._hits:
            c.create_text(14, y + 8, text="click a player for their last board",
                          anchor="w", fill=DIM, font=F_CHIP)
            y += 16
        return y + 8

    def _draw_board(self, c):
        row = next((r for r in self.rows if r["card"] == self.open_card), None)
        if row is None:                     # they left the leaderboard mid-click
            self.open_card = None
            return self._draw_list(c)
        board = row.get("board") or []
        y = self.header(c, self._ago(row.get("seen_round")), AMBER)
        self._hits = [(row["card"], 0, y + 18)]     # click the top = back

        name = row.get("name") or row["card"]
        c.create_text(14, y + 9, text=f"‹ {name[:20]}", anchor="w",
                      fill=ACCENT, font=F_TITLE)
        bits = []
        if row.get("tier"):
            bits.append(f"tier {row['tier']}")
        hp = row.get("health")
        if hp is not None:
            armor = f"+{row['armor']}" if row.get("armor") else ""
            bits.append(f"{hp}{armor} hp")
        if bits:
            c.create_text(self.WIDTH - 14, y + 9, text=" · ".join(bits),
                          anchor="e", fill=SOFT, font=F_SUB)
        y += 22
        c.create_line(10, y, self.WIDTH - 10, y, fill=LINE)
        y += 6

        if not board:
            c.create_text(14, y + 10, text="nothing seen of this board yet",
                          anchor="w", fill=DIM, font=F_SUB)
            return y + 30

        for m in board:
            ic = self.app.art.icon(m.get("card"), 16)
            tx = 16
            if ic is not None:
                c.create_image(16, y + 8, image=ic, anchor="w")
                tx = 36
            nm = m.get("name") or m.get("card") or "?"
            c.create_text(tx, y + 8, text=nm[:22], anchor="w", fill=SOFT,
                          font=F_SUB)
            atk, hp = m.get("atk"), m.get("health")
            if atk is not None and hp is not None:
                c.create_text(self.WIDTH - 14, y + 8, text=f"{atk}/{hp}",
                              anchor="e", fill=GOOD if atk >= hp else SOFT,
                              font=F_SUB)
            y += self.MINION_H
        c.create_text(14, y + 8, text="as it was when their fight was on screen",
                      anchor="w", fill=DIM, font=F_CHIP)
        return y + 18


def _ord(n):
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
