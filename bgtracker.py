#!/usr/bin/env python3
"""
bgtracker - live Hearthstone Battlegrounds pick helper.

Reads Hearthstone's own Power.log, spots the moment you're offered heroes
(or trinkets), and shows each option - with average placement and pick rate
from the COMMUNITY feed by default, or from any source you configure in
sources.json (see README).

The community feed is our own pooled data: built only from games players
shared, aggregates free for everyone, never sold or paywalled. No third
party's stats are bundled or fetched - aggregate placement data belongs to
whoever collected it, and the only pool this points at is the one whose
games were given to it. Card names and IDs come from HearthstoneJSON.
The OVERLAY (overlay.py) also shares your finished games back to that pool
BY DEFAULT - anonymised records, no names, no battletags; the settings
panel's DATA section lists every field and holds the off switch, and
--no-upload stops it for one run (see README). This console version never
uploads anything on its own; `collect.py --upload` is its by-hand path.

Usage:
    python bgtracker.py                     # live: follow the newest Power.log
    python bgtracker.py --replay            # replay the newest log, show past offers
    python bgtracker.py --replay <path>     # replay a specific Power.log
    python bgtracker.py --mmr 10            # use top-10% stats (100/50/25/10/1)
    python bgtracker.py --time past-seven   # all-time|past-three|past-seven|last-patch
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from paths import APP_DIR, BUNDLE_DIR

# The stats feed: sources.json next to this file, with any of the keys
#   heroes, trinkets, comps, cards
#   heroes_duo, trinkets_duo, comps_duo, cards_duo   (what --duo reads)
# each mapping to a URL or a local JSON file you have the right to use
# ({mmr} and {time} placeholders are filled in). With NO sources.json the
# overlay reads the COMMUNITY feed (default_sources below) - the pool built
# only from games players shared - so a fresh install both gives and gets.
# Writing sources.json, with any subset of the keys, replaces that default
# entirely: a key you leave out is a table you asked to keep empty, and the
# default never fills it back in behind your edit.
# APP_DIR rather than __file__: in a frozen build __file__ points inside
# PyInstaller's private bundle, so this file - and the cache, and the memory
# reader - would land somewhere the user never sees. See paths.py.
SOURCES_FILE = APP_DIR / "sources.json"

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
MSYNC_EXE = APP_DIR / "native" / "msync" / "bin" / "Release" / "net48" / "msync.exe"

CACHE_DIR = APP_DIR / ".cache"
CACHE_TTL = 3600  # stats feeds typically rebuild hourly; don't refetch faster

# Below this many games an average placement is noise, not a signal.
MIN_SAMPLE = 30

# A trinket offer always presents exactly four options.
TRINKET_OPTIONS = 4

# Where Hearthstone writes its logs. Three sources, most deliberate first, and
# the answer is settled once at import so every consumer agrees for the whole
# run. Asked for by the first outside contributor (issue #1) and by the first
# beta tester, who hit the same wall from the other side: an install anywhere
# but the default path left the overlay saying "waiting for game" forever.
#
#   1. `hs_logs` in settings.json - somebody who set it explicitly is right by
#      definition; a set-but-wrong path is REPORTED, never silently swapped
#      for a guess, because the overlay watching a different folder than the
#      one the user named is the harder bug to see.
#   2. The registry: Blizzard writes InstallLocation on install, so a D: drive
#      or a moved install is found with zero configuration. Both registry
#      views are read, since a 32-bit process sees the WOW6432Node copy.
#   3. The historical default, exactly as before.


def _hs_logs_dir() -> Path:
    default = (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
               / "Hearthstone" / "Logs")
    try:
        import settings as _settings
        configured = (_settings.Settings.load().get("hs_logs") or "").strip()
    except Exception:
        configured = ""
    if configured:
        p = Path(os.path.expandvars(configured)).expanduser()
        # The Logs folder or the install folder are both accepted: "where is
        # Hearthstone" is the question a user can actually answer.
        return p if p.name.lower() == "logs" else p / "Logs"
    try:
        import winreg
        for hive, key in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Blizzard Entertainment\Hearthstone"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Blizzard Entertainment\Hearthstone"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                if loc and (Path(loc) / "Logs").is_dir():
                    return Path(loc) / "Logs"
            except OSError:
                continue
    except Exception:
        pass
    return default


HS_LOGS = _hs_logs_dir()

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


_DEFAULT_SOURCES = None


def default_sources() -> dict:
    """The community feed's table templates - what a machine with NO
    sources.json reads, so a fresh download shows numbers and (unless the
    switch is off) gives its games back, with zero setup.

    Read out of sources.example.json, which ships in the release zip, rather
    than written out again here: two copies of a url is one copy that goes
    stale the day the feed moves. A user's own copy beside the exe wins over
    the bundled one, same as every other shipped file. If the example file is
    gone too, the tables are rebuilt off the one host constant the uploader
    already uses (settings.COMMUNITY_UPLOAD)."""
    global _DEFAULT_SOURCES
    if _DEFAULT_SOURCES is not None:
        return _DEFAULT_SOURCES
    out = {}
    for base in (APP_DIR, BUNDLE_DIR):
        try:
            raw = json.loads((base / "sources.example.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        out = {k: v for k, v in raw.items()
               if not k.startswith("_") and isinstance(v, str) and v}
        if out:
            break
    if not out:
        import settings as _settings
        host = _settings.COMMUNITY_UPLOAD.rstrip("/")
        out = {k + d: f"{host}/{k}{'-duo' if d else ''}-{{mmr}}-{{time}}.json"
               for k in ("heroes", "trinkets", "cards", "comps")
               for d in ("", "_duo")}
    _DEFAULT_SOURCES = out
    return out


def raw_source(kind: str):
    """The un-formatted template for one table - {mmr} and {time} still in it.
    The template, not just the filled-in URL, is what tells us whether this
    feed is bucketed at all. From sources.json when the user wrote one; the
    community default stands in ONLY when the file does not exist at all, so
    a hand-written file with a key removed keeps that table empty."""
    try:
        srcs = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_sources().get(kind) or None
    except json.JSONDecodeError as e:
        sys.exit(f"sources.json is not valid JSON: {e}")
    src = srcs.get(kind)
    return src if isinstance(src, str) and src else None


def stats_source(kind: str, **fmt):
    """The user-configured source for one stats table (sources.json).
    Returns a URL or file path, or None when the user hasn't configured one."""
    src = raw_source(kind)
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
            p = APP_DIR / p
        return json.loads(p.read_text(encoding="utf-8"))
    CACHE_DIR.mkdir(exist_ok=True)
    # The source itself is part of the key. Without it, pointing sources.json at
    # a different server keeps serving the old server's cached numbers, and a
    # fetch failure "falls back" to a feed you are no longer using - which is a
    # wrong number, silently. (Caught live while testing MMR buckets.)
    path = CACHE_DIR / f"{key}-{hashlib.sha1(source.encode()).hexdigest()[:8]}.json"
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


# The MMR buckets a feed can publish, widest pool first. 100 = every player.
MMR_BUCKETS = ["100", "50", "25", "10", "1"]

# Which bucket each table was actually served from, after any fallback. The
# label on screen has to say what the numbers ARE, not what was asked for.
USED_MMR: dict[str, str] = {}


def bucket_in_use(kind: str, requested: str) -> str:
    """The bucket `kind`'s numbers actually came from (see load_bucket)."""
    return USED_MMR.get(kind, requested)


# Duos reads its own four sources.json keys - heroes_duo, trinkets_duo,
# cards_duo, comps_duo - and there is deliberately NO fallback to the solo feed.
# Duos is four teams placing 1st-4th where solo is eight players placing 1st-8th,
# on a different hero pool, so a solo number shown under a duos heading would be
# worse than showing nothing. With no duos source configured the table comes back
# empty and every option renders as "no data", which is the honest answer.
# server/aggregate.py builds these files from duos games only.
def source_kind(kind: str, duo: bool) -> str:
    """The sources.json key for one table in one game mode."""
    return f"{kind}_duo" if duo else kind


def _declared_bucket(data, asked: str) -> str:
    """What the feed itself says this file is. Our aggregator stamps every file
    with {"mmr": {"bucket": N, "minRating": R, ...}}, and that beats what we
    asked for: a source URL with no {mmr} placeholder returns the same file
    whatever bucket you request, and calling it 'top 1%' would be a lie. A feed
    that carries no stamp gets the benefit of the doubt."""
    got = (data or {}).get("mmr")
    if isinstance(got, dict) and got.get("bucket") is not None:
        return str(got["bucket"])
    return asked


# "-{mmr}" / "_{mmr}" / "{mmr}" anywhere in a template, so the pre-bucket file
# name can be derived from the bucketed one: heroes-{mmr}-{time} -> heroes-{time}.
MMR_TAG_RE = re.compile(r"[-_]?\{mmr\}")


def bucket_sources(kind: str, mmr: str, period: str):
    """Where to look for one table, best first, each with the bucket it deserves
    to be labelled as:

      1. the bucket that was asked for;
      2. the all-players bucket - a young feed publishes a bucket only once it
         holds enough games, so top-1% may simply not exist yet;
      3. the pre-bucket file name (heroes-{time}.json), for a server that has
         not been rebuilt since buckets existed. Our aggregator still writes it
         as a twin of bucket 100, and an older one writes nothing else.

    Only 1 exists when the template has no {mmr} in it; then that one file
    answers for every bucket, exactly as before."""
    raw = raw_source(kind)
    if not raw:
        return []

    def fill(tpl, m):
        try:
            return tpl.format(mmr=m, time=period)
        except (KeyError, IndexError):
            return tpl

    cands = [(fill(raw, mmr), mmr)]
    if "{mmr}" in raw:
        cands.append((fill(raw, "100"), "100"))
        cands.append((fill(MMR_TAG_RE.sub("", raw), "100"), "100"))
    out, seen = [], set()
    for url, label in cands:
        if url and url not in seen:
            seen.add(url)
            out.append((url, label))
    return out


def load_bucket(kind: str, listkey: str, mmr: str, period: str, refresh: bool = False):
    """One stats table for one MMR bucket, with an honest fallback.

    Walks bucket_sources() in order and takes the first file that actually has
    rows, recording in USED_MMR what was really used so the caller can label it
    truthfully - showing the whole pool under a "top 1%" heading would be a
    wrong number, which this project treats the same as a made-up one."""
    cands = bucket_sources(kind, mmr, period)
    if not cands:                       # nothing configured: quietly no numbers
        USED_MMR[kind] = mmr
        return {}
    first_err, blank = None, {}
    for i, (url, label) in enumerate(cands):
        try:
            data = load_stats(url, f"{kind}-{label}-{period}", refresh)
        except Exception as e:
            first_err = first_err or e
            continue
        if data.get(listkey):
            if i and label != mmr:      # a different FILE for the same bucket is
                                        # not worth a word; a different BUCKET is
                print(f"  ! no top {mmr}% {kind} feed yet - showing top {label}%",
                      file=sys.stderr)
            USED_MMR[kind] = _declared_bucket(data, label)
            return data
        blank = blank or data
    if first_err and not blank:
        if len(cands) == 1:
            raise first_err             # one source and it is dead: fail as before
        print(f"  ! {kind} feed unreachable ({first_err}) - no numbers", file=sys.stderr)
    USED_MMR[kind] = _declared_bucket(blank, mmr)
    return blank


def hero_table(mmr: str, period: str, duo: bool = False, refresh: bool = False) -> dict:
    """cardId -> {avg placement, pick rate, sample size}."""
    data = load_bucket(source_kind("heroes", duo), "heroStats", mmr, period, refresh)
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


def trinket_table(period: str, mmr: str, refresh: bool = False, duo: bool = False) -> dict:
    data = load_bucket(source_kind("trinkets", duo), "trinketStats", mmr, period, refresh)
    out = {}
    bucketed = False
    for t in data.get("trinketStats", []):
        avg = t.get("averagePlacement")
        for row in t.get("averagePlacementAtMmr") or []:      # prefer the requested MMR bucket
            if str(row.get("mmr")) == str(mmr):
                avg = row.get("placement")
                bucketed = True     # this row IS the asked-for bucket, inline
                break
        out[t["trinketCardId"]] = {
            "avg": avg,
            "pick": 100.0 * t["pickRate"] if t.get("pickRate") is not None else None,
            "n": t.get("dataPoints", 0),
            "dist": [],
        }
    if bucketed:
        USED_MMR[source_kind("trinkets", duo)] = mmr   # served from the all-players
                                        # file, but the numbers are the asked bucket's
    return out


def hero_power_table(mmr: str, period: str, duo: bool = False,
                     refresh: bool = False) -> dict:
    """cardId -> {avg placement, pick rate, sample size} for HERO POWERS.

    The pick panel has always been able to NAME the powers on offer and never
    to rate them, because no feed publishes hero-power numbers. Ours does now
    (server/aggregate.py hero_power_stats), built exactly like the hero table
    out of the games players shared: the offer is the denominator, the pick is
    the numerator, the placement is the game's own result.

    Same shape and the same fallback as every other table - an unconfigured or
    empty source means {} and every option keeps showing a dash, which is what
    it showed before this existed.

    THE SAMPLE FLOOR, and why this table enforces it where the others do not.
    The aggregator publishes thin rows on purpose and leaves the flagging to
    the client (server/aggregate.py says so), which works for heroes and
    trinkets because their window draws the sample size right under the number
    and writes "thin!" beside it (ui/base.offer_rows, called with MIN_SAMPLE).
    The hero-power window draws the number alone - no sample, nowhere to put a
    flag - so an average built on one game would be shown there as a plain
    fact. Rows under MIN_SAMPLE therefore keep their `n` and lose their number:
    a dash, which is the same thing the window showed when no feed existed.
    Rows with dataPoints 0 (a power offered but never picked - the aggregator
    publishes those for the pick rate) fall out under exactly this rule.
    """
    data = load_bucket(source_kind("heropowers", duo), "heroPowerStats",
                       mmr, period, refresh)
    out = {}
    for h in data.get("heroPowerStats", []):
        offered = h.get("totalOffered") or 0
        n = h.get("dataPoints", 0) or 0
        thin = n < MIN_SAMPLE
        out[h["heroPowerCardId"]] = {
            "avg": None if thin else h.get("averagePosition"),
            # The pick rate rides on the same floor. It has its own, larger
            # denominator (every showing, not every finished game), but a rate
            # printed next to a suppressed average would read as the number the
            # dash is refusing to give.
            "pick": None if thin or not offered else 100.0 * h.get("totalPicked", 0) / offered,
            "n": n,
            "thin": thin,
            "dist": [] if thin else (h.get("placementDistribution") or []),
        }
    return out


def card_table(mmr: str, period: str, refresh: bool = False, duo: bool = False) -> dict:
    """cardId -> {avg placement when played, sample}. Powers the tavern panel."""
    data = load_bucket(source_kind("cards", duo), "cardStats", mmr, period, refresh)
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


# Community hero tips: written text, not collected data, so unlike every stats
# table this one SHIPS with the tool. It is a plain file people edit by pull
# request (data/hero_tips.schema.json + CONTRIBUTING.md); that review, and the
# vote below it, are the whole quality mechanism, and both are why nothing here
# may be copied from anyone else's guide.
_TIPS_CACHE = None


def hero_tips(refresh: bool = False) -> dict:
    """cardId -> {"when": str, "bullets": [str], "tribes": [str]}.

    Read from data/hero_tips.json. A user's own copy beside the exe wins over
    the bundled one, so an edit survives an update instead of being overwritten
    by it (APP_DIR vs BUNDLE_DIR - see paths.py).

    A missing, unreadable or malformed file is not an error: it means no tips,
    and every surface draws nothing rather than a placeholder. Entries that do
    not match the schema are skipped one by one, so one bad pull request cannot
    take the whole file down with it.
    """
    global _TIPS_CACHE
    if _TIPS_CACHE is not None and not refresh:
        return _TIPS_CACHE
    out = {}
    for base in (APP_DIR, BUNDLE_DIR):
        try:
            doc = json.loads((base / "data" / "hero_tips.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        for cid, e in (doc.get("tips") or {}).items():
            if not isinstance(e, dict) or not isinstance(e.get("when"), str):
                continue
            bullets = [b for b in (e.get("bullets") or []) if isinstance(b, str)]
            tribes = [t for t in (e.get("tribes") or []) if t in TRIBES]
            out[cid] = {"name": e.get("name"), "when": e["when"].strip(),
                        "bullets": bullets, "tribes": tribes, "source": "shipped"}
        break                    # first file found wins; they are not merged
    _TIPS_CACHE = out
    return out


_CURVES_CACHE = None


def hero_curves(refresh: bool = False) -> dict:
    """The tavern leveling curves: {"default": {...}, "by_name": {hero name ->
    bucket dict}}, each bucket {"label", "curve" (tier -> turn, int keys),
    "note"}.

    Same class of data as hero_tips: curated written strategy (researched from
    public guides, dated inside the file), shipped as text, never scraped
    stats. Same read rule too: the user's own data/curves.json beside the exe
    wins over the bundled copy, and a missing or malformed file means no
    curves - the curve window simply never opens.
    """
    global _CURVES_CACHE
    if _CURVES_CACHE is not None and not refresh:
        return _CURVES_CACHE
    out = {"default": None, "by_name": {}, "season": ""}

    def clean(b):
        curve = {int(k): int(v) for k, v in (b.get("curve") or {}).items()
                 if str(k).isdigit() and isinstance(v, int) and 1 <= v <= 20}
        if not curve or not isinstance(b.get("label"), str):
            return None
        return {"label": b["label"], "curve": curve,
                "note": b.get("note", "") if isinstance(b.get("note"), str) else ""}

    for base in (APP_DIR, BUNDLE_DIR):
        try:
            doc = json.loads((base / "data" / "curves.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        out["default"] = clean(doc.get("default") or {})
        out["season"] = doc.get("season", "") if isinstance(doc.get("season"), str) else ""
        for b in (doc.get("buckets") or {}).values():
            bucket = clean(b)
            if bucket is None:
                continue
            for nm in (b.get("heroes") or []):
                if isinstance(nm, str):
                    out["by_name"][nm] = bucket
        break                    # first file found wins; they are not merged
    _CURVES_CACHE = out
    return out


# The voted half of the same pipeline. server/tips.py collects submissions and
# votes and publishes ONE file - the current best-voted line per hero, and only
# for the heroes where the vote produced a clear winner (its floors: distinct
# voters, score, and a margin over the shipped line). So this is read exactly
# like every other feed, through the same sources.json key -> load_stats path,
# and every failure lands in the same place: no key, no server, no network, a
# corrupt file, an entry that breaks the shape - the shipped tip is shown.
COMMUNITY_TIPS_FILE = "hero-tips-community.json"
_COMMUNITY_TIPS = None


def _community_tips_source():
    """Where the voted tips come from, or None.

    sources.json wins. A hand-written sources.json that does not name
    `hero_tips` means that feed stays OFF, same law as every other table: a key
    you left out is a table you asked to keep empty. With no sources.json at
    all, a fresh install reads the community host, the one the uploader already
    talks to - so giving and getting stay the same decision."""
    src = raw_source("hero_tips")
    if src:
        return src
    if SOURCES_FILE.exists():
        return None
    import settings as _settings
    return f"{_settings.COMMUNITY_UPLOAD.rstrip('/')}/{COMMUNITY_TIPS_FILE}"


def _community_doc(refresh: bool = False) -> dict:
    """The published feed, parsed and bounded, or an empty one.

    Everything in here was typed by a stranger and voted on by strangers, so it
    is treated like any other untrusted feed rather than like the file that
    ships: entries are re-checked against the same lengths the schema states,
    and one that fails is dropped alone. A tip that is 5000 characters long is
    not a long tip, it is a broken feed."""
    global _COMMUNITY_TIPS
    if _COMMUNITY_TIPS is not None and not refresh:
        return _COMMUNITY_TIPS
    out = {"tips": {}, "vote_url": None}
    try:
        src = _community_tips_source()
        doc = load_stats(src, "hero-tips", refresh) if src else {}
        for cid, e in ((doc or {}).get("tips") or {}).items():
            if not isinstance(e, dict) or not isinstance(e.get("when"), str):
                continue
            when = " ".join(e["when"].split())
            if not 8 <= len(when) <= 80:
                continue
            bullets = [" ".join(b.split()) for b in (e.get("bullets") or [])
                       if isinstance(b, str) and 8 <= len(" ".join(b.split())) <= 100]
            out["tips"][cid] = {"name": None, "when": when, "bullets": bullets[:3],
                                "tribes": [], "source": "community",
                                "votes": e.get("score"), "voters": e.get("voters")}
        url = (doc or {}).get("vote_url")
        if isinstance(url, str) and url.startswith(("http://", "https://")) and len(url) <= 120:
            out["vote_url"] = url
    except Exception:
        out = {"tips": {}, "vote_url": None}
    _COMMUNITY_TIPS = out
    return out


def community_tips(refresh: bool = False) -> dict:
    """cardId -> the community's best-voted tip, for the heroes that have one.

    The FIRST call can hit the network. Never make it from a drawing thread -
    ask community_tips_ready() there and call warm_community_tips() early."""
    return _community_doc(refresh)["tips"]


def community_tips_ready() -> bool:
    """True once the feed has been loaded (or failed) and asking is free."""
    return _COMMUNITY_TIPS is not None


def warm_community_tips():
    """Load the feed on a background thread.

    The draft window asks for tips inside a Tk callback, and this feed is the
    one tip source that can be a URL. A 30 second urlopen on that thread would
    freeze the overlay over the game for the whole hero select - the exact
    moment the window exists for. So the fetch happens here, off to one side,
    and every reader checks community_tips_ready() first and shows the shipped
    line until the answer arrives. Nothing waits for it."""
    if _COMMUNITY_TIPS is not None:
        return
    threading.Thread(target=_community_doc, daemon=True).start()


def tips_vote_url() -> str | None:
    """Where a person votes on these lines, if the feed names a page. None when
    there is no feed, or the operator publishes one without a page - in which
    case nothing about voting is shown, rather than a link to nowhere."""
    return _community_doc()["vote_url"]


def hero_tip(card_id: str) -> dict | None:
    """The tip for one hero, or None. Golden/skin suffixes never appear on a
    hero cardId, so this is a plain lookup.

    The community's line wins where the vote produced one, otherwise the line
    that ships. Every entry says which it is in `source`, because a stranger's
    voted line and a reviewed one are not the same claim and the draft window
    has to be able to say so."""
    return community_tips().get(card_id) or hero_tips().get(card_id)


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


def comp_table(period: str, mmr: str, refresh: bool = False, duo: bool = False) -> list:
    """The archetypes behind the 'comps' page: what to build, and how it places.

    With a configured comps source: real measured rows (avg placement + n).
    Without one (or while it's still empty): the CURATED baseline - evergreen
    tribe families whose core minions are computed from the live card pool, so
    the panel is useful with zero stats and never shows a stale list. The
    baseline is tribe-mechanic families, not measured placements, so it is the
    same honest starting point in duos as in solo."""
    data = load_bucket(source_kind("comps", duo), "compStats", mmr, period, refresh)
    names = card_names(refresh)
    out = []
    for c in data.get("compStats", []):
        avg = c.get("averagePlacement")
        n = c.get("dataPoints", 0)
        for row in c.get("averagePlacementAtMmr") or []:
            if str(row.get("mmr")) == str(mmr):
                avg = row.get("placement", avg)
                n = row.get("dataPoints", n)
                USED_MMR[source_kind("comps", duo)] = mmr
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
    and the card grades score on (id/name/techLevel/attack/health/races/
    mechanics/text), cached a day."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "bgpool.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        cached = json.loads(path.read_text(encoding="utf-8"))
        # attack/health joined this row shape on 2026-08-13. A cache written
        # before that carries every other field, so it would not look broken -
        # it would quietly grade every minion as a 0/0 body. Treat the old
        # shape as stale and refetch instead of trusting it.
        if cached and "attack" in cached[0]:
            return cached
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    pool = [{"id": c["id"], "name": c.get("name", c["id"]),
             "techLevel": c.get("techLevel", 0),
             "attack": c.get("attack", 0), "health": c.get("health", 0),
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


# ------------------------------------------------------------------ comp roles

# data/comp_roles.json: what makes a minion CORE to a family versus an ADD-ON,
# expressed as ROLES (identity mechanics + text patterns), never card lists -
# a card list rots every patch, what a card SAYS does not. The file ships with
# the tool like hero_tips does; roles only DESCRIBE, every card shown still
# comes out of the live pool.
_ROLES_CACHE = None
_POOL_BY_NAME = None
_DIFF_CACHE: dict = {}


def _role(raw) -> dict | None:
    """One validated role: {'mechanics': set, 'rx': compiled | None}.
    A role with neither signal can never match and is treated as absent."""
    if not isinstance(raw, dict):
        return None
    mechs = {m for m in (raw.get("mechanics") or []) if isinstance(m, str)}
    rx = None
    if isinstance(raw.get("text"), str) and raw["text"]:
        try:
            rx = re.compile(raw["text"])
        except re.error:
            rx = None
    if not mechs and rx is None:
        return None
    return {"mechanics": mechs, "rx": rx}


def comp_roles(refresh: bool = False) -> dict:
    """archetype -> {'archetype', 'core', 'addons', 'tribes'}, from
    data/comp_roles.json.

    Read like hero_tips: a user's own copy beside the exe wins over the
    bundled one (APP_DIR vs BUNDLE_DIR), a missing or malformed file means no
    roles - the comps window then draws its flat list, never a guessed split -
    and bad entries are skipped one by one so a single edit cannot take the
    whole file down.
    """
    global _ROLES_CACHE
    if _ROLES_CACHE is not None and not refresh:
        return _ROLES_CACHE
    out = {}
    for base in (APP_DIR, BUNDLE_DIR):
        try:
            doc = json.loads((base / "data" / "comp_roles.json")
                             .read_text(encoding="utf-8"))
        except Exception:
            continue
        for fam in doc.get("families") or []:
            if not isinstance(fam, dict) or not isinstance(fam.get("archetype"), str):
                continue
            core = _role(fam.get("core"))
            if core is None:
                continue             # no core role = nothing to split on
            out[fam["archetype"]] = {
                "archetype": fam["archetype"],
                "core": core,
                "addons": _role(fam.get("addons")),
                "tribes": [t for t in (fam.get("wants_tribes") or []) if t in TRIBES],
            }
        break                        # first file found wins; they are not merged
    _ROLES_CACHE = out
    return out


def _plain_text(t: str) -> str:
    """Card text as the player reads it: markup tags and the [x] no-wrap
    marker dropped, whitespace squeezed, so a role pattern matches words."""
    return re.sub(r"\s+", " ", re.sub(r"</?[^>]+>|\[x\]", "", t or ""))


def _role_hit(minion: dict, role: dict | None) -> bool:
    """Does this pool minion carry the role? Judged off the card's OWN
    keywords and text - computed per card, never authored per card."""
    if not role:
        return False
    if role["mechanics"].intersection(minion["mechanics"]):
        return True
    return bool(role["rx"] and role["rx"].search(_plain_text(minion["text"])))


def comp_roles_for(archetype: str, tribe: str | None) -> dict | None:
    """The roles entry behind one comp row.

    A curated row names its family directly. A stats feed speaks its own
    archetype keys ('mech_magnet', 'beast_lobster'), so those map through the
    row's tribe - each family owns exactly one tribe, which makes this a
    lookup, not a guess. A tribeless stats archetype maps only when it names
    menagerie itself; anything else gets None and the window draws the flat
    list it always drew.
    """
    roles = comp_roles()
    entry = roles.get(archetype)
    if entry is not None:
        return entry
    if tribe is None:
        return roles.get("menagerie") if "menagerie" in archetype.lower() else None
    owners = [e for e in roles.values() if e["tribes"] == [tribe]]
    return owners[0] if len(owners) == 1 else None


def comp_role_hits(minion: dict) -> tuple[list, list]:
    """(core families, add-on families) for ONE pool minion.

    comp_role_split answers the same question for a whole comp row; this
    answers it for a single card, which is what a per-card rating needs. The
    rule is the one classify_board already uses, and nothing new is authored:
    a card can only be core to a family whose tribe it carries (an Amalgam,
    race ALL, carries them all), and it is core when its OWN keywords or text
    match that family's core role in data/comp_roles.json. A family with no
    roles entry is skipped rather than guessed at, and a card that misses the
    core role but matches the add-on role is reported as support - the two are
    never merged, because "the engine" and "what you layer on it" are worth
    different amounts.
    """
    roles = comp_roles()
    core, addon = [], []
    races = minion.get("races") or []
    for _order, archetype, tribe, _mechs, _pattern in COMP_FAMILIES:
        entry = roles.get(archetype)
        if entry is None:
            continue
        if tribe is not None and tribe not in races and "ALL" not in races:
            continue
        if _role_hit(minion, entry["core"]):
            core.append(archetype)
        elif _role_hit(minion, entry.get("addons")):
            addon.append(archetype)
    return core, addon


def pool_by_name(refresh: bool = False) -> dict:
    """name -> pool minion, for the surfaces that speak names (the comps
    window's lists come from board data and curated scoring, both by name).
    Rebuilt only on refresh; the pool itself changes on patches."""
    global _POOL_BY_NAME
    if _POOL_BY_NAME is None or refresh:
        _POOL_BY_NAME = {m["name"]: m for m in bg_pool(refresh)}
    return _POOL_BY_NAME


def comp_difficulty(archetype: str, tribe: str | None) -> dict | None:
    """How hard a family is to assemble - COMPUTED from the live pool, never
    hand-graded, because a difficulty grade is editorial work and copying
    someone else's is theft. data/comp_roles.json _difficulty_inputs is the
    contract; the three measured inputs are:

      tier    average tavern tier of the pool minions that can serve as core -
              an engine that lives at tier 5 cannot be assembled early
      pieces  how many distinct pool minions can serve as core - an engine
              with one carrier in the pool (murloc poison, 2026-08 pool) is
              missed by almost every roll, one with sixteen is hit constantly
      locked  whether the core sits inside a single tribe - a locked engine
              competes for one tribe's slice of the shop, menagerie shops
              anywhere

    score = (2 if tier >= 4.5 else 1 if tier >= 3.75 else 0)   late engine
          + (1 if pieces <= 4 else 0)                          scarce engine
          + (1 if locked else 0)                               one-tribe shop
    word  = easy (0-1) / medium (2) / hard (3+)

    The bands are calibration, so the inputs ride along in the result and the
    window prints them next to the word: a player can disagree with the label
    and still see the facts. No core piece in this patch's pool -> None, and
    no difficulty is shown rather than a guessed one.
    """
    entry = comp_roles_for(archetype, tribe)
    if entry is None:
        return None
    fam = entry["archetype"]
    if fam in _DIFF_CACHE:
        return _DIFF_CACHE[fam]
    fam_tribe = entry["tribes"][0] if entry["tribes"] else None
    try:
        pool = bg_pool()
    except Exception:
        return None            # offline with no cache: no number, and no cache
                               # entry so a later fetch can still answer
    cores = [m for m in pool
             if (fam_tribe is None or fam_tribe in m["races"] or "ALL" in m["races"])
             and _role_hit(m, entry["core"])]
    if not cores:
        _DIFF_CACHE[fam] = None
        return None
    tier = sum(m["techLevel"] for m in cores) / len(cores)
    locked = fam_tribe is not None
    score = ((2 if tier >= 4.5 else 1 if tier >= 3.75 else 0)
             + (1 if len(cores) <= 4 else 0) + (1 if locked else 0))
    out = {"word": "easy" if score <= 1 else "medium" if score == 2 else "hard",
           "tier": tier, "pieces": len(cores), "locked": locked}
    _DIFF_CACHE[fam] = out
    return out


def comp_role_split(comp: dict) -> dict | None:
    """One comp row's minions split into the CORE to look for and the ADD-ONS
    that finish it, plus the computed difficulty.

    CORE is what a card's own text or identity keyword proves against the
    family's core role; everything else the comp actually runs is by
    definition an add-on (the file's contract: core = the engine, add-ons =
    what you layer on once the engine works). An add-on that also matches the
    family's addon role is flagged, so the window can mark proven support
    apart from cards that merely show up. Order inside each half is the row's
    own order - real-board frequency on the stats path, family score on the
    curated path - because that ordering carries information the split must
    not destroy.

    None when no roles entry covers this comp, or when nothing in the list
    matched as core: a split with an empty core is a missed match, not
    information, so the window draws the flat list it always drew.
    """
    entry = comp_roles_for(comp.get("archetype") or "", comp.get("tribe"))
    if entry is None:
        return None
    try:
        pool = pool_by_name()
    except Exception:
        return None                  # offline with no cache yet
    core, addons = [], []
    for name in comp.get("key_wide") or comp.get("key") or []:
        m = pool.get(name)
        if m is not None and _role_hit(m, entry["core"]):
            core.append(name)
        else:
            # a name the pool no longer carries cannot PROVE core, so it is
            # support; the flag says whether the addon role vouches for it
            addons.append((name, bool(m and _role_hit(m, entry["addons"]))))
    if not core:
        return None
    return {"core": core, "addons": addons,
            "difficulty": comp_difficulty(comp.get("archetype") or "",
                                          comp.get("tribe"))}


# -------------------------------------------------------- board -> archetype
#
# What a finished board WAS, so games can be counted per comp. The families and
# the core roles are the ones already defined above (COMP_FAMILIES, and the core
# role each family carries in data/comp_roles.json); nothing new is authored
# here, because a second list of archetypes would drift from the one the panels
# draw and the two would disagree on screen.
#
# The rule, in one line: a board belongs to the tribe it is mostly made of, and
# only if the family's own engine is standing on it.
#
# Both halves are needed. Tribe share alone calls every pile of Beasts "beast
# summons"; the core role alone fires on any board holding one card with the
# right words. A board that satisfies neither is "none" - a genuine pile, and
# forcing it into a bucket is exactly the kind of invented number this project
# does not print.

# How much of a board must share one tribe before the board IS that tribe's
# comp. Half, measured: see the numbers in classify_board's docstring.
COMP_TRIBE_SHARE = 0.5
# Menagerie is the comp with no tribe, so it cannot be recognised by share -
# it is recognised by BREADTH: this many different tribes standing together.
COMP_MENAGERIE_TRIBES = 5
# A board too small to have had an identity. Below this a single minion decides
# the tribe share, which is a coin toss, not a comp.
COMP_MIN_BOARD = 4


def golden_aliases(refresh: bool = False) -> dict:
    """golden cardId -> the plain cardId it upgrades.

    A golden minion is a different card in the log - either the plain id with a
    _G suffix or an old-scheme id of its own (TB_BaconUps_nnn) - and a comp is
    the same comp whether its pieces are golden. The card database states the
    link (battlegroundsNormalDbfId), so it is read, not guessed. Cached a day
    like every other card fact; offline with no cache this is {} and golden
    pieces simply go unrecognised rather than being mapped by a hunch."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / "goldens.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        cards = _fetch(CARDS_URL)
    except Exception:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    by_dbf = {c["dbfId"]: c["id"] for c in cards if c.get("dbfId") and c.get("id")}
    out = {c["id"]: by_dbf[c["battlegroundsNormalDbfId"]] for c in cards
           if c.get("id") and c.get("battlegroundsNormalDbfId") in by_dbf}
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


_POOL_BY_ID = None


def pool_by_id(refresh: bool = False) -> dict:
    """cardId -> the pool minion it is, golden ids folded onto the plain card."""
    global _POOL_BY_ID
    if _POOL_BY_ID is None or refresh:
        pool = {m["id"]: m for m in bg_pool(refresh)}
        for gid, base in golden_aliases(refresh).items():
            if base in pool:
                pool.setdefault(gid, pool[base])
        _POOL_BY_ID = pool
    return _POOL_BY_ID


def _board_minions(board, refresh: bool = False) -> list:
    """The pool minions behind a list of board cardIds. Ids the pool does not
    carry (a summoned token, a card from another mode) are dropped rather than
    counted as tribeless - they were never a comp decision."""
    pool = pool_by_id(refresh)
    return [m for m in (pool.get(c) for c in board or []) if m]


def classify_board(board, refresh: bool = False) -> dict | None:
    """Which archetype a finished board was built as, or None for a pile.

    `board` is a list of cardIds (golden ids welcome). Returns
    {archetype, tribe, share, core, minions} or None.

    Measured over the 44 real games whose logs survive (2026-08-12) - see the
    numbers the aggregator prints, and tests/test_compclass.py, which holds
    this rule to hand-checked boards.

    Why "none" has to be a real answer: a Battlegrounds board is often just the
    six strongest minions the shop offered, and the whole point of a measured
    comp table is to say which archetypes place well. Sweeping the piles into
    the nearest bucket would move their placements into that bucket's average
    and quietly make every comp look like every other comp.
    """
    minions = _board_minions(board, refresh)
    n = len(minions)
    if n < COMP_MIN_BOARD:
        return None
    hits = {t: sum(1 for m in minions
                   if t in m["races"] or "ALL" in m["races"]) for t in TRIBES}
    tribe = max(hits, key=lambda t: hits[t])
    share = hits[tribe] / n
    if share >= COMP_TRIBE_SHARE:
        fam = next((f for f in COMP_FAMILIES if f[2] == tribe), None)
        if fam is not None:
            entry = comp_roles().get(fam[1])
            core = sum(1 for m in minions
                       if (tribe in m["races"] or "ALL" in m["races"])
                       and _role_hit(m, entry["core"] if entry else None))
            if core:
                return {"archetype": fam[1], "tribe": tribe,
                        "share": round(share, 3), "core": core, "minions": n}
    spread = sum(1 for t, c in hits.items() if c)
    if spread >= COMP_MENAGERIE_TRIBES and share < COMP_TRIBE_SHARE:
        return {"archetype": "menagerie", "tribe": None,
                "share": round(share, 3), "core": spread, "minions": n}
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

    It also carries the LEADERBOARD (``players``): the other seven seats with
    their hero, health, armour and tavern tier - and, while their fight is the
    one on screen, the minions the game is actually holding for them. Power.log
    never states any of that during recruit.

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
        # One dict per leaderboard seat, newest reading:
        #   {place, card, health, armor, tier, you, board:[{card, atk, health}]}
        # An empty board means "the game is not holding it", never "empty board".
        self.players = []
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
            # Added by a later msync build; an older helper simply omits it.
            self.players = d.get("players") or []
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


class TribeProver:
    """What the log PROVES about a lobby's tribes, one line at a time.

    A `tag=CARDRACE` line says what a CARD is, not what the LOBBY holds, and
    counting every one of them is wrong in two measured ways: a card generated
    into a hand (a Get, a discover, a Dark Gift reward) and a token summoned
    mid fight (Skeleton, Beetle, Golem) both carry a tribe the lobby never
    dealt. Measured over 60 real games, that made six of them claim 9 tribes.

    So a race counts only when it is stated for a BUYABLE pool minion standing
    in PLAY, and, once the log has named Bartender Bob, only under his
    controller, which is the shop itself.

    This is the one implementation: collect.lobby_tribes mines finished games
    with it and the overlay's LobbyTracker follows a live game with it, so the
    number on screen and the number that reaches the shared pool cannot drift
    apart. The live case has one unavoidable difference, stated rather than
    hidden: Bob is not known until his first shop is written, so anything
    proven in those first few lines is accepted on the looser board rule.

    It never claims a tribe is OUT. An unseen tribe is unconfirmed, and only
    the memory reader can be exact.
    """

    _HEAD = re.compile(
        r"(?:FULL_ENTITY - Creating ID|SHOW_ENTITY - Updating Entity)=\d+ CardID=(\S+)")
    _TAG = re.compile(r"\(\) - \s*tag=(\w+) value=(\S+)")
    _BOB = re.compile(r"cardId=TB_BaconShopBob player=(\d+)")
    # The one-line form: a minion states its race in a TAG_CHANGE that carries
    # its zone and card id inline. It has no controller, so it can only ever be
    # board-grade evidence, which is why it is read only while Bob is unknown.
    _BRACKET = re.compile(
        r"\[entityName=.+? id=\d+ zone=(\S+) zonePos=\d+ cardId=(\S*)")

    def __init__(self, bob=None, pool=None):
        self.tribes = set()
        self.bob = bob
        self._pool = pool
        self._card = self._zone = self._race = self._ctrl = None

    def _pool_ids(self):
        # Lazy, because a tracker is built before the card database is needed
        # and an unreachable database must not stop a game being followed.
        if self._pool is None:
            try:
                self._pool = {m["id"] for m in bg_pool()}
            except Exception:
                self._pool = set()
        return self._pool

    def _keep(self):
        """A block just ended: was it proof?"""
        if (self._race in TRIBES and self._zone == "PLAY"
                and (self.bob is None or self._ctrl == self.bob)):
            card = self._card or ""
            base = card[:-2] if card.endswith("_G") else card
            if base in self._pool_ids():
                self.tribes.add(self._race)

    def feed(self, line):
        """One log line. True when the proven set changed."""
        before = len(self.tribes)
        # Cheap substring guards first: this runs on every line of a live game.
        if self.bob is None and "TB_BaconShopBob" in line:
            m = self._BOB.search(line)
            if m:
                self.bob = m.group(1)
        if "CardID=" in line:
            m = self._HEAD.search(line)
            if m:
                self._keep()
                self._card, self._zone = m.group(1), None
                self._race = self._ctrl = None
                return len(self.tribes) != before
        if self._card is not None and "tag=" in line:
            t = self._TAG.search(line)
            if t:
                k, v = t.group(1), t.group(2)
                if k == "ZONE":
                    self._zone = v
                elif k == "CARDRACE":
                    self._race = v
                elif k == "CONTROLLER":
                    self._ctrl = v
                return len(self.tribes) != before
        if self.bob is None and "CARDRACE" in line and "[entityName=" in line:
            b = self._BRACKET.search(line)
            r = RACE_RE.search(line)
            if b and r and r.group(1) in TRIBES and b.group(1) == "PLAY":
                cid = b.group(2)
                cid = cid[:-2] if cid.endswith("_G") else cid
                if cid in self._pool_ids():
                    self.tribes.add(r.group(1))
        self._keep()
        self._card = self._zone = self._race = self._ctrl = None
        return len(self.tribes) != before

    def flush(self):
        """Close the block still open at the end of a finished game.

        A block is only judged when the NEXT line proves it has ended, so the
        last one in a slice would never be counted. Live this does nothing,
        because the log keeps coming.
        """
        self._keep()
        self._card = self._zone = self._race = self._ctrl = None
        return sorted(self.tribes)

    def reset(self):
        self.tribes = set()
        self.bob = None
        self._card = self._zone = self._race = self._ctrl = None


class LobbyTracker:
    """
    Which tribes this lobby is running, from the best source available.

    With the memory reader: the exact list, from hero select onward.
    Without it: inference from the log, through TribeProver - which counts a
    tribe only from a buyable minion in play (and, once Bob is named, only
    from his shop). Seeing one PROVES that tribe is in; an unseen tribe is
    merely unconfirmed, never provably excluded.
    """

    def __init__(self, memory: "MemoryTribes | None" = None):
        self._prover = TribeProver()
        self.memory = memory
        self._last = set()

    @property
    def seen(self) -> set:
        """What the log has PROVEN so far."""
        return self._prover.tribes

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
        self._prover.feed(line)
        current = self.tribes
        if current != self._last:
            self._last = set(current)
            return True
        return False

    def reset(self):
        self._prover.reset()
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
    ap.add_argument("--duo", action="store_true",
                    help="use Duos stats (heroes, trinkets, cards and comps all "
                         "come from Duos games only)")
    ap.add_argument("--replay", nargs="?", const="__newest__", default=None,
                    help="scan an existing log instead of following live")
    ap.add_argument("--refresh", action="store_true", help="force re-download of stats")
    ap.add_argument("--comps", action="store_true",
                    help="just print the comp rankings and exit")
    ap.add_argument("--no-lobby", action="store_true",
                    help="don't show the tribe/comp panel during games")
    args = ap.parse_args()

    print("bgtracker - loading ...")
    comps = comp_table(args.time, args.mmr, args.refresh, args.duo)
    # A feed publishes an MMR bucket only once it holds enough games, so a table
    # may have come back from the all-players pool instead. Label what we got.
    comp_mmr = bucket_in_use(source_kind("comps", args.duo), args.mmr)

    if args.comps:
        if not comps:
            sys.exit("  no comps available (offline and no card-pool cache yet)")
        curated = bool(comps and comps[0].get("baseline"))
        print(f"\n  COMPS  -  " + ("curated baseline (no stats configured)"
                                   if curated else f"top {comp_mmr}% MMR, {args.time}")
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
    trinkets = trinket_table(args.time, args.mmr, args.refresh, args.duo)
    hero_mmr = bucket_in_use(source_kind("heroes", args.duo), args.mmr)
    trinket_mmr = bucket_in_use(source_kind("trinkets", args.duo), args.mmr)
    # Recognition comes from the card database, not from any stats table, so
    # every offer is detected and named even with no stats configured at all.
    hero_ids = hero_universe(args.refresh)
    trinket_ids = trinket_universe(args.refresh)
    if heroes or trinkets:
        print(f"  stats: {len(heroes)} heroes (top {hero_mmr}%),"
              f" {len(trinkets)} trinkets (top {trinket_mmr}%)"
              f"  ({args.time}{', duos' if args.duo else ''})")
    elif args.duo:
        # Say which sources are missing, not just "some". Duos numbers never
        # fall back to the solo feed - they would be the wrong game's numbers.
        print("  no Duos numbers loaded (heroes_duo / trinkets_duo / cards_duo"
              " / comps_duo empty or unreachable) - offers will show without"
              " numbers. `collect.py --local-feed` builds them from your own"
              " Duos games.")
    else:
        # With no sources.json the community feed is the default, so landing
        # here means it was unreachable or empty - or a hand-written
        # sources.json chose to leave these tables out.
        print("  no numbers loaded (feed unreachable, or sources.json leaves"
              " these tables empty) - offers will show without numbers"
              " (README: 'Where the numbers come from')")

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
        hero_choice = kind == "hero choice"
        table = heroes if hero_choice else trinkets
        # Only heroes have per-tribe stats to re-score against.
        render(kind, opts, table, hero_mmr if hero_choice else trinket_mmr, args.time,
               lobby.tribes if hero_choice else None)

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
                    render_lobby(lobby, comps, comp_mmr)
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
                render_lobby(lobby, comps, comp_mmr)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
