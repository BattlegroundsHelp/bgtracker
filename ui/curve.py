"""LEVELING - the little window that says which turn to hit each tavern tier.

Asked for in exactly these words: "when i pick an hero it shows on the side
the ideal curve... like another little window". The curves are curated
written strategy (data/curves.json, researched from public guides and dated
inside the file), the same class of shipped text as the hero tips - never
scraped stats, and a missing file simply means this window never opens.

It keys on the counters window's state (the same coupling the BUFFS window
uses, with the same hide-when-absent guard): our hero's cardId names the
bucket, the current turn highlights the next milestone, and the one line of
judgement it draws - on curve / behind / ahead - is plain arithmetic between
your tier and the curve's expectation at this turn. The window floats,
drags anywhere, and remembers its spot.
"""

from __future__ import annotations

import bgtracker as bg

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_NAME, F_SUB, GOOD,
                   PANEL_HI, SOFT, TEXT, BaseWindow, fit_text, rrect)


class CurveWindow(BaseWindow):
    KEY = "curve"
    TITLE = "LEVELING"
    COLUMN = "float"                # free-floating, like BUFFS: made to be
    DY = 928                        # dragged where the player wants it
    RESERVE = 88
    MAX_H = 126                     # header + wrapped milestones + verdict +
                                    # two note lines, at Tk's real line boxes
    WIDTH = 232
    EVENTS = ("game",)

    def __init__(self, app):
        super().__init__(app)
        self._seen = -1

    def reset(self):
        self._seen = -1
        self.hide()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()

    def _counters_state(self):
        w = self.app.by_key.get("counters")
        return w.state if w is not None else None

    def _bucket(self, hero_card):
        curves = bg.hero_curves()
        if hero_card:
            name = bg.card_names().get(hero_card)
            if name and name in curves["by_name"]:
                return curves["by_name"][name]
        return curves["default"]

    def tick(self, rect, game_front):
        s = self._counters_state()
        if s is None:
            self._seen = -1
            self.hide()
        elif s.version != self._seen:
            self._seen = s.version
            # Open from the first shop on: the curve matters most at the
            # start, hero known or not (no hero yet = the standard line).
            if s.bg_turn and bg.hero_curves()["default"] is not None:
                self.show()
            else:
                self.hide()
        super().tick(rect, game_front)

    def draw(self, c):
        s = self._counters_state()
        curves = bg.hero_curves()
        bucket = (self._bucket(s.hero) if s is not None
                  else curves["default"]) or curves["default"]
        if bucket is None:
            return 24
        hp = s.effective_hp if s is not None else None
        rules = curves.get("health_rules")
        # The header's right slot carries the health the strategy keys on,
        # coloured by the same thresholds the advice uses.
        hp_col = SOFT
        if hp is not None and rules:
            hp_col = (BAD if hp < rules["danger"]
                      else AMBER if hp < rules["caution"] else GOOD)
        # Only the hp wears the health colour - the bucket label is not
        # health data (hue is the number). The label sits beside it in DIM.
        y = self.header(c, f"{hp} hp" if hp is not None else bucket["label"],
                        hp_col if hp is not None else SOFT)
        if hp is not None:
            c.create_text(self.WIDTH - 14 - F_SUB.measure(f"{hp} hp") - 10,
                          14, text=bucket["label"], anchor="e", fill=DIM,
                          font=F_SUB)
        turn = (s.bg_turn or 0) if s is not None else 0
        tier = (s.tier or 1) if s is not None else 1

        # The milestones, one cell each: "T4 t6". Reached tiers go quiet,
        # the NEXT tier to hit sits on a little plate, the rest wait.
        # expected = the tier the curve says you should hold right now.
        tiers = sorted(bucket["curve"])
        expected = max([1] + [t for t in tiers if turn >= bucket["curve"][t]])
        nxt = min((t for t in tiers if t > tier), default=None)
        x = 14
        for t in tiers:
            fill = DIM if tier >= t else (TEXT if t == nxt else SOFT)
            if t == nxt:
                rrect(c, x - 5, y + 2, x + 60, y + 20, 6,
                      fill=PANEL_HI, outline="")
            c.create_text(x, y + 11, text=f"T{t}", anchor="w",
                          fill=fill, font=F_NAME)
            c.create_text(x + 24, y + 11, text=f"t{bucket['curve'][t]}",
                          anchor="w", fill=fill, font=F_SUB)
            x += 72
            if x > self.WIDTH - 58 and t != tiers[-1]:
                x, y = 14, y + 22
        y += 24

        # The judgement line. Health OUTRANKS the curve: below the caution
        # threshold the right move is no longer "keep the schedule", it is
        # "stop leveling and survive" - the strategy switch the research
        # named as the number one rule.
        low = hp is not None and rules and hp < rules["caution"]
        if turn:
            if low:
                danger = hp < rules["danger"]
                verdict = rules["danger_note" if danger else "caution_note"]
                col = BAD if danger else AMBER
            elif tier > expected:
                # GOOD, not ACCENT: ahead-of-schedule is a good state, and
                # ACCENT is reserved for clickable / yours.
                verdict, col = f"ahead of curve (T{tier} on t{turn})", GOOD
            elif tier == expected:
                verdict, col = "on curve", GOOD
            else:
                verdict, col = f"behind: curve says T{expected} now", BAD
            c.create_text(14, y + 2, anchor="nw", fill=col, font=F_SUB,
                          text=fit_text(verdict, self.WIDTH - 24))
            y += 16

        note = (bucket.get("note") or "").strip()
        if note:
            # Two short lines of the bucket's own advice.
            words, line1 = note.split(), ""
            while words and len(line1) + len(words[0]) < 36:
                line1 += ("" if not line1 else " ") + words.pop(0)
            c.create_text(14, y + 2, anchor="nw", fill=DIM, font=F_CHIP,
                          text=line1)
            y += 12
            rest = " ".join(words)
            if rest:
                c.create_text(14, y + 2, anchor="nw", fill=DIM, font=F_CHIP,
                              text=fit_text(rest, self.WIDTH - 24))
                y += 12
        return y + 6
