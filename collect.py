#!/usr/bin/env python3
"""
Own-data collector - the seed of an independent dataset.

Mines every finished Battlegrounds game out of Hearthstone's Power.log history
and appends one record per game to data/games.jsonl. It touches nothing live, so
you can run it any time (including while the overlay is running); it de-dupes on
the game's start position, so re-running only adds new games.

This is the honest path to not depending on anyone else's stats forever: once
enough games are collected (yours, and eventually other users'), the same
average-placement / comp numbers can be computed from our OWN play. Everything
here is the player's own gameplay data from their own client - fully ours to keep.

    python collect.py            # backfill + update data/games.jsonl
    python collect.py --stats    # print what we have so far

Fields per record (JSONL):
    {date, game_id, hero, place, duo, tribes, source_log,
     offered_heroes, offered_trinkets, picked_trinkets}
`duo` says whether the game was Duos (see DUO_RE) so the two modes can be
counted apart - they place 1st-4th and 1st-8th respectively, so one average over
both describes nothing. A record written before the detector existed has no
`duo` key: that means UNKNOWN, and it is left out of both feeds, not assumed.
`place` and `hero` are best-effort from the log; the memory reader fills the gaps
when the overlay records live (see WISHLIST). A record with a null field is still
kept - partial data still aggregates.

The three offer fields are what make PICK RATE and TRINKET numbers possible at
all: an average placement needs only the game's result, but "how often is this
taken when shown" needs the options you turned down. Field names match
server/aggregate.py exactly (hero_stats / trinket_stats read them by name).
"""

import argparse
import hashlib
import json
import os
import re
import urllib.request
import uuid
from collections import defaultdict
from pathlib import Path

import bgtracker as bg
from paths import APP_DIR, BUNDLE_DIR, frozen
from version import USER_AGENT, VERSION

# How the person reading the output actually runs this program. Telling a
# standalone-build user to "run python collect.py" is telling them to install
# the thing the build exists to avoid.
HOWTO = "collect.exe" if frozen() else "python collect.py"

# Next to the exe when frozen, next to this file from source - never inside
# PyInstaller's bundle, which the user cannot see and an update replaces.
DATA = APP_DIR / "data"
OUT = DATA / "games.jsonl"
CLIENT_ID_FILE = DATA / "client_id"

HERO_RE = re.compile(r"(BG\w+?_HERO_\w+|TB_BaconShop_HERO_\d+)")

# What `--local-feed` writes into sources.json: your own games, as the four
# tables the overlay reads. Module level because the settings panel offers the
# same switch, and two copies of these paths is two chances to point half the
# tool at a feed that is not there.
LOCAL_FEED = {
    "heroes": "data/feed/heroes-{mmr}-{time}.json",
    "trinkets": "data/feed/trinkets-{mmr}-{time}.json",
    "cards": "data/feed/cards-{mmr}-{time}.json",
    "comps": "data/feed/comps-{mmr}-{time}.json",
    # The same four tables built from your DUOS games only, which is what
    # `--duo` reads. Separate files, never mixed with the above.
    "heroes_duo": "data/feed/heroes-duo-{mmr}-{time}.json",
    "trinkets_duo": "data/feed/trinkets-duo-{mmr}-{time}.json",
    "cards_duo": "data/feed/cards-duo-{mmr}-{time}.json",
    "comps_duo": "data/feed/comps-duo-{mmr}-{time}.json",
}


# Tags print as INDENTED lines under an entity header, not keyed inline - so we
# track the "current entity" from the most recent header and attribute tags to it.
HDR_ID_RE = re.compile(r"(?:FULL_ENTITY - Creating ID=|FULL_ENTITY - Updating \[entityName=[^\]]*? id=|"
                       r"SHOW_ENTITY - Updating Entity=\[entityName=[^\]]*? id=|Player EntityID=)(\d+)")
HDR_NAME_RE = re.compile(r"(?:TAG_CHANGE Entity=|CHANGE_ENTITY - Updating Entity=)([^\[\s]+#\d+) tag=")


def file_battletag(lines):
    """Our battletag (constant across a session) = the PlayerName whose player
    has a real Battle.net account. Detected once per file, since the mapping line
    is often logged just outside a single game's CREATE_GAME slice."""
    real_pids = set()
    for line in lines:
        m = re.search(r"PlayerID=(\d+) GameAccountId=\[hi=(\d+)", line)
        if m and int(m.group(2)) > 0:
            real_pids.add(m.group(1))
    for line in lines:
        m = re.search(r"PlayerID=(\d+), PlayerName=(\S+#\d+)", line)
        if m and m.group(1) in real_pids:
            return m.group(2)
    return None


# The hero DRAFT is the one place the log identifies the local player beyond
# doubt: only OUR offered heroes are revealed by name into zone=HAND, and every
# draft line carries our player id. Battletag heuristics fail in Battlegrounds
# because every lobby is full of real Battle.net accounts (and in duos your
# partner's is in the same file), so "the player with a real account" is as
# likely to be someone else as you.
DRAFT_RE = re.compile(r"FULL_ENTITY - Updating \[entityName=[^\]]+? id=(\d+) "
                      r"zone=HAND zonePos=\d+ cardId="
                      r"(?:BG\w+?_HERO_\w+|TB_BaconShop_HERO_\d+)\S* player=(\d+)\]")
NAME_MAP_RE = re.compile(r"PlayerID=(\d+), PlayerName=(\S+#\d+)")


# ------------------------------------------------------------ solo or duos
# Duos is a different game, not a variant: eight players in four teams, a hero
# pool of its own, cards that only exist there - and, measured in his own logs,
# a leaderboard that runs 1..4 instead of 1..8. So a duos game averaged into the
# solo pool does not merely add noise, it drags every solo average toward a
# better-looking number that no solo player can reach. The two must be counted
# apart, which means every record has to say which it was.
#
# The signal: Hearthstone marks the lobby on the PLAYER entity itself -
# `tag=BACON_DUO_TEAMMATE_PLAYER_ID` and `tag=BACON_DUO_TEAM_ID`, written in the
# player block a few dozen lines after CREATE_GAME and re-written as TAG_CHANGEs
# throughout the game.
#
# Measured over the 33 finished games in six real Power.logs (2026-08-11):
#   BACON_DUO_TEAM*_ID tag          6 duos / 27 solo
#   GameType=GT_BATTLEGROUNDS_DUO   6 duos / 27 solo  - agrees with the tag 33/33
#   any BGDUO_ card seen in-game    6 duos / 27 solo  - agrees with the tag 33/33
#   a BGDUO_HERO_ cardId in-game    4 duos / 29 solo  - MISSES 2 real duos games
# So the duos hero-id shape is NOT the signal: two of the six duos games were
# played out entirely on heroes that also exist in solo. GameType is exact, but
# `DebugPrintGame() - GameType=` is printed BEFORE the CREATE_GAME line, i.e.
# outside the game slice this module cuts, and a game whose header rotated into
# the previous file would silently inherit the neighbour's mode. The tag is
# inside the slice, near its top, and repeats ~15 times per game, so even a
# slice that begins mid-game (a reconnect) still carries it. Hence the tag.
#
# Rejected on evidence, for the record: BACON_DUO_PASSABLE fired in 25 of 33
# games (it is a property printed on ordinary cards, solo included) and
# BACON_DUOS_PUNISH_LEAVERS in 32 of 33 (a lobby option, not a mode).
DUO_RE = re.compile(r"tag=BACON_DUO_TEAM(?:MATE_PLAYER)?_ID ")


# ------------------------------------------------------------ what's an offer

# Every choose-one dialog prints a GameState.DebugPrintEntityChoices block, and
# Entities[i] is the on-screen order. The header line carries "id=<n> Player=";
# the option lines are indented and carry "Entities[i]=[...]".
CHOICE_HDR_RE = re.compile(r"GameState\.DebugPrintEntityChoices\(\) - id=\d+ ")
CHOICE_ENT_RE = re.compile(
    r"DebugPrintEntityChoices\(\) -   Entities\[(?P<idx>\d+)\]=\[entityName=.+? "
    r"id=(?P<id>\d+) zone=(?P<zone>\w+) zonePos=\d+ cardId=(?P<card>[\w_]+) "
    r"player=(?P<player>\d+)\]")
# What we actually took. SendChoices is this client sending its answer;
# DebugPrintEntitiesChosen is the server echoing it back (a reconnect replays the
# echo without the send, so accept either).
CHOSEN_RE = re.compile(
    r"(?:SendChoices\(\) -   m_chosenEntities|DebugPrintEntitiesChosen\(\) -   Entities)"
    r"\[\d+\]=\[entityName=.+? id=(?P<id>\d+) zone=\w+ zonePos=\d+ "
    r"cardId=(?P<card>[\w_]+) player=(?P<player>\d+)\]")
# A hero REROLL rewrites the card under the same entity id, so a rerolled-in hero
# was genuinely on screen as an option too.
CHANGE_HAND_RE = re.compile(
    r"CHANGE_ENTITY - Updating Entity=\[entityName=.+? id=(?P<id>\d+) zone=HAND "
    r"[^\]]*\] CardID=(?P<card>[\w_]+)")

_SKIN_RE = re.compile(r"_SKIN_.*$")
# Last-resort id shapes, used only when HearthstoneJSON is unreachable AND nothing
# is cached. Hero ids are BG<set>_HERO_<n> or TB_BaconShop_HERO_<n> (plus an
# optional skin suffix); trinkets carry _MagicItem_ / _Trinket_. Anchoring on the
# trailing digits is also what keeps hero POWERS (BG25_HERO_103p) out.
HERO_SHAPE = re.compile(r"^(?:BG[A-Z0-9]*_HERO_\d+|TB_BaconShop_HERO_\d+)(?:_SKIN_[A-Z0-9]+)?$")
TRINKET_SHAPE = re.compile(r"^BG[A-Z0-9]*_(?:MagicItem|Trinket)_\w+$")

_UNIVERSE = []


def universe():
    """(heroes, trinkets): the cardId sets that tell those two card types apart
    from every other card in the log, from HearthstoneJSON via bgtracker (cached a
    day). Offline with no cache, either may be None - meaning "fall back to the id
    shape", which is coarser but keeps a fresh clone able to mine."""
    if not _UNIVERSE:
        try:
            ids = bg.bg_ids()
            _UNIVERSE.append((set(ids["heroes"]), set(ids["trinkets"])))
        except Exception:
            _UNIVERSE.append((None, None))
    return _UNIVERSE[0]


def hero_id(card):
    """A skin is the same hero in a different coat, and stats are keyed on the
    base id - so an offered skin and a picked skin must collapse to it, or the
    pick never matches its own offer."""
    return _SKIN_RE.sub("", card)


def is_hero(card, heroes):
    return bool(HERO_SHAPE.match(card)) if heroes is None else (
        card in heroes or hero_id(card) in heroes)


def is_trinket(card, trinkets):
    return bool(TRINKET_SHAPE.match(card)) if trinkets is None else card in trinkets


def offers(game, pid=None):
    """What the log PROVES about this game's options and what we took.

    Returns (player_id, offered_heroes, offered_trinkets, picked_trinkets).

    Verified against 23 real games (2026-08-11), two independent signals each:

    OFFERS. Every DebugPrintEntityChoices block in all 23 games carried OUR player
    id and nobody else's (336 of 336 blocks), so a block is by definition a dialog
    we were shown - which also makes it a reliable fallback for our player id when
    the game slice starts after a reconnect and has no hero draft. A block of
    exactly four trinkets is a trinket offer: the same four-option rule the live
    OfferDetector uses to reject the opponents' trinkets that pass through
    SETASIDE every time you fight them (they arrive in 1s, 2s, 3s and 6s). Logs
    without choice blocks fall back to that detector's own signal, the FULL_ENTITY
    burst of four SETASIDE trinkets sharing one timestamp - which produced exactly
    the same offers as the blocks on all 23 games.

    PICKS. SendChoices / DebugPrintEntitiesChosen name the entity we took, and its
    id is one of the offer's. Cross-checked against the independent signal - the
    taken trinket, and only it, re-materialises in zone=PLAY under our player id,
    while the three we refused stay in SETASIDE until they are removed from the
    game - the two agreed on 23 games of 23.

    Rerolled heroes count as offered: the reroll swaps the card under the same
    entity id, and that new hero really was on screen to be taken.
    """
    heroes, trinkets = universe()
    blocks, cur = [], None
    chosen = []          # (entity id, cardId) - our own picks, in order
    hand = {}            # entity id -> hero cardIds that occupied that draft slot
    burst = {}           # timestamp -> {entity id: (cardId, player)} - SETASIDE

    for line in game:
        if "DebugPrintEntityChoices" in line:
            if CHOICE_HDR_RE.search(line):
                cur = []
                blocks.append(cur)
            m = CHOICE_ENT_RE.search(line)
            if m and cur is not None:
                cur.append((int(m["idx"]), m["id"], m["card"], m["zone"], m["player"]))
                if m["zone"] == "HAND" and is_hero(m["card"], heroes):
                    hand.setdefault(m["id"], []).append(m["card"])
            continue
        cur = None                              # any other line ends the block
        if "m_chosenEntities[" in line or "DebugPrintEntitiesChosen() -   Entities[" in line:
            m = CHOSEN_RE.search(line)
            if m:
                chosen.append((m["id"], m["card"]))
        elif "FULL_ENTITY - Updating" in line:
            if "zone=HAND" in line:
                m = bg.ENTITY_RE.match(line)
                if m and is_hero(m["card"], heroes):
                    hand.setdefault(m["id"], []).append(m["card"])
            elif "zone=SETASIDE" in line:
                m = bg.ENTITY_RE.match(line)
                if m and is_trinket(m["card"], trinkets):
                    burst.setdefault(m["ts"], {})[m["id"]] = (m["card"], m["player"])
        elif "CHANGE_ENTITY - Updating" in line and "zone=HAND" in line:
            m = CHANGE_HAND_RE.search(line)
            if m and is_hero(m["card"], heroes):
                hand.setdefault(m["id"], []).append(m["card"])

    # Our player id: the hero draft when the slice has one, else any choice block.
    if pid is None:
        for b in blocks:
            if b:
                pid = b[0][4]
                break

    def ours(b):
        return b and all(p == pid for *_, p in b)

    offered_trinkets, offer_ids = [], set()
    if blocks:
        # The dialogs are logged, so they ARE the answer: a game with no trinket
        # block simply never reached a trinket. Falling back to the raw bursts
        # here would be the one way to let an opponent's revealed pair back in.
        for b in blocks:
            if (len(b) == bg.TRINKET_OPTIONS and ours(b)
                    and all(is_trinket(c, trinkets) for _, _, c, _, _ in b)):
                for _, eid, card, _, _ in sorted(b):
                    offered_trinkets.append(card)
                    offer_ids.add(eid)
    else:
        # This log doesn't print choice blocks at all - group the raw SETASIDE
        # bursts instead, exactly as the live OfferDetector does.
        for ents in burst.values():
            mine = {e: c for e, (c, p) in ents.items() if pid is None or p == pid}
            if len(mine) != bg.TRINKET_OPTIONS:
                continue
            for eid, card in mine.items():
                offered_trinkets.append(card)
                offer_ids.add(eid)

    # Heroes: the first block of >=2 heroes in hand is the draft (duos offer two),
    # then every card that later occupied one of those slots - i.e. the rerolls.
    offered_heroes = []
    hblocks = [b for b in blocks
               if len(b) >= 2 and ours(b)
               and all(z == "HAND" and is_hero(c, heroes) for _, _, c, z, _ in b)]
    slots = [eid for _, eid, _, _, _ in sorted(hblocks[0])] if hblocks else []
    if not slots:
        # Fallback: the draft burst itself, in on-screen order.
        draft = {}
        for line in game:
            d = DRAFT_RE.search(line)
            if d and (pid is None or d.group(2) == pid):
                draft.setdefault(d.group(1), None)
        slots = list(draft)
    for eid in slots:
        for card in hand.get(eid, []):
            if hero_id(card) not in offered_heroes:
                offered_heroes.append(hero_id(card))
    for eid, card in chosen:                     # the hero we took, reroll or not
        if eid in slots and is_hero(card, heroes) and hero_id(card) not in offered_heroes:
            offered_heroes.append(hero_id(card))

    picked_trinkets = []
    for eid, card in chosen:
        if eid in offer_ids and is_trinket(card, trinkets) and card not in picked_trinkets:
            picked_trinkets.append(card)
    if offered_trinkets and not picked_trinkets:
        # Reconnects can drop the choice echo. The second signal stands alone:
        # only the trinket we kept is re-created in PLAY under our player id.
        wanted = set(offered_trinkets)
        for line in game:
            if "zone=PLAY" not in line:
                continue
            m = re.search(r"zone=PLAY zonePos=\d+ cardId=([\w_]+) player=(\d+)\]", line)
            if m and m.group(1) in wanted and (pid is None or m.group(2) == pid) \
                    and m.group(1) not in picked_trinkets:
                picked_trinkets.append(m.group(1))

    return pid, offered_heroes, offered_trinkets, picked_trinkets


# A tribe is PROVEN in the lobby by a minion you could have bought: a real pool
# minion standing in play. Everything else that carries a CARDRACE tag is not
# evidence about this lobby at all, and counting it was wrong:
#
#   - cards GENERATED into a hand ("Get a random Chromadrake", discovers, Dark
#     Gift rewards) carry their own tribe from outside the lobby. Measured on a
#     real game: 9 tribes counted, of which Dragon appeared on 2 log lines and
#     Pirate on 4, both hand-only, against hundreds of lines for the tribes
#     really in play.
#   - TOKENS summoned during a fight (Skeletons, Beetles, Golems, Microbots)
#     carry a tribe whether or not that tribe is in the lobby.
#
# So: zone must be PLAY, and the card must be in the buyable pool. This is the
# same standard bgtracker.LobbyTracker uses for the live overlay, which is that
# seeing a minion PROVES its tribe is in while an unseen tribe is only
# unconfirmed. Exactness still needs the memory reader; the log cannot rule a
# tribe OUT, and this function does not pretend to.
_RACE_HEAD = re.compile(
    r"(?:FULL_ENTITY - Creating ID|SHOW_ENTITY - Updating Entity)=\d+ CardID=(\S+)")
_RACE_BRACKET = re.compile(
    r"\[entityName=.+? id=\d+ zone=(\S+) zonePos=\d+ cardId=(\S*)")
_RACE_TAG = re.compile(r"\(\) - \s*tag=(\w+) value=(\S+)")
_BOB = re.compile(r"cardId=TB_BaconShopBob player=(\d+)")


_POOL_IDS = set()


def pool_ids():
    """Every buyable minion's card id, fetched once per run. Empty when the
    card database is unreachable, and an empty pool means this run mines no
    tribes at all rather than mining wrong ones: a re-mine fills them in."""
    global _POOL_IDS
    if not _POOL_IDS:
        try:
            _POOL_IDS = {m["id"] for m in bg.bg_pool()}
        except Exception:
            return set()
    return _POOL_IDS


def lobby_tribes(game):
    """The tribes this lobby PROVABLY had, from one pass over its lines.

    Never claims a tribe is OUT: an unseen tribe is unconfirmed, exactly as
    bgtracker.LobbyTracker treats it live. Exactness needs the memory reader.

    Three filters, each measured, in order of how much they were worth:

      zone must be PLAY   - a card generated into a HAND (a Get, a discover, a
                            Dark Gift reward) carries a tribe from outside the
                            lobby. This is the big one.
      the card must be    - a token summoned mid fight (Skeleton, Beetle,
      a buyable minion      Golem) carries its own tribe regardless.
      Bob's controller    - where the log names him, this drops a generated
      where it is known     card that was then PLAYED onto a board.

    Measured over 60 real games: six claimed 9 tribes before, one does now.
    That last one is honest residual, not a miss to hunt: its four doubtful
    tribes have 1, 2, 4 and 4 sightings against 42 to 71 for the five real
    ones, and the log gives nothing that separates a single shop sighting from
    a single played-from-hand sighting. Counting it IN is the safe direction,
    because this function's whole contract is that a tribe seen is proven in
    and an unseen tribe is merely unconfirmed.
    """
    pool = pool_ids()
    # Without Bob (a slice that begins after a reconnect) fall back to minions
    # in play: looser, but better than a game with no tribes at all.
    bob = next((m.group(1) for line in game
                for m in [_BOB.search(line)] if m), None)
    tribes = set()
    card = zone = race = ctrl = None

    def keep():
        # A block states its card up top and its zone, race and controller as
        # sibling lines, so the verdict is only reachable once the block ends.
        if race in bg.TRIBES and zone == "PLAY" and (bob is None or ctrl == bob):
            base = card[:-2] if card and card.endswith("_G") else card
            if base in pool:
                tribes.add(race)

    for line in game:
        h = _RACE_HEAD.search(line)
        if h:
            keep()
            card, zone, race, ctrl = h.group(1), None, None, None
            continue
        b = _RACE_BRACKET.search(line)
        if b:
            keep()
            card = zone = race = ctrl = None
            # The one-line form carries zone and cardId inline but no
            # controller, so it is only ever board-grade evidence: use it when
            # there is no shop to key on, ignore it when there is.
            r = re.search(r"tag=CARDRACE value=([A-Z_]+)", line)
            if bob is None and r and r.group(1) in bg.TRIBES and b.group(1) == "PLAY":
                cid = b.group(2)
                cid = cid[:-2] if cid.endswith("_G") else cid
                if cid in pool:
                    tribes.add(r.group(1))
            continue
        t = _RACE_TAG.search(line)
        if t and card is not None:
            k, v = t.group(1), t.group(2)
            if k == "ZONE":
                zone = v
            elif k == "CARDRACE":
                race = v
            elif k == "CONTROLLER":
                ctrl = v
            continue
        keep()
        card = zone = race = ctrl = None
    keep()
    return sorted(tribes)


def extract(game, tag):
    """Our final hero, final placement, lobby tribes and the offers we were shown
    - all pinned to the player the hero draft proves is us. `tag` is only a
    fallback for place."""
    drafted = set()                 # entity ids of OUR offered heroes
    pid = None                      # our PLAYER id, from those same lines
    names = {}                      # player id -> battletag
    for line in game:
        d = DRAFT_RE.search(line)
        if d:
            drafted.add(d.group(1))
            pid = d.group(2)
        n = NAME_MAP_RE.search(line)
        if n:
            names[n.group(1)] = n.group(2)

    # Offers and picks. This also recovers our player id for a slice that begins
    # after a reconnect and so has no hero draft in it - those games still know
    # which trinkets they were shown, and now they keep their placement too.
    pid, offered_heroes, offered_trinkets, picked_trinkets = offers(game, pid)

    # Our hero = the drafted entity that ends up IN PLAY with a real hero card
    # (a reroll swaps the card under the same entity, so take the LAST match).
    hero = None
    if drafted:
        pat = re.compile(r"id=(" + "|".join(drafted) + r") zone=PLAY[^\]]* cardId=(\S+)")
        for line in game:
            mm = pat.search(line)
            if mm and HERO_RE.search(mm.group(2)) and "_PH" not in mm.group(2):
                hero = hero_id(HERO_RE.search(mm.group(2)).group(1))

    # Place: PLAYER_LEADERBOARD_PLACE lines carry the OWNING player id right in
    # the entity bracket, so key on our draft-proven id directly - no battletag,
    # no header-context tracking (that tracker mis-attributed 4 of 5 places to
    # whoever's standing happened to print next). The tag updates continuously
    # as the lobby shrinks; the LAST value for our player is the final result.
    place = None
    place_re = re.compile(r"player=" + (pid or r"\0") +
                          r"\] tag=PLAYER_LEADERBOARD_PLACE value=(\d+)")
    for line in game:
        p = place_re.search(line)
        if p:
            place = int(p.group(1))
    tribes = lobby_tribes(game)

    # An offer-only game still carries signal: pick rate needs the options you
    # turned down, not the result. Keep it rather than throw it away.
    if hero is None and place is None and not (offered_trinkets or offered_heroes):
        return None
    return hero, place, sorted(tribes), offered_heroes, offered_trinkets, picked_trinkets


def games_in(path):
    txt = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    tag = file_battletag(txt)
    cuts = [i for i, l in enumerate(txt) if "CREATE_GAME" in l] + [len(txt)]
    for a, b in zip(cuts, cuts[1:]):
        game = txt[a:b]
        if not any("STATE value=COMPLETE" in l for l in game):
            continue                       # unfinished / disconnect
        duo = any(DUO_RE.search(l) for l in game)
        got = extract(game, tag)
        if not got:
            continue
        hero, place, tribes, off_h, off_t, pick_t = got
        date = path.parent.name.replace("Hearthstone_", "")[:10]  # YYYY_MM_DD
        yield {
            "date": date,
            "game_id": f"{path.parent.name}:{a}",   # stable de-dupe key
            "hero": hero,
            "place": place,
            # Solo or Duos - see DUO_RE. Always a real boolean here, because the
            # slice either carries the tag or provably does not. A record written
            # by an older version has no `duo` key at all, and that absence means
            # UNKNOWN: the aggregator must count it in neither pool rather than
            # assume solo. Re-mining fills it in wherever the log still exists.
            "duo": duo,
            "tribes": tribes,
            # Named exactly as server/aggregate.py reads them.
            "offered_heroes": off_h,
            "offered_trinkets": off_t,
            "picked_trinkets": pick_t,
            "source_log": path.parent.name,
            # Which extraction rules produced this record. Local bookkeeping:
            # upload_records() never sends it, so a bump re-mines without
            # re-uploading anything whose values did not actually change.
            "mv": MINER_VERSION,
        }


# Every key a mined record carries. A record written by an older version is
# missing the offer fields (or `duo`), and its game can be re-mined to fill them
# in - which is the whole reason collect() rewrites rather than appends. Adding a
# key here is what makes the next run repair every record whose log still exists.
FIELDS = ("date", "game_id", "hero", "place", "duo", "tribes",
          "offered_heroes", "offered_trinkets", "picked_trinkets", "source_log")

# How this file MINES, as opposed to what it stores. Missing keys repair
# themselves through FIELDS above, but a key whose VALUE was extracted wrongly
# never would: the record has every field, so it looks complete forever. Bump
# this whenever an extraction rule changes and every record mined by an older
# rule is re-mined once, wherever its log still exists.
#   2: lobby tribes count only pool minions in play (a hand-generated card or
#      a summoned token carries a tribe the lobby never had; measured, one real
#      game claimed 9 tribes, three of them impossible).
#   3: lobby tribes key on BOB'S SHOP where the log names him, which also
#      drops a generated card that was played onto a board.
MINER_VERSION = 3


def collect(logs=None):
    """Mine `logs` (default: the whole Power.log history) into games.jsonl.

    `logs` exists for the overlay's own pooling (pool.py): the full-history
    pass costs real time (measured 53 seconds over 1.6 GB of logs), so at a
    game boundary the overlay passes just the CURRENT log and this merges its
    games into the file without touching, or re-reading, anything else.
    """
    DATA.mkdir(exist_ok=True)
    kept = {}                                  # game_id -> record, insertion order
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                kept[rec["game_id"]] = rec
            except Exception:
                pass
    if logs is None:
        logs = sorted(bg.HS_LOGS.glob("Hearthstone_*/Power.log"))
    added = filled = 0
    for path in logs:
        for rec in games_in(path):
            old = kept.get(rec["game_id"])
            if old is None:
                added += 1
            elif (all(k in old for k in FIELDS)
                    and old.get("mv") == MINER_VERSION):
                continue                       # complete AND mined by this rule
            else:
                filled += 1                    # older record, re-mined in place
                # The fresh mine wins key by key: that is what repairs a value
                # an older rule got wrong, while anything only the old record
                # has (a field from a log that has since rotated away) stays.
                rec = {**old, **rec}
            kept[rec["game_id"]] = rec
    # Rewrite through a temp file so an interrupted run can never truncate the
    # only copy of the dataset. Games whose log has since rotated away are kept
    # exactly as they were - nothing is ever dropped. The temp name carries the
    # pid because two writers are now reachable at once (the overlay's pool
    # thread backfilling while the panel's "Share now" runs a mine): a shared
    # fixed name would let one replace() publish the other's half-written file.
    tmp = OUT.with_suffix(f".jsonl.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in kept.values():
            f.write(json.dumps(rec) + "\n")
    tmp.replace(OUT)
    extra = f", filled in offers for {filled} older ones" if filled else ""
    print(f"collected {added} new games{extra}; total {len(kept)} in {OUT}")
    out = {"added": added, "filled": filled, "total": len(kept)}
    with_t = sum(1 for r in kept.values() if r.get("offered_trinkets"))
    print(f"  {with_t} carry trinket offers "
          f"({sum(len(r.get('offered_trinkets') or []) for r in kept.values())} options, "
          f"{sum(len(r.get('picked_trinkets') or []) for r in kept.values())} taken)")
    duo = sum(1 for r in kept.values() if r.get("duo") is True)
    solo = sum(1 for r in kept.values() if r.get("duo") is False)
    unknown = len(kept) - duo - solo
    tail = (f", {unknown} unknown (mined before duos was detected, and their log "
            f"has rotated away)" if unknown else "")
    print(f"  {solo} solo, {duo} duos{tail}")
    # Returned as well as printed: the settings panel runs this and has to show
    # the outcome in a row, and scraping stdout for it would be a lie waiting to
    # happen the first time a print is reworded.
    return out


def stats():
    if not OUT.exists():
        print("no data yet - run `" + HOWTO + "` first")
        return
    recs = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"{len(recs)} games recorded")
    with_both = [r for r in recs if r.get("hero") and r.get("place")]
    print(f"  {len(with_both)} have both hero and placement")
    duo = sum(1 for r in recs if r.get("duo") is True)
    solo = sum(1 for r in recs if r.get("duo") is False)
    unknown = len(recs) - duo - solo
    print(f"  {solo} solo, {duo} duos"
          + (f", {unknown} of unknown mode (counted in neither feed)" if unknown else ""))
    with_off = [r for r in recs if r.get("offered_heroes")]
    with_tri = [r for r in recs if r.get("offered_trinkets")]
    picked = sum(len(r.get("picked_trinkets") or []) for r in recs)
    print(f"  {len(with_off)} carry the hero offer (pick rate needs it)")
    print(f"  {len(with_tri)} carry trinket offers - {picked} trinkets taken")
    names = bg.card_names()
    # Solo and duos are listed apart for the same reason the feeds are: a duos
    # game finishes 1st-4th, a solo game 1st-8th, so one average over both is a
    # number that describes no game you ever played.
    for label, want in (("solo", False), ("duos", True)):
        per = defaultdict(list)
        for r in with_both:
            if r.get("duo") is want:
                per[r["hero"]].append(r["place"])
        if not per:
            continue
        rows = sorted((sum(v) / len(v), len(v), h) for h, v in per.items())
        print(f"  your average placement by hero, {label} "
              f"({sum(len(v) for v in per.values())} games):")
        for avg, n, h in rows[:15]:
            print(f"    {avg:.2f}  {names.get(h, h):26} n={n}")


def client_id():
    """A random id kept only on this machine. Uploads use it as a salt so the
    server can de-dupe re-uploads without ever learning who you are - it never
    leaves except hashed into each game's opaque uid. Generated once."""
    if CLIENT_ID_FILE.exists():
        return CLIENT_ID_FILE.read_text(encoding="utf-8").strip()
    DATA.mkdir(exist_ok=True)
    cid = uuid.uuid4().hex
    CLIENT_ID_FILE.write_text(cid, encoding="utf-8")
    return cid


def upload_records():
    """One upload-shaped record per game in games.jsonl, or [] with none yet.

    This list IS the privacy contract: every field that ever leaves the machine
    is built right here and nowhere else, the settings panel's DATA copy names
    each one, and tests/test_settings.py reads this function's source to hold
    the two together. Only the aggregate signal (hero, placement, lobby tribes,
    date, and the heroes and trinkets you were offered) under an opaque id -
    never your battletag, never the logs themselves."""
    if not OUT.exists():
        return []
    cid = client_id()
    recs = []
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        if not (g.get("hero") or g.get("place")):
            continue                       # the server rejects no-signal games anyway
        recs.append({
            "uid": hashlib.sha256(f"{cid}:{g['game_id']}".encode()).hexdigest()[:32],
            "date": g.get("date"),
            "hero": g.get("hero"),
            "place": g.get("place"),
            # Solo or duos. Sent as null when this record predates the detector,
            # so the server can keep it out of both feeds rather than guess; a
            # later upload of the re-mined record fills that null in.
            "duo": g.get("duo"),
            "tribes": g.get("tribes") or [],
            # The options you turned down - the only way pick rate can exist.
            # Still just cardIds off your own screen; nothing identifying.
            "offered_heroes": g.get("offered_heroes") or [],
            "offered_trinkets": g.get("offered_trinkets") or [],
            "picked_trinkets": g.get("picked_trinkets") or [],
            "client": cid[:8],
            # Which client version mined this. Not about you - it is how the
            # server can tell "the numbers moved" from "a build with a parsing
            # bug is in the wild", and which versions are still uploading. An
            # older server ignores an unknown field, so sending it is safe
            # before the server that stores it is deployed.
            "v": VERSION,
        })
    return recs


def upload_url(base_url):
    """The ingest endpoint for a feed address, however the address was typed."""
    url = base_url.rstrip("/")
    if not url.endswith("/upload"):
        url += "/upload"
    return url


def post_batch(url, recs, token=None, timeout=30):
    """POST one batch of records; return the server's parsed reply.

    Raises on any failure - the CALLER decides whether that is printed
    (upload() below) or swallowed and retried later (pool.py). `url` is the
    full /upload endpoint, from upload_url()."""
    body = json.dumps({"games": recs}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    if token:
        req.add_header("X-Upload-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def upload(base_url, token=None, batch=300):
    """Send EVERY collected game to a shared feed, in one pass.

    This is the by-hand path (`--upload`, and the panel's Share now button):
    it ignores pool.py's sent ledger and resends the lot, which is safe and
    cheap because the server de-dupes on uid - and it is exactly what you want
    when the question is "did my games arrive?". The overlay's own automatic
    sharing lives in pool.py and sends only what has not gone yet."""
    if not OUT.exists():
        print("no data yet - run `" + HOWTO + "` first")
        return {"sent": 0, "stored": 0, "error": None,
                "note": "no games collected yet"}
    recs = upload_records()
    if not recs:
        print("nothing to upload (no games with a hero or placement yet)")
        return {"sent": 0, "stored": 0, "error": None,
                "note": "no games with a hero or placement yet"}

    url = upload_url(base_url)
    sent = stored = 0
    for i in range(0, len(recs), batch):
        try:
            res = post_batch(url, recs[i:i + batch], token)
        except Exception as e:
            print(f"  ! upload failed at batch {i // batch}: {e}")
            # The caller gets the failure verbatim. A partial upload is still
            # reported as what it was - some batches did land, and the server
            # de-dupes on uid, so re-running is safe and never doubles a game.
            return {"sent": sent, "stored": stored, "error": f"{type(e).__name__}: {e}",
                    "note": f"stopped at batch {i // batch + 1} of "
                            f"{(len(recs) + batch - 1) // batch}"}
        sent += res.get("accepted", 0)
        stored += res.get("stored", 0)
    print(f"uploaded {sent} games to {url} ({stored} new to the server)")
    return {"sent": sent, "stored": stored, "error": None, "note": None}


def local_feed():
    """YOUR games become YOUR stats feed, in one command.

    Runs the same aggregator the community server uses over data/games.jsonl,
    writes the four client-shaped feeds into data/feed/, and (only if you have
    no sources.json yet) writes one pointing at them - so the overlay lights up
    with real numbers from your own play, no third party involved. Thin samples
    stay flagged by the client; nothing is invented."""
    if not OUT.exists():
        print("no data/games.jsonl yet - run `" + HOWTO + "` first")
        return
    import os
    import sys
    feed_dir = DATA / "feed"
    os.environ["BGTRACKER_OUT"] = str(feed_dir)      # before the import: the
    # CODE, so BUNDLE_DIR: server/aggregate.py ships inside the frozen build.
    sys.path.insert(0, str(BUNDLE_DIR / "server"))   # module reads env at load
    import aggregate as agg
    games = []
    with open(OUT, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            g = json.loads(line)
            # The aggregator indexes these keys directly; collected records
            # only carry what the log gives, so fill the rest as absent.
            # `duo` included: absent means unknown, and the aggregator keeps an
            # unknown game out of BOTH feeds instead of assuming it was solo.
            for k in ("hero", "place", "mmr", "duo"):
                g.setdefault(k, None)
            for k in ("tribes", "offered_heroes", "offered_trinkets",
                      "picked_trinkets", "final_board"):
                g.setdefault(k, [])
            if g.get("date"):
                g["date"] = g["date"].replace("_", "-")   # log dirs use underscores
            games.append(g)
    from datetime import datetime
    stamp = datetime.now().isoformat(timespec="seconds")
    # Same bucketing rules as the community server (server/aggregate.py): one
    # file per MMR bucket your own games can support. On a personal feed that is
    # normally just the all-players bucket - the log never states your rating -
    # and the client falls back to it, so nothing goes blank.
    agg.write("buckets", agg.emit(games, stamp))
    local = dict(LOCAL_FEED)
    src = APP_DIR / "sources.json"
    if not src.exists():
        src.write_text(json.dumps(local, indent=2), encoding="utf-8")
        print("wrote sources.json -> your own numbers now show in the overlay")
    else:
        # An existing sources.json is the user's own file and is never rewritten
        # - but a table that gained files since it was written would stay dark
        # forever, which is how a `--duo` that reads nothing looks like a broken
        # feature. So the MISSING keys are added, pointing at the feed this run
        # just built, and nothing already in the file is touched.
        try:
            cur = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            cur = None
        added = [k for k in local if isinstance(cur, dict) and k not in cur]
        if added:
            cur.update({k: local[k] for k in added})
            src.write_text(json.dumps(cur, indent=2), encoding="utf-8")
            print(f"sources.json kept as it was, plus your local feed for: "
                  f"{', '.join(added)}")
        else:
            print("sources.json already exists - left untouched")
    duo = sum(1 for g in games if g.get("duo") is True)
    solo = sum(1 for g in games if g.get("duo") is False)
    unknown = len(games) - solo - duo
    print(f"({len(games)} games total: {solo} solo, {duo} duos"
          + (f", {unknown} of unknown mode left out of both" if unknown else "")
          + f"; under {bg.MIN_SAMPLE} per hero shows as thin - it fills in as you play)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true", help="print what we have so far")
    ap.add_argument("--local-feed", action="store_true",
                    help="turn your collected games into a personal stats feed the overlay reads")
    ap.add_argument("--upload", metavar="URL",
                    help="send ALL collected games to a shared feed, now, by hand "
                         "(the overlay already shares new games on its own unless "
                         "you switched that off)")
    ap.add_argument("--token", help="X-Upload-Token, if the server requires one")
    args = ap.parse_args()
    if args.upload:
        upload(args.upload, args.token)
    elif args.stats:
        stats()
    elif args.local_feed:
        local_feed()
    else:
        collect()
        print("\ntip: `" + HOWTO + " --local-feed` turns these games into your own overlay numbers")


if __name__ == "__main__":
    main()
