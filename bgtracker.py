#!/usr/bin/env python3
"""
bgtracker - live Hearthstone Battlegrounds pick helper.

Reads Hearthstone's own Power.log, spots the moment you're offered heroes
(or trinkets), and shows each option - with average placement and pick rate
IF you have configured a stats source of your own (sources.json; see README).

No stats data is bundled or fetched by default: aggregate placement data
belongs to whoever collected it, and this tool points at nobody's feed.
Card names and IDs come from HearthstoneJSON. Everything runs locally, and
by default nothing leaves your machine. Contributing your finished games to
the community dataset is a strict opt-in (see README) - anonymised records,
aggregates free for everyone, never sold.

Usage:
    python bgtracker.py                     # live: follow the newest Power.log
    python bgtracker.py --replay            # replay the newest log, show past offers
    python bgtracker.py --replay <path>     # replay a specific Power.log
    python bgtracker.py --mmr 10            # use top-10% stats (100/50/25/10/1)
    python bgtracker.py --time past-seven   # all-time|past-three|past-seven|last-patch
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# There is NO built-in stats feed. To see numbers, create sources.json next to
# this file with any of the keys
#   heroes, heroes_duo, trinkets, comps, cards
# each mapping to a URL or a local JSON file you have the right to use
# ({mmr} and {time} placeholders are filled in). collect.py grows your own
# dataset from your own games. See README: "Bring your own stats".
SOURCES_FILE = Path(__file__).parent / "sources.json"

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"

# The ten Battlegrounds tribes. A lobby only ever runs a subset.
TRIBES = ["BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL",
          "MURLOC", "NAGA", "PIRATE", "QUILBOAR", "UNDEAD"]
TRIBE_LABEL = {t: t.capitalize() for t in TRIBES}
TRIBE_LABEL["MECHANICAL"] = "Mech"

# Hearthstone's own Race enum ids. Both a stats source and the memory reader
# speak these numbers.
TRIBE_ID = {11: "UNDEAD", 14: "MURLOC", 15: "DEMON", 17: "MECHANICAL",
            18: "ELEMENTAL", 20: "BEAST", 23: "PIRATE", 24: "DRAGON",
            43: "QUILBOAR", 92: "NAGA"}

# The memory reader that knows the lobby's tribes at hero select, which the log
# never states. Built from native/msync (clean-room); absent until you build it.
MSYNC_EXE = Path(__file__).parent / "native" / "msync" / "bin" / "Release" / "net48" / "msync.exe"

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_TTL = 3600  # stats feeds typically rebuild hourly; don't refetch faster

# Below this many games an average placement is noise, not a signal.
MIN_SAMPLE = 30

# A trinket offer always presents exactly four options.
TRINKET_OPTIONS = 4

HS_LOGS = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Hearthstone" / "Logs"

# Lines look like:
# D 13:29:32.3296250 PowerTaskList.DebugPrintPower() -     FULL_ENTITY - Updating
#   [entityName=Lady Vashj id=96 zone=HAND zonePos=4 cardId=BG23_HERO_304 player=3] CardID=BG23_HERO_304
TS_RE = re.compile(r"^D ([\d:.]+)")
# The offered heroes get shuffled into their final on-screen order AFTER the
# FULL_ENTITY burst, in ONE ZONE_POSITION correction block; the last value per
# entity in THAT block - zeros included, they are transit states - matched the
# screen exactly (verified live 2026-08-10). Later blocks are rerolls and the
# pick itself, so tracking must freeze after the first block.
TAGPOS_RE = re.compile(
    r"^D (?P<ts>[\d:.]+).*?TAG_CHANGE Entity=\[entityName=.+? id=(?P<id>\d+) "
    r"zone=HAND [^\]]*\] tag=ZONE_POSITION value=(?P<pos>\d+)")
# A hero REROLL rewrites the same entity in place: the bracket still carries the
# old name/card, the trailing CardID is the hero that replaced it.
CHANGE_RE = re.compile(
    r"CHANGE_ENTITY - Updating Entity=\[entityName=.+? id=(?P<id>\d+) "
    r"zone=HAND [^\]]*\] CardID=(?P<card>[\w_]+)")

# Every choose-one dialog (trinket shop, discovers, Dark Gift minions) logs an
# EntityChoices block whose Entities[i] index IS the on-screen order - verified
# against a live trinket screen 2026-08-10.
CHOICE_HDR_RE = re.compile(r"^D [\d:.]+ GameState\.DebugPrintEntityChoices\(\) - id=\d+ Player=")
CHOICE_ENT_RE = re.compile(
    r"DebugPrintEntityChoices\(\) -   Entities\[(?P<idx>\d+)\]="
    r"\[entityName=(?P<name>.+?) id=\d+ [^\]]*cardId=(?P<card>[\w_]+)")


class ChoiceReader:
    """Collects one EntityChoices block; returns its ordered options when the
    block ends (first non-choice line)."""

    def __init__(self):
        self.cur = None

    def feed(self, line: str):
        if "DebugPrintEntityChoices" not in line:
            if self.cur:
                done, self.cur = self.cur, None
                return done or None
            return None
        if CHOICE_HDR_RE.match(line):
            self.cur = []
        m = CHOICE_ENT_RE.search(line)
        if m and self.cur is not None:
            self.cur.append((int(m.group("idx")), m.group("name"), m.group("card")))
        return None
ENTITY_RE = re.compile(
    r"^D (?P<ts>[\d:.]+).*?FULL_ENTITY - Updating "
    r"\[entityName=(?P<name>.*?) id=(?P<id>\d+) zone=(?P<zone>\w+) "
    r"zonePos=(?P<pos>\d+) cardId=(?P<card>[\w_]+) player=(?P<player>\d+)\]"
)


# ---------------------------------------------------------------- stats layer

def _fetch(url: str):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "bgtracker/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":  # gzip magic, in case the CDN stops pre-decoding
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw)


def stats_source(kind: str, **fmt):
    """The user-configured source for one stats table (sources.json).
    Returns a URL or file path, or None when the user hasn't configured one."""
    try:
        srcs = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        sys.exit(f"sources.json is not valid JSON: {e}")
    src = srcs.get(kind)
    if not src:
        return None
    try:
        return src.format(**fmt)
    except (KeyError, IndexError):
        return src


def load_stats(source, key: str, refresh: bool = False):
    """Load one stats blob from a user-configured source - a URL (cached on
    disk for CACHE_TTL seconds) or a local JSON file. No source -> {}, so
    every table quietly degrades to 'no data' instead of failing."""
    if not source:
        return {}
    if not source.startswith(("http://", "https://")):
        p = Path(source)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        return json.loads(p.read_text(encoding="utf-8"))
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / (key + ".json")
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = _fetch(source)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data
    except Exception as e:
        if path.exists():
            print(f"  ! fetch failed ({e}); using cached copy from "
                  f"{time.strftime('%H:%M', time.localtime(path.stat().st_mtime))}", file=sys.stderr)
            return json.loads(path.read_text(encoding="utf-8"))
        raise


def hero_table(mmr: str, period: str, duo: bool = False, refresh: bool = False) -> dict:
    """cardId -> {avg placement, pick rate, sample size}."""
    src = stats_source("heroes_duo" if duo else "heroes", mmr=mmr, time=period)
    data = load_stats(src, f"heroes-{'duo-' if duo else ''}{mmr}-{period}", refresh)
    out = {}
    for h in data.get("heroStats", []):
        offered = h.get("totalOffered") or 0
        # Drop tribe rows with too little data on either side before trusting
        # them - a thin sample on a tribe is worse than no adjustment.
        n = h.get("dataPoints", 0)
        tribes = [t for t in (h.get("tribeStats") or [])
                  if t.get("dataPoints", 0) > n / 20
                  and t.get("dataPointsOnMissingTribe", 0) > t.get("dataPoints", 0) / 20]
        out[h["heroCardId"]] = {
            "avg": h.get("averagePosition"),
            "pick": (100.0 * h.get("totalPicked", 0) / offered) if offered else None,
            "n": n,
            "dist": h.get("placementDistribution") or [],
            "tribes": tribes,
        }
    return out


def lobby_adjust(stat: dict, present: set):
    """
    Re-score a hero for the tribes this lobby is actually running.

    The standard lobby-scoring arithmetic: the base average plus the summed
    impact of each tribe that is in. Returns None when we don't know the tribes,
    or when the hero has no usable tribe rows - better no number than a fake one.
    """
    if not present or stat is None or stat.get("avg") is None:
        return None
    rows = [t for t in (stat.get("tribes") or []) if TRIBE_ID.get(t.get("tribe")) in present]
    if not rows:
        return None
    return stat["avg"] + sum(t.get("impactAveragePosition", 0) for t in rows)


def trinket_table(period: str, mmr: str, refresh: bool = False) -> dict:
    data = load_stats(stats_source("trinkets", time=period, mmr=mmr),
                      f"trinkets-{period}", refresh)
    out = {}
    for t in data.get("trinketStats", []):
        avg = t.get("averagePlacement")
        for row in t.get("averagePlacementAtMmr") or []:      # prefer the requested MMR bucket
            if str(row.get("mmr")) == str(mmr):
                avg = row.get("placement")
                break
        out[t["trinketCardId"]] = {
            "avg": avg,
            "pick": 100.0 * t["pickRate"] if t.get("pickRate") is not None else None,
            "n": t.get("dataPoints", 0),
            "dist": [],
        }
    return out


def card_table(mmr: str, period: str, refresh: bool = False) -> dict:
    """cardId -> {avg placement when played, sample}. Powers the tavern panel."""
    data = load_stats(stats_source("cards", mmr=mmr, time=period),
                      f"cards-{mmr}-{period}", refresh)
    out = {}
    for c in data.get("cardStats", []):
        avg, other = c.get("averagePlacement"), c.get("averagePlacementOther")
        out[c["cardId"]] = {
            "avg": avg,
            "n": c.get("totalPlayed", 0),
            # The honest signal: players who bought it vs players who did not.
            # Raw averagePlacement mostly measures WHO buys a card (late-game
            # cards are bought by winners), not whether it helps.
            "delta": (avg - other) if (avg is not None and other is not None) else None,
        }
    return out


def card_tiers(refresh: bool = False) -> dict:
    """cardId -> tavern tier. Minion strength scales with tier, so any rating
    must compare a minion against its OWN tier, not the whole pool."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "cardtiers.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    tiers = {c["id"]: c["techLevel"] for c in cards if c.get("id") and c.get("techLevel")}
    path.write_text(json.dumps(tiers), encoding="utf-8")
    return tiers


def card_names(refresh: bool = False) -> dict:
    """cardId -> printable name. Card text only changes on patches, so cache it a day."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "cardnames.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    names = {c["id"]: c["name"] for c in cards if c.get("id") and c.get("name")}
    path.write_text(json.dumps(names), encoding="utf-8")
    return names


def bg_ids(refresh: bool = False) -> dict:
    """{'heroes': [...], 'trinkets': [...]} - every Battlegrounds hero and
    trinket cardId, from HearthstoneJSON. This is what lets the detector
    RECOGNISE an offer; stats tables only decorate it with numbers."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "bgids.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    ids = {"heroes": [c["id"] for c in cards if c.get("battlegroundsHero")],
           "trinkets": [c["id"] for c in cards if c.get("type") == "BATTLEGROUND_TRINKET"]}
    path.write_text(json.dumps(ids), encoding="utf-8")
    return ids


def hero_universe(refresh: bool = False) -> dict:
    """cardId -> {} for every BG hero; the detector's recognition set."""
    return {i: {} for i in bg_ids(refresh)["heroes"]}


def trinket_universe(refresh: bool = False) -> dict:
    """cardId -> {} for every BG trinket; the detector's recognition set."""
    return {i: {} for i in bg_ids(refresh)["trinkets"]}


def hero_power_universe(refresh: bool = False) -> dict:
    """cardId -> {} for every hero power.

    A hero-power choose-one and a minion discover arrive as the same
    EntityChoices block, so telling them apart is a card-identity question.
    Cached a day like the other card facts; offline with no cache this returns
    {} and the id-shape fallback in ui.classify_choice takes over."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "heropowers.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return {i: {} for i in json.loads(path.read_text(encoding="utf-8"))}
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        if path.exists():
            return {i: {} for i in json.loads(path.read_text(encoding="utf-8"))}
        return {}
    ids = [c["id"] for c in cards if c.get("type") == "HERO_POWER" and c.get("id")]
    path.write_text(json.dumps(ids), encoding="utf-8")
    return {i: {} for i in ids}


def comp_minion_counts(comp: dict) -> tuple:
    """(cardId -> appearances, number of boards) over this comp's real boards.
    Golden copies fold into the plain card - '_G' is the same minion, upgraded."""
    counts, boards = {}, 0
    for hero in comp.get("heroStats") or []:
        for board in hero.get("finalBoards") or []:
            boards += 1
            for minion in board.get("finalComp", {}).get("board") or []:
                cid = re.sub(r"_G$", "", minion.get("cardID", ""))
                if cid:
                    counts[cid] = counts.get(cid, 0) + 1
    return counts, boards


def key_minions(comp: dict, names: dict, limit: int = 4) -> list:
    """The minions that actually show up in this comp, most frequent first."""
    counts, _ = comp_minion_counts(comp)
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return [names.get(cid, cid) for cid, _ in top]


def comp_table(period: str, mmr: str, refresh: bool = False) -> list:
    """The archetypes behind the 'comps' page: what to build, and how it places.

    With a configured comps source: real measured rows (avg placement + n).
    Without one (or while it's still empty): the CURATED baseline - evergreen
    tribe families whose core minions are computed from the live card pool, so
    the panel is useful with zero stats and never shows a stale list."""
    data = load_stats(stats_source("comps", time=period, mmr=mmr),
                      f"comps-{period}", refresh)
    names = card_names(refresh)
    out = []
    for c in data.get("compStats", []):
        avg = c.get("averagePlacement")
        n = c.get("dataPoints", 0)
        for row in c.get("averagePlacementAtMmr") or []:
            if str(row.get("mmr")) == str(mmr):
                avg = row.get("placement", avg)
                n = row.get("dataPoints", n)
                break
        if avg is None:
            continue
        counts, boards = comp_minion_counts(c)
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        # freq: how often a minion appears on this comp's real boards (by NAME,
        # because the live log speaks names) - the raw material for scoring a
        # shop minion against the comp and against what's already on the board.
        freq = {names.get(cid, cid): cnt / boards for cid, cnt in ranked[:25]} if boards else {}
        out.append({"archetype": c["archetype"], "avg": avg, "n": n,
                    "tribe": archetype_tribe(c["archetype"]),
                    "key": [names.get(cid, cid) for cid, _ in ranked[:4]],
                    "key_wide": [names.get(cid, cid) for cid, _ in ranked[:10]],
                    "freq": freq})
    out.sort(key=lambda c: c["avg"])
    if out:
        return out
    try:
        return comp_families(refresh)
    except Exception:
        return []          # offline with no cache yet: empty beats a crash


# Evergreen tribe identities. Each family is (order, archetype, tribe,
# mechanics that mark a core piece, text patterns that mark a core piece).
# The FAMILIES survive patches because they are what the tribe is for; the
# actual core minions are computed from the live card pool, so they are always
# current-patch without shipping anyone's list.
COMP_FAMILIES = [
    (1,  "murloc poison",        "MURLOC",     {"BATTLECRY"},            r"[Pp]oison|[Vv]enom"),
    (2,  "mech magnetic",        "MECHANICAL", {"MAGNETIC", "DIVINE_SHIELD", "DEATHRATTLE"}, r"[Mm]agnetic|[Dd]ivine [Ss]hield"),
    (3,  "beast summons",        "BEAST",      {"DEATHRATTLE"},          r"[Ss]ummon"),
    (4,  "undead deathrattle",   "UNDEAD",     {"DEATHRATTLE", "REBORN"}, r"[Rr]eborn|dies"),
    (5,  "elemental scaling",    "ELEMENTAL",  {"END_OF_TURN_TRIGGER"},  r"[Tt]avern|[Rr]efresh|this turn"),
    (6,  "dragon attack",        "DRAGON",     {"START_OF_COMBAT"},      r"[Aa]ttack|[Ss]tart of [Cc]ombat"),
    (7,  "naga spellcraft",      "NAGA",       {"BACON_SPELLCRAFT_ID"},  r"[Ss]pellcraft|[Ss]pell"),
    (8,  "quilboar blood gems",  "QUILBOAR",   set(),                    r"[Bb]lood [Gg]em"),
    (9,  "pirate economy",       "PIRATE",     {"BACON_RALLY"},          r"[Gg]old|[Cc]oin|buy|sell"),
    (10, "demon consume",        "DEMON",      set(),                    r"[Hh]ealth|[Cc]onsume|your hero"),
    (11, "menagerie",            None,         set(),                    r"minion type|of each type|different"),
]


def bg_pool(refresh: bool = False) -> list:
    """The CURRENT Battlegrounds minion pool with the fields the comp engine
    scores on (id/name/techLevel/races/mechanics/text), cached a day."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "bgpool.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    pool = [{"id": c["id"], "name": c.get("name", c["id"]),
             "techLevel": c.get("techLevel", 0),
             "races": c.get("races") or ([c["race"]] if c.get("race") else []),
             "mechanics": c.get("mechanics") or [],
             "text": c.get("text") or ""}
            for c in cards if c.get("techLevel") and c.get("isBattlegroundsPoolMinion")]
    path.write_text(json.dumps(pool), encoding="utf-8")
    return pool


def comp_families(refresh: bool = False) -> list:
    """The curated baseline: one row per evergreen tribe family, core minions
    scored out of the LIVE pool. Rows carry baseline=True, avg=None, n=0 so
    every renderer shows 'curated' instead of pretending these are measured."""
    pool = bg_pool(refresh)
    out = []
    for order, archetype, tribe, mechs, pattern in COMP_FAMILIES:
        rx = re.compile(pattern)
        scored = []
        for m in pool:
            races = m["races"]
            if tribe is not None and tribe not in races and "ALL" not in races:
                continue
            if tribe is None and not rx.search(m["text"]):
                continue                     # menagerie cores must SAY so
            score = (2 * sum(1 for k in m["mechanics"] if k in mechs)
                     + (2 if rx.search(m["text"]) else 0)
                     + (1 if m["techLevel"] >= 4 else 0))
            if score > 0:
                scored.append((score, m["techLevel"], m["name"]))
        scored.sort(key=lambda s: (-s[0], -s[1]))
        names_ranked = [n for _, _, n in scored]
        if len(names_ranked) < 3:            # a family with no pool support this patch
            continue
        out.append({"archetype": archetype, "tribe": tribe,
                    "avg": None, "n": 0, "rank": order, "baseline": True,
                    "key": names_ranked[:5], "key_wide": names_ranked[:9],
                    "freq": {}})
    return out


def comp_sort_key(c, thin_at: int):
    """Order comps with mixed real/baseline rows without crashing on avg=None:
    solid data first, then thin, then curated baseline (by family order)."""
    if c.get("baseline"):
        return (2, c.get("rank", 99))
    return (0 if c["n"] >= thin_at else 1, c["avg"])


def archetype_tribe(archetype: str) -> str | None:
    """'mech_magnet' -> MECHANICAL, 'end_of_turn_naga' -> NAGA, 'neutral_*' -> None."""
    a = archetype.upper()
    for t in TRIBES:
        if t in a or (t == "MECHANICAL" and "MECH" in a):
            return t
    return None


def normalize(card_id: str, table: dict) -> str:
    """Hero skins carry a suffix the stats table doesn't use."""
    if card_id in table:
        return card_id
    base = re.sub(r"_SKIN_.*$", "", card_id)
    return base if base in table else card_id


# ---------------------------------------------------------------- presentation

def top4_rate(dist):
    if not dist:
        return None
    return sum(d["percentage"] for d in dist if d.get("rank", 9) <= 4)


def render(kind: str, options: list, table: dict, mmr: str, period: str,
           tribes: set | None = None) -> None:
    rows = []
    for opt in options:
        name, card = opt[0], opt[1]      # (name, card) or (name, card, screenPos)
        st = table.get(normalize(card, table))
        rows.append((name, card, st))

    # With the lobby's tribes known, re-score every hero for THIS lobby and rank
    # on that instead of the global average.
    adj = {card: lobby_adjust(st, tribes) for _, card, st in rows} if tribes else {}
    use_adj = any(v is not None for v in adj.values())

    def score(r):
        return adj.get(r[1]) if use_adj and adj.get(r[1]) is not None else r[2]["avg"]

    rated = [r for r in rows if r[2] and r[2]["avg"] is not None]
    rated.sort(key=score)
    unrated = [r for r in rows if not (r[2] and r[2]["avg"] is not None)]

    bar = "=" * 68
    tag = "  (tuned to this lobby)" if use_adj else ""
    print(f"\n{bar}\n  {kind.upper()}  -  top {mmr}% MMR, {period}{tag}\n{bar}")
    solid = [r for r in rated if r[2]["n"] >= MIN_SAMPLE]
    best_card = solid[0][1] if solid else None   # crown only a trustworthy sample
    for i, (name, card, st) in enumerate(rated, 1):
        thin = st["n"] < MIN_SAMPLE
        marker = " <<<" if card == best_card else ""
        t4 = top4_rate(st.get("dist"))
        t4s = f"  top4 {t4:4.1f}%" if t4 is not None else ""
        pick = f"{st['pick']:5.1f}%" if st["pick"] is not None else "    ?"
        n = f"n={st['n']:,}" + (" (thin!)" if thin else "")
        a = adj.get(card)
        if use_adj and a is not None:
            shift = a - st["avg"]
            avg_txt = f"avg {a:.2f} ({shift:+.2f})"
        else:
            avg_txt = f"avg {st['avg']:.2f}       "
        print(f"  {i}. {name[:26]:<26} {avg_txt}   picked {pick}{t4s}   {n}{marker}")
    for name, card, st in unrated:
        print(f"  -. {name[:26]:<26} no data at top {mmr}% MMR  ({card})")
    if len(solid) > 1:
        spread = solid[-1][2]["avg"] - solid[0][2]["avg"]
        print(f"  {'':30}spread {spread:.2f} places between best and worst")
    if len(solid) < len(rated):
        print(f"  {'':30}(thin) = under {MIN_SAMPLE} games, treat as no signal")
    print(bar)


# ---------------------------------------------------------------- lobby tribes

RACE_RE = re.compile(r"tag=CARDRACE value=([A-Z_]+)")


class MemoryTribes(threading.Thread):
    """
    The lobby's tribes, read out of Hearthstone's memory by the clean-room
    msync helper. This is the only way to know them AT HERO SELECT - the log
    says nothing about tribes until minions start appearing, several turns later.

    Optional: if msync.exe hasn't been built, everything falls back to log
    inference and simply knows less, later.
    """

    daemon = True

    def __init__(self):
        super().__init__()
        self.races = set()
        self.board = []        # cardIds of the minions on YOUR board, live
        self.hand = []
        self.trinkets = []
        self.rating = None
        self.error = "starting"
        self.proc = None

    @staticmethod
    def available() -> bool:
        return MSYNC_EXE.exists()

    def run(self):
        try:
            proc = subprocess.Popen(
                [str(MSYNC_EXE), "--watch"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.error = str(e)
            return
        self.proc = proc
        for line in proc.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            self.board = d.get("board") or []
            self.hand = d.get("hand") or []
            self.trinkets = d.get("trinkets") or []
            if d.get("rating", -1) > 0:
                self.rating = d["rating"]
            if d.get("ok"):
                self.races = {TRIBE_ID[r] for r in d.get("races") or [] if r in TRIBE_ID}
                self.error = None
            else:
                self.races = set()
                self.error = d.get("error") or "unknown"

    def stop(self):
        """Kill the helper. Without this it outlives the overlay and the next
        build fails on a locked exe (nine orphans, learned the hard way)."""
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        except Exception:
            pass


class LobbyTracker:
    """
    Which tribes this lobby is running, from the best source available.

    With the memory reader: the exact list, from hero select onward.
    Without it: inference from the log. Every minion carries its tribe, so
    seeing one PROVES that tribe is in - but an unseen tribe is merely
    unconfirmed, never provably excluded, and in a real game only 6 of 7 were
    identified within 6 minutes (~turn 5).
    """

    def __init__(self, memory: "MemoryTribes | None" = None):
        self.seen = set()          # what the log has proven
        self.memory = memory
        self._last = set()

    @property
    def tribes(self) -> set:
        if self.memory is not None and self.memory.races:
            return self.memory.races
        return self.seen

    @property
    def exact(self) -> bool:
        """True when the list is complete rather than 'what we've seen so far'."""
        return bool(self.memory is not None and self.memory.races)

    def feed(self, line: str) -> bool:
        """True when the effective tribe list changed, from either source."""
        m = RACE_RE.search(line)
        if m and m.group(1) in TRIBES:
            self.seen.add(m.group(1))
        current = self.tribes
        if current != self._last:
            self._last = set(current)
            return True
        return False

    def reset(self):
        self.seen = set()
        self._last = set()


def render_lobby(tracker: LobbyTracker, comps: list, mmr: str, limit: int = 8) -> None:
    tribes = tracker.tribes
    have = sorted(tribes)
    rest = [t for t in TRIBES if t not in tribes]
    bar = "-" * 68
    print(f"\n{bar}")
    if tracker.exact:
        print(f"  TRIBES IN  ({len(have)}/10, from memory): "
              + ", ".join(TRIBE_LABEL[t] for t in have))
        if rest:
            print(f"  out this lobby:              " + ", ".join(TRIBE_LABEL[t] for t in rest))
    else:
        print(f"  TRIBES IN  ({len(have)}/10 confirmed): "
              + ", ".join(TRIBE_LABEL[t] for t in have))
        if rest:
            print(f"  not seen yet:                " + ", ".join(TRIBE_LABEL[t] for t in rest))

    # A comp is playable only if its tribe is in. Neutral comps (tribe None) always are.
    playable = [c for c in comps if c["tribe"] is None or c["tribe"] in tribes]
    playable = [c for c in playable if c.get("baseline") or c["n"] >= MIN_SAMPLE][:limit]
    if playable:
        curated = playable[0].get("baseline")
        print("  comps open to you (curated - no stats configured):" if curated
              else f"  best comps available to you (top {mmr}% MMR):")
        for c in playable:
            tag = TRIBE_LABEL.get(c["tribe"], "any")
            head = "curated" if c.get("baseline") else f"{c['avg']:.2f}"
            tail = "" if c.get("baseline") else f"  n={c['n']:,}"
            print(f"    {head}  {c['archetype'].replace('_',' '):<26} [{tag}]{tail}")
            if c.get("key"):
                print(f"          build: {' / '.join(c['key'])}")
    print(bar)


# ---------------------------------------------------------------- log reading

def newest_power_log():
    if not HS_LOGS.exists():
        return None
    logs = sorted(HS_LOGS.glob("Hearthstone_*/Power.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


class OfferDetector:
    """
    Groups the burst of FULL_ENTITY lines that share one timestamp into a single
    'here are your options' event.

    Heroes on offer sit in the local player's HAND, so the zone alone identifies
    them. Trinkets sit in SETASIDE, which every player's trinkets pass through -
    those need the player-id filter as well.
    """

    def __init__(self, heroes: dict, trinkets: dict, universe: dict | None = None,
                 names: dict | None = None):
        # `universe` is the unfiltered hero list, used only to RECOGNISE a hero.
        # Recognising against the MMR-filtered table would silently drop options
        # that are too rare in that bracket to have stats.
        self.heroes = universe if universe is not None else heroes
        self.trinkets = trinkets
        self.names = names or {}   # cardId -> display name, for rerolled-in heroes
        self.ts = None
        self.buf = []
        self.player = None      # our player id, learned from the hero draft
        # Entity ids already seen THIS GAME, so one entity is never counted twice.
        # Ids restart each game (93-96, then 89-92...), hence the reset on a draft.
        self.known = set()
        self.new_game = False   # set on a draft; the caller clears it
        self._live = {}         # entity id -> [name, card, pos] of the open hero offer
        self._live_ts = None    # timestamp of the settle block; freeze after it
        self.refresh = None     # re-issued offer after ZONE_POSITION corrections

    def feed(self, line: str):
        m = ENTITY_RE.match(line)
        if not m:
            # The client shuffles the offered heroes into their final on-screen
            # order AFTER the offer burst; track those corrections and expose a
            # refreshed offer so a UI can move its badges to the right cards.
            if self.buf or self._live:
                ch = CHANGE_RE.search(line)
                if ch:
                    eid, newc = int(ch.group("id")), ch.group("card")
                    newn = self.names.get(newc, newc)
                    for ent in self.buf:
                        if ent[4] == eid:
                            ent[1], ent[2] = newn, newc
                    if eid in self._live:
                        e = self._live[eid]
                        e[0], e[1] = newn, newc
                        poss = [q for _, _, q in self._live.values()]
                        if min(poss) >= 1 and len(set(poss)) == len(poss):
                            self.refresh = ("hero choice",
                                            [(n, c, q) for n, c, q in self._live.values()])
                g = TAGPOS_RE.match(line)
                if g:
                    eid, p = int(g.group("id")), int(g.group("pos"))
                    # The settle shuffle shares the offer burst's timestamp, so
                    # it usually lands while the offer is still in the buffer -
                    # correct it there and the offer emits right the first time.
                    for ent in self.buf:
                        if ent[4] == eid:
                            ent[3] = p
                    if eid in self._live:
                        ent = self._live[eid]
                        if p != ent[2]:
                            ent[2] = p
                            # Zeros and collisions are transit states (the pick
                            # zeroes everything) - only a clean permutation is a
                            # real on-screen arrangement worth re-emitting.
                            poss = [q for _, _, q in self._live.values()]
                            if min(poss) >= 1 and len(set(poss)) == len(poss):
                                self.refresh = ("hero choice",
                                                [(n, c, q) for n, c, q in self._live.values()])
            # Any later-stamped line closes the pending group. Without this the
            # group would wait for the NEXT offer, which in a replay is minutes
            # of game time away.
            t = TS_RE.match(line)
            if t and self.buf and t.group(1) != self.ts:
                return self.flush()
            return None
        card, zone = m["card"], m["zone"]
        kind = None
        if zone == "HAND" and normalize(card, self.heroes) in self.heroes:
            # The heroes on offer are dealt into OUR hand, so this also tells us
            # which player id is us - needed to filter trinkets below.
            self.player = m["player"]
            kind = "hero choice"
        elif zone == "SETASIDE" and card in self.trinkets:
            # Trinkets are staged in SETASIDE, and every player's are logged.
            # Keep only ours once we know who we are.
            if self.player is not None and m["player"] != self.player:
                return None
            kind = "trinket choice"
        else:
            return None

        flushed = None
        if m["ts"] != self.ts:
            flushed = self.flush()
            self.ts = m["ts"]
            if kind == "hero choice":
                # Heroes are drafted once, so this is a new game. Flag it here
                # rather than when the group is emitted - the group is only
                # emitted minutes later, and anything keyed off it resets late.
                self.known = set()
                self.new_game = True
        if m["id"] in self.known:      # a restatement of a card already in play
            return flushed
        self.known.add(m["id"])
        # zonePos is the on-screen slot (1..4 left to right for heroes), which is
        # what lets a UI attach a stat to the right character instead of a list.
        # A list, not a tuple: ZONE_POSITION corrections update it in place.
        self.buf.append([kind, m["name"], card, int(m["pos"] or 0), int(m["id"])])
        return flushed

    def flush(self):
        """Emit the pending choice, if it is one. Safe to call any time."""
        buf, self.buf = self.buf, []
        if len(buf) < 2:               # a single card is not a choice
            return None
        kind = buf[0][0]
        # A real trinket offer is always four options. Everything else staged in
        # SETASIDE is an opponent's pair of trinkets being revealed as you fight
        # them - across 19 real games that noise was 2s, 1s, 3s and 6s, while the
        # genuine offers were 36 clean bursts of exactly 4.
        if kind == "trinket choice" and len(buf) != TRINKET_OPTIONS:
            return None
        if kind == "hero choice":
            # Keep the offer live: ZONE_POSITION corrections arriving after this
            # point update these slots and surface through self.refresh.
            self._live = {i: [n, c, p] for _, n, c, p, i in buf}
        else:
            self._live = {}
        self._live_ts = None
        return (kind, [(n, c, p) for _, n, c, p, i in buf])

    def reset(self):
        self.ts = None
        self.buf = []
        self.player = None
        self.known = set()
        self._live = {}
        self._live_ts = None
        self.refresh = None


def follow(path: Path):
    """
    Tail a file, surviving Hearthstone rotating to a new log.

    Yields each new line, and yields None the moment it catches up. That idle
    signal is what makes the overlay timely: the four hero lines land in one
    burst, the reader goes idle a fraction of a second later, and we print
    then - instead of waiting for some unrelated later line to arrive.
    """
    f = open(path, "r", encoding="utf-8", errors="ignore")
    f.seek(0, os.SEEK_END)
    current = path
    idle = True          # already caught up at start; don't emit a flush yet
    last_rotate_check = 0.0
    try:
        while True:
            line = f.readline()
            if line:
                idle = False
                yield line
                continue
            if not idle:
                idle = True
                yield None          # caught up -> flush whatever is pending
            time.sleep(0.25)
            now = time.monotonic()
            if now - last_rotate_check < 2.0:
                continue
            last_rotate_check = now
            newest = newest_power_log()
            if newest and newest != current:
                print(f"\n  -> new game session, following {newest.parent.name}")
                f.close()
                f = open(newest, "r", encoding="utf-8", errors="ignore")
                current = newest
                yield None          # drop anything half-collected from the old log
    finally:
        f.close()


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Live Battlegrounds pick stats from your own game log.")
    ap.add_argument("--mmr", default="100", choices=["100", "50", "25", "10", "1"],
                    help="MMR bucket: 100=all, 1=top 1%% (default: 100)")
    ap.add_argument("--time", default="last-patch",
                    choices=["all-time", "past-three", "past-seven", "last-patch"])
    ap.add_argument("--duo", action="store_true", help="use Duos stats")
    ap.add_argument("--replay", nargs="?", const="__newest__", default=None,
                    help="scan an existing log instead of following live")
    ap.add_argument("--refresh", action="store_true", help="force re-download of stats")
    ap.add_argument("--comps", action="store_true",
                    help="just print the comp rankings and exit")
    ap.add_argument("--no-lobby", action="store_true",
                    help="don't show the tribe/comp panel during games")
    args = ap.parse_args()

    print("bgtracker - loading ...")
    comps = comp_table(args.time, args.mmr, args.refresh)

    if args.comps:
        if not comps:
            sys.exit("  no comps available (offline and no card-pool cache yet)")
        curated = bool(comps and comps[0].get("baseline"))
        print(f"\n  COMPS  -  " + ("curated baseline (no stats configured)"
                                   if curated else f"top {args.mmr}% MMR, {args.time}")
              + "\n" + "=" * 68)
        for c in comps:
            if not c.get("baseline") and c["n"] < MIN_SAMPLE:
                continue
            tag = TRIBE_LABEL.get(c["tribe"], "any")
            head = "curated" if c.get("baseline") else f"{c['avg']:.2f}"
            tail = "" if c.get("baseline") else f"  n={c['n']:,}"
            print(f"  {head}  {c['archetype'].replace('_',' '):<26} [{tag}]{tail}")
            if c.get("key"):
                print(f"        build: {' / '.join(c['key'])}")
        print("=" * 68)
        return

    heroes = hero_table(args.mmr, args.time, args.duo, args.refresh)
    trinkets = trinket_table(args.time, args.mmr, args.refresh)
    # Recognition comes from the card database, not from any stats table, so
    # every offer is detected and named even with no stats configured at all.
    hero_ids = hero_universe(args.refresh)
    trinket_ids = trinket_universe(args.refresh)
    if heroes or trinkets:
        print(f"  stats: {len(heroes)} heroes, {len(trinkets)} trinkets"
              f"  (top {args.mmr}% MMR, {args.time}{', duos' if args.duo else ''})")
    else:
        print("  no stats sources configured - offers will show without numbers"
              " (README: 'Bring your own stats')")

    det = OfferDetector(heroes, trinket_ids, hero_ids)

    memory = None
    if MemoryTribes.available() and args.replay is None:
        memory = MemoryTribes()
        memory.start()
        print("  reading lobby tribes from game memory")
    elif args.replay is None:
        print("  tribes will be inferred from the log (build native/msync for the exact list)")
    lobby = LobbyTracker(memory)

    def show(event):
        if not event:
            return
        kind, opts = event
        table = heroes if kind == "hero choice" else trinkets
        # Only heroes have per-tribe stats to re-score against.
        render(kind, opts, table, args.mmr, args.time,
               lobby.tribes if kind == "hero choice" else None)

    def track(line):
        """Returns True when a newly confirmed tribe should refresh the panel."""
        if det.new_game:           # a draft was just seen: fresh lobby, fresh tribes
            det.new_game = False
            lobby.reset()
        return lobby.feed(line) and not args.no_lobby

    if args.replay is not None:
        path = newest_power_log() if args.replay == "__newest__" else Path(args.replay)
        if not path or not path.exists():
            sys.exit(f"no Power.log found (looked in {HS_LOGS})")
        print(f"  replaying {path}  ({path.stat().st_size / 1e6:.0f} MB)\n")
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                show(det.feed(line))
                if track(line):
                    render_lobby(lobby, comps, args.mmr)
        show(det.flush())
        return

    path = newest_power_log()
    if not path:
        sys.exit(f"no Power.log found. Is Hearthstone installed at {HS_LOGS.parent}?")
    print(f"  watching {path.parent.name}/Power.log")
    print("  waiting for a Battlegrounds game ... (Ctrl+C to stop)")
    try:
        for line in follow(path):
            if line is None:
                show(det.flush())
                continue
            show(det.feed(line))
            if track(line):
                render_lobby(lobby, comps, args.mmr)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
