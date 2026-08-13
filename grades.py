"""CARD GRADES - a star read off the CARD, for the minions nothing has measured yet.

Why this exists
---------------
The tavern stars and the minion browser's stars are measured: they rank the
buy-it-vs-skip-it DIFFERENTIAL out of a card table (bgtracker.card_table), and
with no row for a card they show nothing at all. That is the right behaviour
and it is the whole reason this tool has any standing - it prints its own
numbers or it prints none. But it means a brand new install, on a pool of a
few dozen games, shows an unrated shop for a while: the tool is least useful
at the exact moment somebody is deciding whether to keep it.

A grade fills that gap WITHOUT inventing a statistic. Every input here is the
card itself, out of the same HearthstoneJSON data the rest of the tool already
fetches: the stat line, the keywords, the card text, the tribe, and whether
the card is a core piece of one of the comp families (data/comp_roles.json).
Nothing here is a placement, a win rate, or a sample of anything. It is an
OPINION derived from a card, it is labelled as one on every surface that draws
it (a hollow star instead of a filled one), and the moment the pool can
measure a card the measurement replaces it.

Two hard rules, both enforced below and in tests/test_grades.py:

  1. MEASURED WINS. A card with a real differential is never graded. The grade
     is only ever consulted where the card table has nothing.
  2. WITHIN THE TIER. A five star tier one is a good tier one, not a tier six.
     Bands are cut inside each tavern tier, the same top-heavy shape the
     measured stars use, so the two paths feel identical.

The scoring rule
----------------
Everything is expressed in units of A TIER AVERAGE BODY, so one weight means
the same thing at every tier. The tier averages are not hardcoded: they are
computed from the live pool every time the grade table is built, so a patch
that inflates stats moves the yardstick with it.

    score = (attack + health) / mean_total_stats(tier) - 1     # the body
          + keyword weights                                     # what it does
          + comp-family core / add-on weight                    # what it is for
          + tribeless / all-tribes weight                       # where it fits

MEASURED tier means, this pool (274 minions, HearthstoneJSON, 2026-08-13):

    tier 1   4.04  (n=23, median 4)       tier 5   9.85  (n=53, median 10)
    tier 2   5.49  (n=37, median 6)       tier 6  12.46  (n=37, median 13)
    tier 3   6.76  (n=50, median 7)       tier 7  18.31  (n=13, median 18)
    tier 4   8.48  (n=61, median 9)

so a 4/5 at tier 3 sits 33% over its tier's typical body, and the same 4/5 at
tier 6 sits 28% under. Tier 7 is the thin one (13 minions, and one 40+ stat
body among them), which is exactly why its band is cut from its own
distribution rather than from a curve.

THE WEIGHTS ARE A JUDGEMENT, NOT A MEASUREMENT
----------------------------------------------
Nothing below was fitted to data. They are one player's ordering of what a
keyword is worth relative to a tier average body, written down so a
contributor can argue with a number in a pull request instead of guessing what
the code believes. The reasoning, per weight:

  DIVINE_SHIELD 0.30  Eats one hit whatever its size, so it is worth more the
                      bigger the enemy board gets, and it is the keyword whole
                      comps are built to protect and re-apply. The most
                      stat-independent thing on a card.
  VENOMOUS      0.30  The same argument from the other side: it answers the
                      biggest minion on the board off any body at all. That is
                      why the game only ever prints it on small ones - the
                      keyword IS the card.
  POISONOUS     0.30  The older wording of the same effect. Not in the current
                      pool (VENOMOUS replaced it); kept so a patch that brings
                      it back is not silently graded as vanilla.
  WINDFURY      0.20  Doubles attack output, but only pays once someone has
                      buffed it. On a vanilla body it is close to "+attack",
                      which the body term already counts, so it lands under
                      the two keywords above.
  REBORN        0.20  A second body at one health: strong with deathrattles,
                      shields and buffs, close to filler alone.
  START_OF_COMBAT 0.20  Acts before anyone swings. The highest-leverage timing
                      in the game, and only 11 of 274 minions have it.
  END_OF_TURN_TRIGGER 0.20  Scaling that fires every turn compounds; this is
                      the elemental and quilboar engine keyword (19 of 274).
  MAGNETIC      0.15  Puts a stat line exactly where it is needed and keeps
                      the board slot free. Tribe locked, so it is worth
                      nothing in a lobby without mechs - but that is the
                      lobby filter's job, not the grade's.
  DEATHRATTLE   0.15  The widest scaling keyword in the pool (48 of 274), but
                      the AVERAGE deathrattle is small, and a grade has to be
                      about the average one.
  AVENGE        0.12  Repeating payoff, on someone else's timing.
  AURA          0.12  Board wide and permanent while it lives, usually small.
  BACON_SPELLCRAFT_ID 0.10  A free spell every turn: real, and slow.
  BACON_RALLY   0.10  Common (26 of 274) and mostly a tempo effect.
  TAUNT         0.08  Positioning, not power. It converts into value only
                      alongside something else (shield, poison, big health),
                      and it can actively cost you the fight.
  DISCOVER      0.08  Choice is worth something; it is not a stat.
  CHOOSE_ONE    0.08  The same argument.
  BATTLECRY     0.05  42 of 274 carry it, and much of what it does has already
                      happened before the first attack (see the DO-NOT-SCRIPT
                      section of docs/CARD_EFFECTS.md). Almost a rounding
                      term, kept only so a battlecry body is not graded as a
                      vanilla one.
  STEALTH       0.05  Survives a round of targeting. Rare and situational.

  A mechanic not in this table scores ZERO rather than a default, because a
  guessed default for an unknown keyword is exactly the invented number this
  project exists to avoid. TRIGGER_VISUAL and InvisibleDeathrattle are
  deliberately absent: they are internal markers, and TRIGGER_VISUAL sits on
  95 of the 274 pool minions while meaning nothing to a player.

  Text signals, for value the keyword list cannot see:
  "permanently" / "this game" 0.15  Scaling that survives the fight is the
                      strongest shape a card can have in this game mode.
  "summon"      0.10  Bodies out of nowhere, the mid-game's real currency.

  Comp roles (data/comp_roles.json, matched by bgtracker.comp_role_hits):
  core, first family  0.35  The archetypes are built AROUND these cards, which
                      is worth more than their stat line says - that is the
                      entire premise of a comp.
  each further family 0.10, capped at two  A card carrying three engines is
                      genuinely flexible, but the returns are flat: you can
                      only build one comp.
  add-on only         0.12  Proven support for a family, not its engine.

  Fit:
  no tribe      0.05  A tribeless minion is in EVERY lobby and can never be
                      the dead card the lobby's tribe list makes of others.
                      Small on purpose: it collects no tribal buffs either.
  race ALL      0.10  An Amalgam counts as every tribe at once, which is the
                      same argument with more upside.

Known limits, stated rather than papered over: a card that GRANTS a keyword to
others ("give your minions Divine Shield") carries no such mechanic itself and
is only partly caught by the text signals; positioning, tempo and hero
interactions are not modelled at all; and the comp-role match is only as good
as data/comp_roles.json. None of this is measured, and no surface says it is.

Cost
----
The pool only changes on a patch, so the whole table is built once and cached
in .cache/cardgrades.json beside the other card-derived tables (bgpool,
cardtiers, goldens), keyed by GRADE_VERSION so changing a weight above
rebuilds it instead of serving yesterday's opinion. In a running overlay a
grade is one dict lookup: nothing here runs per frame, and nothing here
fetches on a draw path.
"""

from __future__ import annotations

import json
import re
import time

import bgtracker as bg

# Bump when a weight, a band or the row shape changes: the cache is keyed on
# it, so an old file is ignored instead of quietly serving the old opinion.
GRADE_VERSION = 1

CACHE_FILE = "cardgrades.json"
CACHE_TTL = 86400          # a day, like every other card-derived table here

KEYWORDS = {
    "DIVINE_SHIELD": 0.30,
    "VENOMOUS": 0.30,
    "POISONOUS": 0.30,
    "WINDFURY": 0.20,
    "REBORN": 0.20,
    "START_OF_COMBAT": 0.20,
    "END_OF_TURN_TRIGGER": 0.20,
    "MAGNETIC": 0.15,
    "DEATHRATTLE": 0.15,
    "AVENGE": 0.12,
    "AURA": 0.12,
    "BACON_SPELLCRAFT_ID": 0.10,
    "BACON_RALLY": 0.10,
    "TAUNT": 0.08,
    "DISCOVER": 0.08,
    "CHOOSE_ONE": 0.08,
    "BATTLECRY": 0.05,
    "STEALTH": 0.05,
}

# The mechanics whose raw key reads badly on screen. Everything else is
# title-cased, so a keyword a future patch adds still prints as words.
KEYWORD_LABELS = {
    "BACON_SPELLCRAFT_ID": "Spellcraft",
    "BACON_RALLY": "Rally",
    "DIVINE_SHIELD": "Divine Shield",
    "START_OF_COMBAT": "Start of Combat",
    "END_OF_TURN_TRIGGER": "End of Turn",
    "CHOOSE_ONE": "Choose One",
}

# (label, weight, pattern), read against the card's plain text.
TEXT_SIGNALS = (
    ("permanent scaling", 0.15, re.compile(r"[Pp]ermanently|this game")),
    ("summons", 0.10, re.compile(r"[Ss]ummon")),
)

CORE_FIRST = 0.35
CORE_EXTRA = 0.10
CORE_EXTRA_MAX = 2         # a card can only build one comp at a time
ADDON = 0.12
TRIBELESS = 0.05
ALL_TRIBES = 0.10

# The measured stars' own shape (ui/browser.py _make_bands, overlay.py _cut):
# top 8% is five stars, top quarter is four, and so on. Kept identical on
# purpose - a player should not have to learn two scales.
BANDS = (0.92, 0.75, 0.50, 0.25)
# Below this many minions a tier's own distribution is not a distribution, and
# a band cut from it would be a rank invented out of a handful of cards. Every
# tavern tier clears it in the current pool (13 to 61); the guard is for a
# patch, or a caller, that leaves one thin.
MIN_TIER_POOL = 10

_TABLE = None              # module memo: built once, read per frame


def tier_means(pool) -> dict:
    """tavern tier -> mean (attack + health) across the live pool.

    This is the yardstick every body is measured against, and it is measured
    rather than assumed so a patch that inflates a tier moves it.
    """
    totals, counts = {}, {}
    for m in pool:
        t = m.get("techLevel") or 0
        totals[t] = totals.get(t, 0) + (m.get("attack") or 0) + (m.get("health") or 0)
        counts[t] = counts.get(t, 0) + 1
    return {t: totals[t] / counts[t] for t in totals if counts[t]}


def keyword_label(key: str) -> str:
    return KEYWORD_LABELS.get(key) or key.replace("_", " ").title()


def _plain(text: str) -> str:
    """Card text as the player reads it: markup and the [x] no-wrap marker
    gone, whitespace squeezed, so a pattern matches words."""
    return re.sub(r"\s+", " ", re.sub(r"</?[^>]+>|\[x\]", "", text or ""))


def parts(minion: dict, means: dict, roles=None) -> list:
    """Every term of one minion's score as (label, value), in scoring order.

    One function, so the number and the explanation can never drift apart: the
    score is the sum of these, and the browser shows the same labels.
    """
    tier = minion.get("techLevel") or 0
    body = (minion.get("attack") or 0) + (minion.get("health") or 0)
    mean = means.get(tier) or 0
    out = []
    if mean:
        out.append((f"{minion.get('attack', 0)}/{minion.get('health', 0)} body, "
                    f"tier {tier} averages {mean:.1f}", body / mean - 1.0))
    for k in minion.get("mechanics") or ():
        if k in KEYWORDS:
            out.append((keyword_label(k), KEYWORDS[k]))
    text = _plain(minion.get("text") or "")
    for label, weight, rx in TEXT_SIGNALS:
        if rx.search(text):
            out.append((label, weight))
    core, addon = roles if roles is not None else bg.comp_role_hits(minion)
    if core:
        out.append((f"core of {core[0]}", CORE_FIRST))
        extra = min(len(core) - 1, CORE_EXTRA_MAX)
        if extra:
            out.append((f"and {extra} more famil{'y' if extra == 1 else 'ies'}",
                        CORE_EXTRA * extra))
    elif addon:
        out.append((f"supports {addon[0]}", ADDON))
    races = minion.get("races") or []
    if "ALL" in races:
        out.append(("every tribe", ALL_TRIBES))
    elif not races:
        out.append(("no tribe, so never dead in a lobby", TRIBELESS))
    return out


def score(minion: dict, means: dict, roles=None) -> float:
    return sum(v for _label, v in parts(minion, means, roles))


def bands(scores) -> list | None:
    """Cut points for one tier, best band first, or None for a tier too thin
    to rank. A score EQUAL to a cut takes the higher band, so a run of
    identical vanilla bodies shares a star instead of being split by sort
    order - which does mean a band can hold more than its nominal share."""
    if len(scores) < MIN_TIER_POOL:
        return None
    vals = sorted(scores)
    return [vals[min(len(vals) - 1, int(len(vals) * k))] for k in BANDS]


def stars_for(value: float, cuts) -> int:
    return (5 if value >= cuts[0] else 4 if value >= cuts[1] else
            3 if value >= cuts[2] else 2 if value >= cuts[3] else 1)


def build(pool=None) -> dict:
    """The whole grade table: {version, means, stars, why, n}.

    Pure enough to test: hand it a pool and it grades that pool.
    """
    pool = bg.bg_pool() if pool is None else pool
    means = tier_means(pool)
    scored = []
    for m in pool:
        try:
            roles = bg.comp_role_hits(m)
        except Exception:
            roles = ([], [])          # no roles file: grade the card alone
        p = parts(m, means, roles)
        scored.append((m, sum(v for _label, v in p), p))
    by_tier = {}
    for m, s, _p in scored:
        by_tier.setdefault(m.get("techLevel") or 0, []).append(s)
    cuts = {t: bands(v) for t, v in by_tier.items()}
    stars, why = {}, {}
    for m, s, p in scored:
        cut = cuts.get(m.get("techLevel") or 0)
        if not cut:
            continue                  # a tier too thin to rank gets no grade
        stars[m["id"]] = stars_for(s, cut)
        why[m["id"]] = [label for label, _v in p]
    # A golden is the same card: the shop and the board both speak the golden
    # id (BG20_100_G, or an old-scheme TB_BaconUps_nnn), and looking it up
    # under the plain id is what pool_by_id already does for the comps.
    try:
        for gid, base in bg.golden_aliases().items():
            if base in stars:
                stars.setdefault(gid, stars[base])
                why.setdefault(gid, why[base])
    except Exception:
        pass                          # offline with no cache: plain ids only
    return {"version": GRADE_VERSION, "means": means, "stars": stars,
            "why": why, "n": len(pool)}


def table(refresh: bool = False) -> dict:
    """The cached grade table. Built once per patch, then a dict lookup.

    Never call this from a draw path with a cold cache: it reads the card
    pool, which can be a network fetch. The overlay warms it on its reader
    thread and the browser warms it on its loader thread, the same way both
    already warm the card table.
    """
    global _TABLE
    if _TABLE is not None and not refresh:
        return _TABLE
    bg.CACHE_DIR.mkdir(exist_ok=True)
    path = bg.CACHE_DIR / CACHE_FILE
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("version") == GRADE_VERSION:
                _TABLE = doc
                return doc
        except Exception:
            pass                      # unreadable cache: rebuild it
    doc = build()
    try:
        path.write_text(json.dumps(doc), encoding="utf-8")
    except Exception:
        pass                          # a read-only install still grades
    _TABLE = doc
    return doc


def grade(card_id: str) -> int | None:
    """1..5 for a card, or None when there is no warm table.

    Draw paths call this. It never builds and never fetches: with nothing warm
    yet the surfaces simply show no star, which is what they showed before
    this feature existed.
    """
    if _TABLE is None or not card_id:
        return None
    return _TABLE["stars"].get(card_id)


def why(card_id: str) -> list:
    """The labelled terms behind a grade, in scoring order, for the surface
    that has room to show them."""
    return list(_TABLE["why"].get(card_id, ())) if _TABLE else []


def ready() -> bool:
    return _TABLE is not None


def reset():
    """Drop the memo. Tests use it; nothing in the app does."""
    global _TABLE
    _TABLE = None
