"""HERO PICK window - the heroes on offer in the draft. Nothing else.

Lifecycle:
  opens   on the hero-draft burst (the four heroes dealt into your HAND)
  updates on a slot correction - the client shuffles the offered heroes into
          their final on-screen order AFTER the burst, sharing its timestamp,
          so the badges move to the right portraits instead of being wrong
  closes  on ``hero_over``, which the reader raises off the first PowerTaskList
          CARDRACE line: shop minions on screen means the hero is picked
  closes  on its timeout as a belt-and-braces backstop

It sits down the LEFT edge of the game window by default because the hero
portraits occupy the middle and the badge strip already writes each hero's
number above its own portrait.

Each hero also gets one line of community-written advice under its name, from
data/hero_tips.json (see CONTRIBUTING.md). A hero with no tip shows nothing at
all - no placeholder, no "no tip yet" - and the line is drawn inside the row
that already exists, so the window is exactly as tall as it was and stays
inside its band.

A line can come from two places and they are not the same claim, so the window
says which: the tips that SHIP were written against the hero's own card text
and reviewed in a pull request, while a VOTED line is a stranger's, published
by server/tips.py once the vote cleared its floors. A voted line is marked ▲ on
the row and named in the header; an unmarked line is the shipped one. There is
deliberately no vote button here. The band is full at four heroes - the tip
line replaces the placement bar precisely because there is no room to add one -
a hero draft is a 60 second decision and not the moment to editorialise, and a
one-click vote from an anonymous overlay is a ballot box with no lock: the
same script that could fake games could fake votes. So the honest minimum is
what is built - the header carries the page the feed names, when it names one
and when the header has room to print it, and a person votes there.
"""

from __future__ import annotations

import bgtracker as bg

from .base import AMBER, DIM, F_SUB, F_TITLE, BaseWindow, fit_text, offer_rows

# The mark a voted line wears, on the row and in the header, so the two never
# have to be told apart by memory.
VOTED = "▲"
# What the header has left after the title. "PICK YOUR HERO" measures 93px in
# F_BRAND and starts at x=14, the right margin is 14, and a gap keeps the two
# from touching: 316 - 14 - 107 - 15. Anything longer is dropped in favour of
# a shorter way of saying the same thing, never truncated - half a URL is
# worse than no URL.
HEADER_PX = 180


class HeroPickWindow(BaseWindow):
    KEY = "heropick"
    TITLE = "PICK YOUR HERO"
    COLUMN = "left"
    DY = 70
    RESERVE = 256
    MAX_H = 256
    EVENTS = ("hero", "hero_slots", "hero_over", "game")
    BADGE_KIND = "hero"
    BADGE_PRIORITY = 40
    TIMEOUT_MS = 75_000        # hero select is at most ~60s

    def __init__(self, app):
        super().__init__(app)
        self.rows, self.tuned, self.voted = [], False, False
        # Start the voted-tips fetch now, not on the draft: a network call in
        # the Tk callback that opens this window would freeze the overlay over
        # the game for the length of the hero select.
        try:
            bg.warm_community_tips()
        except Exception:
            pass

    def reset(self):
        self.rows, self.tuned, self.voted = [], False, False
        self.hide()

    def _with_tips(self, rows):
        """Attach each hero's community tip line, by cardId.

        The rows come from the reader, which knows stats and nothing else, so
        the tip is attached here - the window that shows it. A hero with no
        entry gets no key at all, and the drawing code then draws nothing for
        it. A broken or missing tips file leaves every row untouched rather
        than taking the draft window down with it.

        The voted feed only gets a say once it has finished loading in the
        background; until then, and whenever there is no feed at all, this is
        the shipped file and nothing else.
        """
        self.voted = False
        try:
            tips = bg.hero_tips()
            voted = bg.community_tips() if bg.community_tips_ready() else {}
        except Exception:
            return rows
        out = []
        for r in rows:
            t = voted.get(r.get("card")) or tips.get(r.get("card"))
            if not (t and t.get("when")):
                out.append(r)
                continue
            line = t["when"]
            if t.get("source") == "community":
                line = f"{VOTED} {line}"
                self.voted = True
            out.append(dict(r, tip=line))
        return out

    def _subtitle(self):
        """What the header says about where these lines came from.

        Built longest first and measured, because the title takes the left of a
        316px bar: with a voted line on screen it says so, and it names the page
        the feed points at when that still fits. An unmarked line is the tip
        that ships, so nothing is said in that case - the window's normal state
        does not need a label.
        """
        base = "tuned to this lobby" if self.tuned else ""
        if not self.voted:
            return base or None
        # Longest first, and the shortest one has to survive next to "tuned to
        # this lobby" (measured: 176px of the 180 available), because a row
        # wearing a ▲ with nothing in the header explaining it is worse than
        # no mark at all.
        wants = [f"{VOTED} community tip", f"{VOTED} community"]
        try:
            url = bg.tips_vote_url()
        except Exception:
            url = None
        if url:
            short = url.split("://", 1)[-1].rstrip("/")
            wants.insert(0, f"{VOTED} vote {short}")
        for w in wants:
            s = f"{base} · {w}" if base else w
            if fit_text(s, HEADER_PX) == s:
                return s
        return base or None

    def on_event(self, name, payload):
        if name == "hero":
            self.rows = self._with_tips(payload.get("rows") or [])
            self.tuned = payload.get("tuned", False)
            self.show()
            self.badges_show(self.rows, bg.MIN_SAMPLE)
        elif name == "hero_slots":
            # Same offer, corrected on-screen order: move the badges, do not
            # re-open the window (it may have been closed by the pick).
            self.rows = self._with_tips(payload.get("rows") or []) or self.rows
            if self.is_open:
                self.badges_show(self.rows, bg.MIN_SAMPLE)
                self.redraw()
        elif name in ("hero_over", "game"):
            self.reset()

    def draw(self, c):
        y = self.header(c, self._subtitle(), AMBER)
        if not self.rows:
            c.create_text(14, y + 8, text="waiting for the draft", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 24
        y = offer_rows(c, y, self.rows, self.WIDTH, self.app.art, bg.MIN_SAMPLE)
        if not any(r.get("avg") is not None for r in self.rows):
            c.create_text(14, y + 8, text="NO HERO STATS CONFIGURED", anchor="w",
                          fill=DIM, font=F_TITLE)
            y += 20
        return y + 8
