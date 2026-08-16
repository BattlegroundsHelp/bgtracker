"""The counters, one tiny window each: an icon and its number, nothing else.

This is the shape the counters were always meant to have (founder, restated
2026-08-15): not a strip you have to aim at, and not a panel with a title bar
like the hero windows, but one micro window per number, each dragged wherever
its player wants it and each remembering where it was put. The reference
overlay does the same with its counters, and the BUFFS pills already worked
this way.

What a micro window is, exactly:

  * no header, no title, no reset link. An icon, a value, and its own edge
  * it appears only while it has something true to say and disappears the
    moment it does not - an empty micro window is clutter with a border
  * it owns no parser. Every number is read from the counters window's
    CounterState, the one source all these surfaces share, so no two of them
    can ever disagree about the same number
  * turning the COUNTERS window off in settings turns these off with it,
    because that is where the state and the log feed live. Same rule the
    BUFFS window has always followed

Each subclass says three things: which icon it wears, what its value is right
now, and what colour that value should be. Everything else lives here.
"""

from __future__ import annotations

from . import skin
from .base import (AMBER, DIM, F_NAME, GOOD, SOFT, TEXT, BaseWindow,
                   get_scale, shadow_text)

ICON_PX = 18            # base pixels; bitmaps bake at ICON_PX * get_scale()
PAD = 6


class MicroWindow(BaseWindow):
    """One counter. Subclasses set KEY, TITLE (the settings label), ICON, and
    implement value()."""

    COLUMN = "float"                # every one of them is movable
    RESERVE = 30
    MAX_H = 30
    WIDTH = 78
    EVENTS = ("game",)
    # The game's own icon first, our designed glyph second. Extracting is
    # per-user (tools/extract_game_assets.py) and never ships, so a fresh
    # install runs on the designed set until it is run - the window looks
    # different, never empty.
    ICON = ()                       # ("game/counter_x", "counter_x")
    BLURB = ""                      # the settings panel's one-liner

    def __init__(self, app):
        super().__init__(app)
        self._seen = -1

    # ------------------------------------------------------------ subclass
    def value(self, s):
        """(text, colour) for this state, or None to stay hidden."""
        raise NotImplementedError

    # ------------------------------------------------------------ plumbing
    def reset(self):
        # Re-arm the version watch: new_game() puts the state's version back
        # to 0, and a stale _seen could equal it and swallow the first update
        # of the next game (the trap the BUFFS window fell into twice).
        self._seen = -1
        self.hide()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()

    def _state(self):
        w = self.app.by_key.get("counters")
        return w.state if w is not None else None

    def tick(self, rect, game_front):
        s = self._state()
        if s is None:
            # The counters window is switched off - it is the only source
            # these have. Hide rather than freeze on the last number seen.
            self._seen = -1
            self.hide()
        elif s.version != self._seen:
            self._seen = s.version
            if s.known() and self.value(s) is not None:
                self.show()
            else:
                self.hide()
        super().tick(rect, game_front)

    def draw(self, c):
        s = self._state()
        got = self.value(s) if s is not None else None
        if got is None:
            return 20
        text, fill = got
        px = max(12, round(ICON_PX * get_scale()))
        icon = None
        for name in self.ICON:
            icon = skin.ui_icon(c, name, px)
            if icon is not None:
                break
        x, cy = PAD, 15
        if icon is not None:
            c.create_image(x, cy - ICON_PX // 2, image=icon, anchor="nw")
            x += ICON_PX + 5
        else:
            # No icon on disk: the label's first letters stand in, so the
            # window still says which number it is holding.
            c.create_text(x, cy, text=self.TITLE[:3].upper(), anchor="w",
                          fill=DIM, font=F_NAME)
            x += 28
        # The value wears a halo: these float over the board rather than over
        # a panel, so there is card art behind them as often as not.
        shadow_text(c, x, cy, text, fill, F_NAME, anchor="w")
        return 30


class GoldMicro(MicroWindow):
    KEY = "m_gold"
    TITLE = "Gold"
    BLURB = "The gold you have left, over what this turn gave you."
    ICON = ("game/counter_gold", "counter_gold")
    DY = 720

    def value(self, s):
        if s.gold is None:
            return None
        return f"{s.gold}/{s.gold_max}", AMBER if s.gold else DIM


class TierMicro(MicroWindow):
    KEY = "m_tier"
    TITLE = "Tavern tier"
    BLURB = "Your tavern tier."
    # The game's own tavern shield where it has been extracted
    # (tools/extract_game_assets.py); the drawn label stands in otherwise.
    ICON = ("game/shield",)
    DY = 754
    WIDTH = 62

    def value(self, s):
        if not s.tier:
            return None
        return str(s.tier), TEXT


class UpgradeMicro(MicroWindow):
    KEY = "m_upgrade"
    TITLE = "Upgrade cost"
    BLURB = "What the next tavern tier costs right now, green when you can afford it."
    ICON = ("game/counter_upgrade", "counter_upgrade")
    DY = 788

    def value(self, s):
        if s.at_max_tier:
            return "max", DIM
        if s.next_cost is None:
            return None
        afford = s.gold is not None and s.gold >= s.next_cost
        return f"{s.next_cost}g", GOOD if afford else SOFT


class TriplesMicro(MicroWindow):
    KEY = "m_triples"
    TITLE = "Triples"
    BLURB = "Triples earned so far. Hidden until you have one."
    ICON = ("game/star", "counter_triples")
    DY = 822
    WIDTH = 62

    def value(self, s):
        # Zero triples is not news; this stays away until there is one.
        if not s.triples:
            return None
        return str(s.triples), SOFT


class RollsMicro(MicroWindow):
    KEY = "m_rolls"
    TITLE = "Free rerolls"
    BLURB = "Free rerolls in hand. Hidden when there are none."
    ICON = ("counter_rolls",)
    DY = 856
    WIDTH = 62

    def value(self, s):
        if not s.free_rolls:
            return None
        return str(s.free_rolls), GOOD


class TrinketMicro(MicroWindow):
    KEY = "m_trinket"
    TITLE = "Trinket in"
    BLURB = "Turns until the next trinket is offered."
    ICON = ("game/counter_trinket", "counter_trinket")
    DY = 890
    WIDTH = 62

    def value(self, s):
        nxt = min((v for v in s.trinket_in.values() if v > 0), default=None)
        if not nxt:
            return None
        return str(nxt), SOFT


class TurnMicro(MicroWindow):
    KEY = "m_turn"
    TITLE = "Turn"
    BLURB = "The Battlegrounds turn, amber while a fight is on."
    ICON = ("counter_turn",)
    DY = 924
    WIDTH = 62

    def value(self, s):
        if not s.bg_turn:
            return None
        return str(s.bg_turn), AMBER if s.in_combat else TEXT


MICROS = (GoldMicro, TierMicro, UpgradeMicro, TriplesMicro, RollsMicro,
          TrinketMicro, TurnMicro)
