"""COUNTERS window - the numbers the game keeps about YOU, and nothing else.

One dense strip along the top of the right column: the turn, the gold you have
left out of the gold you get this turn, gold already promised for next turn,
your tavern tier and what the next tier costs RIGHT NOW, the stacking tavern
buffs, and what your board is made of.

Every number here is a counter Hearthstone itself writes into Power.log. None
of them is derived from a model, a stats feed or a guess, so a blank slot means
"the log has not said yet" and is drawn as a dash - never as a zero.

THE TAGS, AND THE LINE THAT PROVES EACH ONE
-------------------------------------------
All values are taken from the PowerTaskList copy only (the copy that is in sync
with the screen). GameState writes the same tags seconds early - taking gold or
tier from it would show next turn's numbers over this turn's shop. Identity
lines (``PlayerID=n, PlayerName=x``) are read from either copy: they are not a
lifecycle signal, they are who-am-I.

Written against the local player's PLAYER entity (``Entity=<battletag>``):

  RESOURCES                          the gold this turn gives you
  RESOURCES_USED                     how much of it you have spent
  TEMP_RESOURCES                     one-off gold on top (a coin, a trinket)
  BACON_PLAYER_EXTRA_GOLD_NEXT_TURN  gold already banked for NEXT turn.
                                     Measured 2026-08-13: ZERO occurrences in
                                     a full live session (3 games) - the
                                     current patch does not write it. Kept for
                                     old logs; a live source for "next turn's
                                     gold" is still wanted and needs a game
                                     that actually banks some to mine it from.
  BACON_ELEMENTAL_BUFFATKVALUE       the elemental buff, attack half. In
  BACON_ELEMENTAL_BUFFHEALTHVALUE    current games this pair tracks a small
                                     per-application size, NOT the total the
                                     game's tooltip shows - the totals moved
                                     to accumulator enchantments (see
                                     SHOPBUFF_PREFIX below), and these two are
                                     drawn only when no accumulator exists.
  BACON_BLOODGEMBUFFATKVALUE         your Blood Gem size, attack half
  BACON_BLOODGEMBUFFHEALTHVALUE      ... and its health half
  PLAYER_TECH_LEVEL                  your tavern tier (also written on the hero)

Written against an entity that carries ``player=<your id>``:

  PLAYER_TECH_LEVEL                  on your hero, zone=PLAY
  BACON_MAX_PLAYER_TECH_LEVEL        the ceiling this lobby allows
  PLAYER_TRIPLES                     triples earned so far, on your hero
  COST   on cardId=TB_BaconShopTechUp0N_Button, zone=PLAY
                                     the LIVE price of the next tavern tier -
                                     the button is re-created every turn at the
                                     base price and then discounted by a
                                     TAG_CHANGE, so last-write-wins is the price
  BACON_FREE_REFRESH_COUNT           free rerolls, on the Refresh button
  BACON_TURNS_LEFT_TO_DISCOVER_TRINKET
                                     on BG30_Trinket_1st / _2nd while zone=PLAY

Written against the game itself:

  TAG_CHANGE Entity=GameEntity tag=TURN
                                     Hearthstone counts TWO turns per
                                     Battlegrounds round: the ODD value is your
                                     recruit phase, the EVEN value after it is
                                     that round's fight. Measured over one real
                                     log (7 games): gold was SPENT on an odd
                                     TURN 415 times and on an even TURN 0 times,
                                     refilled 58 times on odd and 0 on even, and
                                     every one of 164 combats started on an even
                                     TURN. So the turn a player counts is
                                     (TURN + 1) // 2, and TURN 1 is the first
                                     shop (3 gold), not hero select - the draft
                                     happens before TURN is written at all.

NOT included, because no log line proves them: any per-tribe buff counter other
than elemental and Blood Gem (the tag universe has none), and a per-tribe count
of your own board - the log cannot give a trustworthy board, so those counts
come from the ``board`` event, which the reader builds from the memory reader
during RECRUIT only.

WHERE THE LINES COME FROM
-------------------------
If the reader ever pushes a ``counters`` event, this window uses it and stops
reading anything itself. Until then it tails Power.log on its own daemon
thread: read-only, bounded backfill, no second copy of any other window's
logic. The thread is started from ``tick()``, which only ever runs inside the
live overlay - so the test harnesses (headless, and the render pass that never
starts the manager poll) never touch the disk.

Lifecycle: open while any counter is known for the current game, closed before
that and reset by ``game``. It has no combat/tavern trigger of its own on
purpose - counters are true in both phases, and keying them to a phase is how
a surface ends up describing a moment that is not on screen. Repainting is
driven off the manager's own poll, so no extra timer is added and the paint
always happens on the Tk thread; the feed only ever assigns whole values to
the state (the same shape as the memory reader's board), so the worst a race
can do is show one counter a single frame ahead of its neighbour.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import bgtracker as bg

from .base import (AMBER, DIM, F_CHIP, F_NAME, F_SUB, GOOD, SOFT, TEXT,
                   TRIBE_COLOR, BaseWindow, advance)

# The screen-synced copy. Every VALUE below is taken from it and nothing else.
PTL = "PowerTaskList"

# TAG_CHANGE Entity=<battletag|GameEntity|[bracket]> tag=X value=N
# The bracket alternative is matched up to its own "player=N]" because entity
# names legitimately contain brackets ("Bacon_Free_Refresh_Player_Ench [DNT]").
# The plain alternative is lazy-up-to-" tag=" rather than \S+, because entity
# names carry spaces: the live log writes "TAG_CHANGE Entity=Bartender Bob
# tag=..." - and a BATTLETAG with a space would have made every player tag
# unreadable for that user under the old \S+.
TAGCHANGE_RE = re.compile(
    r"TAG_CHANGE Entity=(?P<ent>\[.*?player=\d+\]|.+?) "
    r"tag=(?P<tag>[A-Z0-9_]+) value=(?P<val>-?\d+)")
BRACKET_RE = re.compile(
    r"^\[entityName=(?P<name>.*) id=(?P<id>\d+) zone=(?P<zone>\w+) "
    r"zonePos=(?P<pos>-?\d+) cardId=(?P<card>[\w_]*) player=(?P<player>\d+)\]$")
# A FULL_ENTITY / SHOW_ENTITY header followed by indented bare "tag=" lines.
# This is how a freshly created entity states its opening values - it is what
# makes the tavern-upgrade price appear the moment the overlay starts mid-game
# instead of one turn later.
BLOCK_RE = re.compile(r"(?:FULL_ENTITY|SHOW_ENTITY) - Updating (?P<ent>\[.*?player=\d+\])")
BARE_TAG_RE = re.compile(r"^D [\d:.]+ \w+\.DebugPrintPower\(\) - +"
                         r"tag=(?P<tag>[A-Z0-9_]+) value=(?P<val>-?\d+)\s*$")
# The log states the player-id -> battletag mapping outright. Same shape the
# reader uses for the extra-gold tag; the battletag is only ever held in memory
# to match lines, and is never drawn or written anywhere. Name to end of line,
# not \S+: a battletag with a space would otherwise be stored truncated and
# could then never equal the entity spelling on any tag line.
PLAYERNAME_RE = re.compile(r"PlayerID=(\d+), PlayerName=(.+?)\s*$")
PLAYERNAME_BYTES = re.compile(rb"PlayerID=(\d+), PlayerName=(.+?)\s*$",
                              re.MULTILINE)
DRAGBUY = "TB_BaconShop_DragBuy"
TECHUP_RE = re.compile(r"^TB_BaconShopTechUp0*(\d+)_Button$")
TRINKET_SLOT = {"BG30_Trinket_1st": "lesser", "BG30_Trinket_2nd": "greater"}

# Tags read off the local player's own entity, by battletag.
PLAYER_TAGS = {
    "RESOURCES": "gold_base",
    "RESOURCES_USED": "gold_used",
    "TEMP_RESOURCES": "gold_temp",
    "BACON_PLAYER_EXTRA_GOLD_NEXT_TURN": "extra_next",
    "PLAYER_TECH_LEVEL": "tier",
    "BACON_ELEMENTAL_BUFFATKVALUE": "elem_atk",
    "BACON_ELEMENTAL_BUFFHEALTHVALUE": "elem_hp",
    "BACON_BLOODGEMBUFFATKVALUE": "gem_atk",
    "BACON_BLOODGEMBUFFHEALTHVALUE": "gem_hp",
}
# Tags read off an entity we own, i.e. one whose bracket says player=<our id>.
# Each names the zone it is only trusted in: a hero in SETASIDE is a draft
# option, and a trinket in GRAVEYARD has already been spent.
OWNED_TAGS = {
    "PLAYER_TECH_LEVEL": ("tier", "PLAY"),
    "BACON_MAX_PLAYER_TECH_LEVEL": ("max_tier", "PLAY"),
    "PLAYER_TRIPLES": ("triples", "PLAY"),
    "BACON_FREE_REFRESH_COUNT": ("free_rolls", "PLAY"),
}

# The standing tavern buffs of the CURRENT game patch live on hidden
# player-attached accumulator enchantments, not on the player tags above.
# Measured live 2026-08-13 (elemental game): the game's own tooltip
# said +59/+54 while BACON_ELEMENTAL_BUFF* on the player entity read 3/4 - the
# legacy pair no longer carries the total. The totals were on two enchantments
# owned by player=2, in TAG_SCRIPT_DATA_NUM_1 (attack) and _NUM_2 (health):
#
#   cardId BG_ShopBuff_Elemental        "your Elementals in the Tavern have
#                                        +X/+Y" (Dancing Barnstormer's line;
#                                        the suffix names the tribe)
#   cardId BG34_854pe, entityName        a per-refresh accumulator (Waveling)
#     "Random minion Tavern Minion       that stamps its running total onto
#      Buff Player Ench [DNT]"           one tavern minion as a visible
#                                        enchantment (BG34_854e, "Eastern
#                                        Winds") - the stamped copy's NAME is
#                                        what the player sees, so it is what
#                                        the chip is labelled with.
#
# The BG_ShopBuff_ prefix is the general family; the "...pe" + "Tavern Minion
# Buff" pair identifies the stamping kind without hardcoding one card.
SHOPBUFF_PREFIX = "BG_ShopBuff_"
STAMPER_NAME = "Tavern Minion Buff"
ACCUM_TAGS = {"TAG_SCRIPT_DATA_NUM_1": "atk", "TAG_SCRIPT_DATA_NUM_2": "hp"}
# The same totals (and RESOURCES) are mirrored onto a bracketed enchantment,
# cardId Bacon_TagTransferPlayerE, one step behind the battletag entity. It is
# read as a REDUNDANT source for the player tags: for a battletag the log
# spells strangely, the mirror is the only copy that still attributes.
TAGTRANSFER = "Bacon_TagTransferPlayerE"

_NAME_TRIBES = None


def name_tribes() -> dict:
    """minion name -> its tribes, from the LIVE card pool (cached a day by
    bgtracker). Offline with no cache this is empty and the tribe chips simply
    do not appear."""
    global _NAME_TRIBES
    if _NAME_TRIBES is None:
        try:
            _NAME_TRIBES = {m["name"]: set(m["races"]) for m in bg.bg_pool()}
        except Exception:
            _NAME_TRIBES = {}
    return _NAME_TRIBES


def tribe_counts(names) -> tuple:
    """(tribe -> how many of them you have, how many count as every tribe).

    An "ALL" minion (an Amalgam) is counted on its own instead of being added
    to all ten - inflating a tribe count would be inventing a number.
    """
    tribes, wild = {}, 0
    lookup = name_tribes()
    for nm in names or ():
        rs = lookup.get(nm)
        if not rs:
            continue
        if "ALL" in rs:
            wild += 1
            continue
        for r in rs:
            if r in TRIBE_COLOR:
                tribes[r] = tribes.get(r, 0) + 1
    return tribes, wild


class CounterState:
    """Every counter the log states about you, for ONE game.

    A pure function of the lines fed to it: no clock, no Tk, no threads. That
    is what lets it be replayed against a real Power.log and checked against
    the log by hand.
    """

    def __init__(self):
        self.reset()

    # -------------------------------------------------------------- lifecycle

    def reset(self):
        """Forget everything, including who we are."""
        self.id_names = {}
        self.new_game()

    def new_game(self):
        """A fresh game: every counter goes, and so does the player id (it is
        re-issued each game). The id -> battletag MAP is kept: the log states
        it once, before the first TURN is ever written, so throwing it away
        here would leave us unable to name ourselves for the whole game."""
        self.player = None          # our player id, as the log spells it
        self.name = None            # our battletag; used to match, never shown
        self.turn = None            # raw GameEntity TURN (2 per BG round)
        self.gold_base = None
        self.gold_used = 0
        self.gold_temp = 0
        self.extra_next = 0
        self.tier = None
        self.max_tier = None
        self.triples = 0
        self.free_rolls = 0
        self.upgrade = {}           # tavern tier -> what it costs right now
        self.trinket_in = {}        # "lesser"/"greater" -> turns left
        self.elem_atk = self.elem_hp = 0
        self.gem_atk = self.gem_hp = 0
        self.shop_buffs = {}        # accumulator entity id -> {card, label,
                                    # atk, hp} - the standing tavern buffs
        self.hero = None            # OUR hero's cardId, from its entity
                                    # entering PLAY at the draft's end
        self.hero_eid = None        # ...and that entity's id: health tags
                                    # are followed BY ID, because during a
                                    # fight "player=ours" carries the
                                    # opponent's mirrored hero too
        self.hero_health = None     # HEALTH / DAMAGE / ARMOR on our hero;
        self.hero_damage = 0        # effective_hp derives from the three
        self.hero_armor = 0
        self.board = []             # minion names, from the reader's board event
        self.version = 0
        self._blk = None
        self._pending = {}          # writes seen mid-fight, held until recruit

    def _bump(self, field, value):
        if getattr(self, field) != value:
            setattr(self, field, value)
            self.version += 1

    # ------------------------------------------------------------- properties

    @property
    def bg_turn(self):
        """The turn a player counts. Hearthstone writes two per round."""
        if not self.turn:
            return None
        return (self.turn + 1) // 2

    @property
    def in_combat(self):
        """Even TURN values are the fight that closes the round."""
        return bool(self.turn and self.turn % 2 == 0)

    @property
    def effective_hp(self):
        """What the player calls their health: health minus damage plus
        armor. None until the log has stated the hero's health at all."""
        if self.hero_health is None:
            return None
        return self.hero_health - self.hero_damage + self.hero_armor

    @property
    def gold(self):
        if self.gold_base is None:
            return None
        return max(0, self.gold_base + self.gold_temp - self.gold_used)

    @property
    def gold_max(self):
        if self.gold_base is None:
            return None
        return self.gold_base + self.gold_temp

    @property
    def next_tier(self):
        """The tier the tavern button is currently offering, if any."""
        if self.tier is None:
            return None
        higher = [t for t in self.upgrade if t > self.tier]
        return min(higher) if higher else None

    @property
    def next_cost(self):
        nxt = self.next_tier
        return self.upgrade.get(nxt) if nxt is not None else None

    @property
    def at_max_tier(self):
        return bool(self.tier and self.max_tier and self.tier >= self.max_tier)

    def known(self) -> bool:
        """Is there anything real to draw? Never true off a blank state."""
        return bool(self.bg_turn or self.gold_base is not None or self.tier
                    or self.board or self.extra_next)

    def effects(self):
        """The standing tavern effects, as data: {card, label, atk, hp, kind}.

        ``card`` is the accumulator's cardId (or None for the legacy player
        tags), ``kind`` one of shopbuff/stamper/legacy/gem. The pills window
        and the strip both read this one list, so they can never disagree.
        """
        out = []
        elem_accum = False
        for eid in sorted(self.shop_buffs):
            rec = self.shop_buffs[eid]
            if not (rec["atk"] or rec["hp"]):
                continue
            if rec["card"].startswith(SHOPBUFF_PREFIX):
                if rec["label"] == "ELEMENTAL":
                    elem_accum = True
                out.append({"card": rec["card"], "label": rec["label"],
                            "atk": rec["atk"], "hp": rec["hp"],
                            "kind": "shopbuff"})
            else:
                out.append({"card": rec["card"],
                            "label": rec["label"] or "Tavern buff",
                            "atk": rec["atk"], "hp": rec["hp"],
                            "kind": "stamper"})
        if (self.elem_atk or self.elem_hp) and not elem_accum:
            out.append({"card": None, "label": "ELEMENTAL",
                        "atk": self.elem_atk, "hp": self.elem_hp,
                        "kind": "legacy"})
        if self.gem_atk or self.gem_hp:
            out.append({"card": None, "label": "Blood Gems",
                        "atk": self.gem_atk, "hp": self.gem_hp,
                        "kind": "gem"})
        return out

    # ------------------------------------------------------------------ input

    def set_board(self, names):
        self.board = list(names or [])
        self.version += 1

    def apply(self, payload):
        """Merge a reader-pushed ``counters`` payload. Unknown keys ignored."""
        if not isinstance(payload, dict):
            return
        for k, v in payload.items():
            if k in ("version", "_blk") or not hasattr(self, k):
                continue
            self._bump(k, v)

    def feed(self, line: str):
        """One raw Power.log line. Returns True when something changed."""
        before = self.version

        # Who are we? The mapping is stated in plain text and is not a
        # lifecycle signal, so either copy may carry it.
        if "PlayerID=" in line:
            m = PLAYERNAME_RE.search(line)
            if m:
                self.id_names[m.group(1)] = m.group(2)
                self._resolve()

        if PTL not in line:
            return self.version != before

        if "FULL_ENTITY" in line or "SHOW_ENTITY" in line:
            self._entity_line(line)
            return self.version != before

        m = TAGCHANGE_RE.search(line)
        if m:
            self._blk = None
            self._tag(m.group("ent"), m.group("tag"), int(m.group("val")))
            return self.version != before

        bare = BARE_TAG_RE.match(line)
        if bare is not None:
            if self._blk is not None:
                self._tag(self._blk, bare.group("tag"), int(bare.group("val")))
            return self.version != before

        self._blk = None
        return self.version != before

    # ----------------------------------------------------------------- detail

    def _resolve(self):
        if self.player is not None and self.name is None:
            self.name = self.id_names.get(self.player)

    def _entity_line(self, line):
        """A FULL_ENTITY header: learn who we are, and open a tag block.

        Two independent ways to be named, measured on a real log: the hero
        draft deals OUR options into zone=HAND and it happens BEFORE the first
        TURN is written; and a drag-to-buy token is re-created for us in every
        single recruit phase (seen at TURN=1 and again at TURN=3), so the id is
        recoverable within one turn even if the overlay starts mid-game.

        A draft naming a DIFFERENT player id is a new game - that is the
        earliest honest new-game signal there is, earlier than TURN resetting.
        """
        e = bg.ENTITY_RE.match(line)
        if e is not None:
            card, zone = e["card"], e["zone"]
            draft = zone == "HAND" and "HERO_" in card
            if draft and self.player is not None and e["player"] != self.player:
                self.new_game()
            if (draft or card == DRAGBUY) and self.player is None:
                self.player = e["player"]
                self.version += 1
                self._resolve()
            # The hero WE ended up with: its entity enters zone=PLAY when the
            # draft resolves, during a recruit phase. First one wins (a hero
            # swap mid-game is rare enough to not chase); combat is excluded
            # because the fight mirrors the opponent's hero into our
            # controller. This is what the curve window keys on.
            if (self.hero is None and "HERO_" in card and zone == "PLAY"
                    and not self.in_combat and self.player is not None
                    and e["player"] == self.player):
                self.hero_eid = e["id"]
                self._bump("hero", card)
        b = BLOCK_RE.search(line)
        self._blk = b.group("ent") if b else None

    def _tag(self, ent, tag, val):
        if ent == "GameEntity":
            if tag == "TURN":
                if self.turn is not None and val < self.turn:
                    self.new_game()       # the counter restarted: a new game
                self._bump("turn", val)
                if val % 2 and self._pending:
                    # The shop is back. Everything the fight wrote lands now,
                    # last-write-wins - and the last write of a fight is always
                    # your own state restored, so this is the honest value AND
                    # it keeps the gold the fight banked for you.
                    for f, v in self._pending.items():
                        self._bump(f, v)
                    self._pending.clear()
            return

        if not ent.startswith("["):
            if self.name is not None and ent == self.name:
                field = PLAYER_TAGS.get(tag)
                if field is None:
                    return
                if self.in_combat:
                    # A fight rewrites your own player entity as it mirrors the
                    # match: measured inside one fight, our tier went 4 -> 0 ->
                    # 6 -> 4 and the Blood Gem buff +11/+8 -> +0/+0 -> +11/+8.
                    # Hold it all until the shop is back rather than show a
                    # number that belongs to whoever we are fighting.
                    self._pending[field] = val
                    return
                self._bump(field, val)
            return

        br = BRACKET_RE.match(ent)
        if br is None or self.player is None or br.group("player") != self.player:
            return
        # OUR hero's health, followed by ENTITY ID - the one bracket read
        # that outranks the combat freeze, because the id is unambiguous
        # (the fight mirrors the opponent's hero into our controller, but as
        # a DIFFERENT entity). Damage lands at the fight's end, i.e. during
        # an even TURN, so it rides the same pending flush the player tags
        # use and appears with the next shop.
        if (self.hero_eid is not None and br.group("id") == self.hero_eid
                and tag in ("HEALTH", "DAMAGE", "ARMOR")):
            field = "hero_" + tag.lower()
            if self.in_combat:
                self._pending[field] = val
            else:
                self._bump(field, val)
            return
        if self.in_combat:
            # DURING A FIGHT "player=<our id>" stops meaning "ours": the
            # opponent's hero and trinkets are mirrored into our controller.
            # Measured inside one real fight, our tier read 3, then 2 (the
            # opponent's), then 3 again, and the trinket countdown jumped
            # 3 -> 0 -> 8 -> 2. Nothing here can legitimately change mid-fight,
            # so the recruit-phase values simply stand - the same freeze the
            # reader already applies to your board.
            return
        card, zone = br.group("card"), br.group("zone")

        # The standing tavern buffs (see the SHOPBUFF_PREFIX block above).
        # PLAY and SETASIDE both accepted: an accumulator is a hidden
        # bookkeeping enchantment and the client has parked it in either.
        if tag in ACCUM_TAGS and zone in ("PLAY", "SETASIDE"):
            self._accum(br.group("id"), card, br.group("name"),
                        ACCUM_TAGS[tag], val)
            return
        # A stamping accumulator's visible copy ("Eastern Winds") names the
        # buff the player is actually shown - claim it as the chip label.
        if card and card.endswith("e") and self.shop_buffs:
            self._accum_name(card, br.group("name"))

        # The TagTransfer mirror: redundant copies of the player tags. Applied
        # through the same field map, so whichever spelling the log manages to
        # attribute first wins and the other only ever restates it.
        if card == TAGTRANSFER:
            field = PLAYER_TAGS.get(tag)
            if field is not None:
                self._bump(field, val)
            return

        owned = OWNED_TAGS.get(tag)
        if owned is not None and zone == owned[1]:
            self._bump(owned[0], val)
            return
        if tag == "COST" and zone == "PLAY":
            up = TECHUP_RE.match(card or "")
            if up is not None:
                # The button is re-created each turn at the base price and then
                # discounted, so the newest write is the live price.
                tier = int(up.group(1))
                # Every re-creation writes COST=0 and immediately overwrites it
                # with the real price (measured: id=278 got 0 then 5, then the
                # next turn's button got 4). A free tavern-up is real, but the
                # price only ever walks DOWN one per turn, so a genuine 0 can
                # only arrive from 1 - anything else is that transient.
                if val == 0 and self.upgrade.get(tier) != 1:
                    return
                if self.upgrade.get(tier) != val:
                    self.upgrade[tier] = val
                    self.version += 1
            return
        if tag == "BACON_TURNS_LEFT_TO_DISCOVER_TRINKET" and zone == "PLAY":
            slot = TRINKET_SLOT.get(card)
            if slot is not None and self.trinket_in.get(slot) != val:
                self.trinket_in[slot] = val
                self.version += 1

    def _accum(self, eid, card, name, half, val):
        """One script-data write on an entity we own: is it a tavern buff?

        Only the two known accumulator shapes are believed - script data is a
        general-purpose scratchpad and most of it is not a buff. An unknown
        enchantment writing script data is silently ignored, which is the
        honest failure: no chip, rather than a chip with a wrong meaning.
        """
        if card.startswith(SHOPBUFF_PREFIX) and not card.endswith("_Ench"):
            # The bare family cardId is the accumulator; the game stamps a
            # per-minion copy with _Ench appended ("Elemental Tavern Buffed",
            # 16 of them in one replayed game) that carries the same numbers
            # and would each have shown up as its own chip.
            label = card[len(SHOPBUFF_PREFIX):].upper()   # the tribe
        elif card.endswith("pe") and STAMPER_NAME in (name or ""):
            label = None                    # named by its visible stamp later
        else:
            return
        rec = self.shop_buffs.get(eid)
        if rec is None:
            rec = self.shop_buffs[eid] = {"card": card, "label": label,
                                          "atk": 0, "hp": 0}
        if rec[half] != val:
            rec[half] = val
            self.version += 1

    def _accum_name(self, card, name):
        """A visible stamped enchantment sighted: its cardId is the stamper's
        minus the 'p' (BG34_854pe stamps BG34_854e), and its NAME is the words
        on the player's screen."""
        if not name or name.startswith("UNKNOWN"):
            return
        for rec in self.shop_buffs.values():
            if (rec["label"] is None and rec["card"].endswith("pe")
                    and rec["card"][:-2] + "e" == card):
                rec["label"] = name
                self.version += 1


class CounterFeed(threading.Thread):
    """Tails Power.log into a CounterState, read-only, on its own thread.

    Bounded backfill: the tail of the current log is replayed first so that
    starting the overlay mid-game fills the strip immediately, and the SAME
    handle then keeps reading - so no line written during the backfill is
    lost. A rotation (Hearthstone starting a new log) restarts the state.

    How far back it starts is not a guess: a cheap chunked pass finds the LAST
    ``PlayerID=n, PlayerName=x`` in the file, which the client writes once per
    game in its opening dump, and the replay starts there - i.e. at the top of
    the game you are actually in. Two things forced that:

      * the map itself. A fixed 32 MB tail found it in one of three real logs
        and left the other two with no gold, no tier ceiling and no buffs at
        all, because nothing on the player entity can be attributed without it.
      * RESOURCES only fires when it CHANGES, so once your gold caps it is
        never restated. Joining a capped game mid-way from a fixed tail leaves
        the maximum-gold number permanently unknown.

    BACKFILL caps the work if that dump is very far back (a marathon session
    in one log); the scan decodes nothing, so the pass itself is cheap.
    """

    daemon = True
    BACKFILL = 128 * 1024 * 1024     # hard cap on how much history to replay
    POLL = 0.25

    def __init__(self, state: CounterState, path=None, backfill=None, once=False):
        super().__init__()
        self.state = state
        self.path = path
        self.backfill = self.BACKFILL if backfill is None else backfill
        self.once = once             # replay to EOF and stop (tests)
        self.error = None
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self._run()
        except Exception as e:                    # a dead feed must not shout
            self.error = str(e)

    CHUNK = 8 << 20
    OVERLAP = 96                     # a match may straddle two chunks

    def _scan_identity(self, f):
        """Collect every ``PlayerID=n, PlayerName=x``, newest wins, and return
        the byte offset of the last one - the top of the current game.

        Chunked bytes search: a chunk with no match is rejected by one
        substring test, so this reads the file without decoding it.
        """
        f.seek(0)
        tail, pos, last = b"", 0, 0
        while True:
            chunk = f.read(self.CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            if b"PlayerID=" in buf:
                for m in PLAYERNAME_BYTES.finditer(buf):
                    self.state.id_names[m.group(1).decode()] = \
                        m.group(2).decode("utf-8", "ignore")
                    last = max(last, pos + m.start())
            keep = buf[-self.OVERLAP:]
            pos += len(buf) - len(keep)
            tail = keep
        return last

    def _run(self):
        path = self.path or bg.newest_power_log()
        if path is None:
            self.error = "no Power.log"
            return
        path = Path(path)
        f = open(path, "rb")
        try:
            size = path.stat().st_size
            if self.backfill and size > self.backfill:
                # Start at the top of the current game, unless that is further
                # back than we are willing to read.
                start = max(self._scan_identity(f), size - self.backfill)
                f.seek(start)
                f.readline()                      # drop the half line we landed in
            last_check = 0.0
            while not self._stop:
                pos = f.tell()
                raw = f.readline()
                if raw:
                    if not raw.endswith(b"\n"):
                        f.seek(pos)               # still being written; wait
                    else:
                        # Cheap byte prefilter so most of the log is never
                        # decoded: tag writes, the id->battletag map, and the
                        # *_ENTITY headers that name the local player.
                        if (b"tag=" in raw or b"PlayerID=" in raw
                                or b"_ENTITY" in raw):
                            self.state.feed(raw.decode("utf-8", "ignore"))
                        continue
                if self.once:
                    return
                time.sleep(self.POLL)
                now = time.monotonic()
                if now - last_check < 2.0:
                    continue
                last_check = now
                newest = bg.newest_power_log()
                if newest and newest != path:
                    f.close()
                    path = newest
                    f = open(path, "rb")
                    self.state.reset()
        finally:
            try:
                f.close()
            except Exception:
                pass


class CountersWindow(BaseWindow):
    KEY = "counters"
    TITLE = "COUNTERS"
    COLUMN = "right"
    DY = 8
    RESERVE = 62
    MAX_H = 54                      # the band above COMBAT (y+70); never spills
    WIDTH = 244                     # tightened with the columns below, and
                                    # with GOLD gone to its own window
                                    # (founder: "too big", 2026-08-15)
    EVENTS = ("counters", "board", "gold", "game")

    ROW_H = 15
    GAP = 5

    def __init__(self, app):
        super().__init__(app)
        self.state = CounterState()
        self._feed = None
        self._external = False      # a reader is pushing 'counters' events
        self._seen = -1

    # ------------------------------------------------------------- lifecycle

    def reset(self):
        # new_game(), not reset(): the reader announces a game on the hero
        # draft, which the log writes AFTER it has stated the id -> battletag
        # map for that game. Throwing the map away here would leave the strip
        # unable to recognise its own player for the whole game.
        self.state.new_game()
        self._seen = self.state.version
        self.hide()

    def on_event(self, name, payload):
        if name == "game":
            self.reset()
            return
        if name == "counters":
            # A reader took over: stop reading the log ourselves rather than
            # have two sources disagree about the same number.
            self._external = True
            self._stop_feed()
            self.state.apply(payload)
        elif name == "board":
            self.state.set_board((payload or {}).get("names"))
        elif name == "gold":
            # The reader's gold event is BACON_PLAYER_EXTRA_GOLD_NEXT_TURN. Our
            # own feed reads the same tag from the screen-synced copy, so it
            # wins; this is only the fallback when we are not reading at all.
            if self._feed is None:
                self.state.extra_next = payload or 0
                self.state.version += 1
        self._sync()

    def tick(self, rect, game_front):
        # Started here and nowhere else: tick() only runs under the live
        # manager poll, so no test harness ever opens the log.
        if (not self.headless and not self._external and self._feed is None
                and rect is not None):
            self._start_feed()
        if self.state.version != self._seen:
            self._sync()
        super().tick(rect, game_front)

    def _start_feed(self):
        try:
            self._feed = CounterFeed(self.state)
            self._feed.start()
        except Exception:
            self._feed = None

    def _stop_feed(self):
        if self._feed is not None:
            try:
                self._feed.stop()
            except Exception:
                pass
            self._feed = None

    def _sync(self):
        self._seen = self.state.version
        if self.state.known():
            self.show()
        else:
            self.hide()

    # --------------------------------------------------------------- drawing
    #
    # The layout is HSReplay's, looked up and copied (their HDT overlay
    # screenshot, measured 2026-08-14): stats are LABELLED COLUMNS - a tiny
    # muted label over a plain bright value ("Start" over "5,095"), in a flat
    # box, no pills, no chips - and the standing effects are plain text rows
    # with only the VALUE coloured. The founder's rule: copy how the shipped
    # trackers handle it, never invent.

    def _stats(self):
        """The labelled columns, importance order. Always the first three."""
        s = self.state
        gold = s.gold
        # GOLD is NOT a column here any more: it is its own movable window
        # (ui/gold.py), split out on founder feedback 2026-08-15 - it is the
        # one counter looked at every turn, so it stopped being the first
        # column of a strip. Both read this same state, so they agree.
        cols = [("TIER", f"{s.tier}" if s.tier else "—",
                 TEXT if s.tier else DIM)]
        if s.at_max_tier:
            cols.append(("UPGRADE", "max", DIM))
        elif s.next_cost is not None:
            afford = gold is not None and gold >= s.next_cost
            cols.append(("UPGRADE", f"{s.next_cost}g", GOOD if afford else SOFT))
        else:
            cols.append(("UPGRADE", "—", DIM))
        if s.triples:
            cols.append(("TRIPLES", f"{s.triples}", SOFT))
        if s.free_rolls:
            cols.append(("ROLLS", f"{s.free_rolls} free", GOOD))
        if s.extra_next:
            cols.append(("NEXT TURN", f"+{s.extra_next}g", GOOD))
        nxt = min((v for v in s.trinket_in.values() if v > 0), default=None)
        if nxt:
            cols.append(("TRINKET", f"in {nxt}", SOFT))
        return cols

    def draw(self, c):
        s = self.state
        turn = s.bg_turn
        dot = None if turn is None else (AMBER if s.in_combat else GOOD)
        y = self.header(c, f"turn {turn}" if turn else "turn —", DIM, dot=dot)

        if not s.known():
            c.create_text(14, y + 8, text="waiting for a game", anchor="w",
                          fill=DIM, font=F_SUB)
            return y + 22

        # The labelled columns: label at the top in the muted small type,
        # value under it in the plain bright one. Columns that stop fitting
        # drop from the right - the first three always fit.
        # One label line (F_CHIP) over one value line (F_SUB), at Tk's real
        # line boxes - measured, not hoped, after two rounds of the window
        # test catching painted ink below the panel. The standing effects
        # are not here any more: they are the BUFFS window's pills, movable
        # on their own, the way the reference draws each counter separately.
        x, limit = 12, self.WIDTH - 6
        for label, value, fill in self._stats():
            w = max(F_CHIP.measure(label), F_SUB.measure(value)) + 10
            if x + w > limit:
                break
            c.create_text(x, y, text=label, anchor="nw", fill=DIM,
                          font=F_CHIP)
            c.create_text(x, y + 8, text=value, anchor="nw", fill=fill,
                          font=F_SUB)
            x = x + w
        return y + 23
