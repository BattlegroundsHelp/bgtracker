#!/usr/bin/env python3
"""
Aggregator - the read side of the independent dataset.

Turns the ingested games (data/games.db) into the exact JSON the client already
knows how to read (see bgtracker.py: hero_table / trinket_table / card_table).
Point sources.json at these files and the tool runs on our OWN numbers - no third
party, nothing to ask permission for, because it's players' own game results.

Run it on a timer (systemd / cron / the Docker sidecar). It reads the DB, writes
server/out/*.json[.gz], and exits. The reverse proxy serves those files statically,
so a thousand clients fetching stats never touch this process or the DB.

    python aggregate.py                    # write every period into server/out/

What it computes honestly, from the data we actually have:
  - heroes:   averagePosition + placement spread + sample, from games with a hero
              and a placement. Pick-rate only when clients upload the offered set.
  - heropowers: the same numbers for the hero POWER, from the games that were
              offered a choice of one. Nobody publishes these anywhere - the pick
              panel could name the options and never rate them.
  - trinkets: averagePlacement + sample, from games that took the trinket. Pick-rate
              likewise needs the offered set.
  - cards:    played-vs-not placement delta, from games that upload their final board.
  - comps:    the archetype each finished board was BUILT as, averaged. The
              labelling uses the client's own families and core roles
              (bgtracker.COMP_FAMILIES + data/comp_roles.json), imported rather
              than restated, so the server and the panels can never disagree
              about what "beast summons" means. A board matching nothing is
              counted as "none", never swept into the nearest bucket. Rows are
              published only once an archetype clears COMP_MIN_GAMES; below that
              the file carries the classification counts and no rows, and the
              client falls back to its curated list - because a thin measured row
              REPLACES that list on screen, which would show a comp ranking built
              on four games.

Each of those is written once per MMR bucket the pool can actually support (see
MMR_BUCKETS below): heroes-{mmr}-{period}.json. Bucket 100 is ALSO written under
the old un-bucketed name (heroes-{period}.json), so a sources.json written before
buckets existed keeps working untouched.

...and once per GAME MODE. Solo and Duos are two datasets, not one: a duos lobby
is four teams and finishes 1st-4th, a solo lobby finishes 1st-8th, and the hero
and card pools differ. Duos gets its own family of files, heroes-duo-{mmr}-
{period}.json (and the un-bucketed heroes-duo-{period}.json), built from a pool
that shares no game with the solo one - which is what the client's `--duo` and
the `*_duo` keys in sources.json read. Every file states its own "mode". A game
whose mode is unknown - recorded before the client could tell them apart - is in
neither pool; the count is published in buckets.json as "unclassified".

Nothing here invents a number. A hero with no placements, a trinket nobody was
recorded taking, a card never seen on a board: absent, not zero-filled. A bucket
with too few games: not written at all, so the client falls back to the whole
pool instead of reading noise off four games.

Env: BGTRACKER_DB, BGTRACKER_OUT (dir), BGTRACKER_PATCH_DATE (YYYY-MM-DD; the
     cut-off for the "last-patch" window - defaults to a rolling 14 days),
     BGTRACKER_MMR_MIN (games a bucket needs before it is published).
"""

import gzip
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.environ.get("BGTRACKER_DB", Path(__file__).parent.parent / "data" / "games.db"))
OUT = Path(os.environ.get("BGTRACKER_OUT", Path(__file__).parent / "out"))
PATCH_DATE = os.environ.get("BGTRACKER_PATCH_DATE") or None

# The client asks for these period names (bgtracker.py). Each maps to a date
# window; None means "everything". last-patch uses BGTRACKER_PATCH_DATE if set,
# else a rolling fortnight - a stand-in until we track real patch dates.
PERIODS = {"all-time": None, "past-seven": 7, "past-three": 3, "last-patch": "patch"}

# ------------------------------------------------------------- MMR buckets
# The client asks for one of five buckets (bgtracker.py --mmr 100|50|25|10|1),
# meaning "the top N% of players". We do NOT know the ladder's real rating
# distribution - nobody publishes it, and lifting someone else's cut-offs would
# be using their data. So a bucket is defined against the only distribution we
# can honestly measure: OUR OWN pool. Bucket N = the games whose rating is in
# the top N% of the ratings shared with this server, in that same time window.
# Every file states its own boundary (the "mmr" block: bucket, minRating, games,
# basis), so nobody has to guess what "top 10%" meant on the day it was built.
MMR_BUCKETS = [100, 50, 25, 10, 1]

# A bucket is published only once it holds this many games. Below it the split
# is noise, not granularity: four games at "top 1%" is a worse answer than the
# whole pool, and the client is built to fall back to bucket 100 rather than
# show nothing. Same number as the client's MIN_SAMPLE - the line this project
# already draws between "signal" and "no signal".
MMR_MIN_GAMES = int(os.environ.get("BGTRACKER_MMR_MIN", "30"))

# Games one archetype needs before its row is published at all. Every other
# table publishes thin rows and lets the client flag them, but a comp row cannot
# do that: the client's comp_table drops its CURATED family list the moment the
# feed carries a single measured row (bgtracker.comp_table), so publishing a
# 4-game archetype would replace a useful list with a ranking nobody should
# read. Same number as the client's MIN_SAMPLE.
COMP_MIN_GAMES = int(os.environ.get("BGTRACKER_COMP_MIN", "30"))

# The comps file carries the example boards the client builds "key minions" and
# their frequency from. Capped so one popular archetype cannot make the file
# enormous; the cap is on BOARDS, and the newest are kept.
COMP_MAX_BOARDS = 200

# ---------------------------------------------- the client's own definitions
# The archetypes, and what makes a minion core to one, are defined in the CLIENT
# (bgtracker.COMP_FAMILIES + data/comp_roles.json), because that is what the
# panels draw. They are imported, never restated: a second list here would drift
# from the first and the two would disagree on screen, which is worse than
# having no comp table at all.
#
# The import is optional on purpose. The deployed container may hold only this
# file, and the classifier also needs the live card pool (HearthstoneJSON) to
# know a minion's tribes and text. Either being missing means the comps file
# says so and carries no rows - it never falls back to a guess.
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    import bgtracker as bg
except Exception:                                  # pragma: no cover - deploy shape
    bg = None


def load_games():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM games").fetchall()
    conn.close()
    out = []
    for r in rows:
        g = dict(r)
        # .get, not [k]: a store written by an older ingest has no column for a
        # newer field until that ingest starts and migrates it, and the
        # aggregator must not crash in the gap - a missing column is an empty
        # list, exactly like a row that never carried the field.
        for k in ("tribes", "offered_heroes", "offered_trinkets", "picked_trinkets",
                  "offered_hero_powers", "picked_hero_powers", "final_board"):
            g[k] = json.loads(g[k]) if g.get(k) else []
        out.append(g)
    return out


def cutoff_for(spec):
    if spec is None:
        return None
    if spec == "patch":
        if PATCH_DATE:
            return PATCH_DATE
        spec = 14
    return (date.today() - timedelta(days=spec)).isoformat()


def in_window(games, cutoff):
    if cutoff is None:
        return games
    return [g for g in games if g.get("date") and g["date"] >= cutoff]


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def rating_cut(rated, top_pct):
    """The rating at the bottom edge of the top `top_pct`% of `rated` (a sorted
    ascending list of ratings), rounded DOWN to a round hundred.

    Nearest-rank, so even a tiny pool yields a cut - whether the bucket is
    actually published is decided by the sample floor, not by this. Rounding
    down keeps the published boundary off one individual player's exact rating
    and holds it steady while the pool wobbles; it can pull in a few games below
    the strict percentile, which is the honest direction to err (more sample,
    never less)."""
    if not rated:
        return None
    idx = min(int(len(rated) * (1 - top_pct / 100.0)), len(rated) - 1)
    return (rated[idx] // 100) * 100


def mmr_cuts(games):
    """bucket -> minimum rating. Bucket 100 is everyone (None = no floor, and it
    keeps the games that never reported a rating at all). The other four exist
    only once somebody has actually reported a rating in this window."""
    rated = sorted(g["mmr"] for g in games if isinstance(g.get("mmr"), int))
    cuts = {100: None}
    for b in MMR_BUCKETS:
        if b == 100:
            continue
        cut = rating_cut(rated, b)
        if cut is not None:
            cuts[b] = cut
    return cuts


def in_bucket(games, cut):
    """The games inside one bucket. A game with no rating counts only in bucket
    100 - we cannot place it, and guessing would be inventing a number."""
    if cut is None:
        return games
    return [g for g in games if isinstance(g.get("mmr"), int) and g["mmr"] >= cut]


def hero_stats(games):
    places = defaultdict(list)          # hero -> [place, ...]  (avg / dist / n)
    offered = defaultdict(int)          # hero -> times offered (pick-rate denominator)
    picked = defaultdict(int)           # hero -> times picked, among offer-bearing games
    for g in games:
        if g["hero"] and g["place"]:
            places[g["hero"]].append(g["place"])
        if g["offered_heroes"]:                        # only games that carry the offer
            for h in g["offered_heroes"]:
                offered[h] += 1
            if g["hero"] and g["hero"] in g["offered_heroes"]:
                picked[g["hero"]] += 1

    out = []
    heroes = set(places) | set(offered)
    for h in heroes:
        pl = places[h]
        dist = []
        if pl:
            for rank in range(1, 9):
                c = pl.count(rank)
                if c:
                    dist.append({"rank": rank, "percentage": round(100.0 * c / len(pl), 2)})
        row = {
            "heroCardId": h,
            "averagePosition": round(mean(pl), 3) if pl else None,
            "dataPoints": len(pl),
            "placementDistribution": dist,
            "totalOffered": offered[h],
            "totalPicked": picked[h],
            "tribeStats": [],           # per-tribe impact needs far more data; omitted, not faked
        }
        out.append(row)
    out.sort(key=lambda r: (r["averagePosition"] is None, r["averagePosition"] or 9))
    return {"heroStats": out}


def hero_power_stats(games):
    """The hero-power table, built exactly like hero_stats.

    Only some heroes hand you a choice of power; the rest have a fixed one and
    contribute nothing here, which is why this table is much smaller than the
    hero table and why that is not a bug.

    One game can pick SEVERAL powers - a power that hands out another power
    re-offers every few turns (measured: one game picked five). So:
      - a placement counts ONCE per distinct power per game, or a single long
        game would stack five copies of its own result onto one row;
      - offered / picked count every showing, because pick rate is asking
        "how often is this taken when it is on screen", and it was on screen
        each time.
    """
    places = defaultdict(list)          # power -> [place, ...]
    offered = defaultdict(int)
    picked = defaultdict(int)
    for g in games:
        if g["place"]:
            for p in set(g["picked_hero_powers"]):
                places[p].append(g["place"])
        if g["offered_hero_powers"]:
            for p in g["offered_hero_powers"]:
                offered[p] += 1
            for p in g["picked_hero_powers"]:
                if p in g["offered_hero_powers"]:
                    picked[p] += 1

    out = []
    for p in set(places) | set(offered):
        pl = places[p]
        dist = []
        if pl:
            for rank in range(1, 9):
                c = pl.count(rank)
                if c:
                    dist.append({"rank": rank, "percentage": round(100.0 * c / len(pl), 2)})
        out.append({
            "heroPowerCardId": p,
            "averagePosition": round(mean(pl), 3) if pl else None,
            "dataPoints": len(pl),
            "placementDistribution": dist,     # the client's top-4 comes from this
            "totalOffered": offered[p],
            "totalPicked": picked[p],
        })
    out.sort(key=lambda r: (r["averagePosition"] is None, r["averagePosition"] or 9))
    return {"heroPowerStats": out}


def trinket_stats(games):
    places = defaultdict(list)
    offered = defaultdict(int)
    picked = defaultdict(int)
    for g in games:
        for t in g["picked_trinkets"]:
            if g["place"]:
                places[t].append(g["place"])
        if g["offered_trinkets"]:
            for t in g["offered_trinkets"]:
                offered[t] += 1
            for t in g["picked_trinkets"]:
                if t in g["offered_trinkets"]:
                    picked[t] += 1

    out = []
    for t in set(places) | set(offered):
        pl = places[t]
        avg = round(mean(pl), 3) if pl else None
        out.append({
            "trinketCardId": t,
            "averagePlacement": avg,
            "averagePlacementAtMmr": [],        # no MMR split yet
            "pickRate": (picked[t] / offered[t]) if offered[t] else None,
            "dataPoints": len(pl),
        })
    out.sort(key=lambda r: (r["averagePlacement"] is None, r["averagePlacement"] or 9))
    return {"trinketStats": out}


def card_stats(games):
    # Only games that uploaded a final board can tell us "played vs not". Restrict
    # the whole comparison to that pool so 'Other' isn't polluted by games that
    # simply never reported a board.
    boarded = [g for g in games if g["final_board"] and g["place"]]
    universe = {c for g in boarded for c in g["final_board"]}
    out = []
    for cid in universe:
        played = [g["place"] for g in boarded if cid in g["final_board"]]
        other = [g["place"] for g in boarded if cid not in g["final_board"]]
        ap, apo = mean(played), mean(other)
        out.append({
            "cardId": cid,
            "averagePlacement": round(ap, 3) if ap is not None else None,
            "averagePlacementOther": round(apo, 3) if apo is not None else None,
            "totalPlayed": len(played),
        })
    out.sort(key=lambda r: r["averagePlacement"] or 9)
    return {"cardStats": out}


def comp_stats(games):
    """Average placement per archetype, over the boards players finished on.

    Every game with a final board and a placement is classified by the client's
    own rule (bgtracker.classify_board: the board belongs to the tribe it is
    mostly made of, and only if that family's engine piece is standing on it).
    A board that matches nothing is counted under "none" and its placement goes
    nowhere - forcing piles into the nearest bucket would drag every archetype's
    average toward the middle and make the whole table say nothing.

    The counts are always reported, rows only above COMP_MIN_GAMES. That gap is
    the honest state of a young pool: "we classified 39 boards and no archetype
    has 30 games yet" is a fact; a table of four-game averages is not.
    """
    boarded = [g for g in games if g["final_board"] and g["place"]]
    info = {"boards": len(boarded), "classified": 0, "unclassified": 0,
            "minGames": COMP_MIN_GAMES, "classifier": None}
    if bg is None:
        info["classifier"] = "unavailable: the client module is not importable here"
        return {"compStats": [], "compClassification": info}
    try:
        bg.bg_pool()                    # the live card pool the rule reads
    except Exception as e:
        info["classifier"] = f"unavailable: no card pool ({type(e).__name__})"
        return {"compStats": [], "compClassification": info}
    if not bg.comp_roles():
        # Without the roles file no board can prove a core piece, so every
        # board would come back "none" - which reads as "nobody plays comps"
        # instead of "this deploy is missing data/comp_roles.json".
        info["classifier"] = "unavailable: data/comp_roles.json is missing"
        return {"compStats": [], "compClassification": info}
    info["classifier"] = "bgtracker.classify_board"

    places = defaultdict(list)
    tribes = {}
    boards = defaultdict(list)
    for g in boarded:
        try:
            hit = bg.classify_board(g["final_board"])
        except Exception:
            hit = None
        if not hit:
            info["unclassified"] += 1
            continue
        info["classified"] += 1
        a = hit["archetype"]
        places[a].append(g["place"])
        tribes[a] = hit["tribe"]
        boards[a].append(g["final_board"])

    info["byArchetype"] = {a: len(v) for a, v in sorted(places.items(),
                                                        key=lambda kv: -len(kv[1]))}
    out = []
    for a, pl in places.items():
        if len(pl) < COMP_MIN_GAMES:
            continue
        out.append({
            "archetype": a,
            "tribe": tribes[a],
            "averagePlacement": round(mean(pl), 3),
            "averagePlacementAtMmr": [],       # no MMR split until the pool asks for one
            "dataPoints": len(pl),
            "frequency": round(len(pl) / len(boarded), 4),
            # The client reads its "key minions" and their % of boards out of
            # this shape (bgtracker.comp_minion_counts), so the example boards
            # are real finished boards from this very pool - nobody else's.
            "heroStats": [{"finalBoards": [
                {"finalComp": {"board": [{"cardID": c} for c in b]}}
                for b in boards[a][-COMP_MAX_BOARDS:]]}],
        })
    out.sort(key=lambda r: r["averagePlacement"])
    return {"compStats": out, "compClassification": info}


def write(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, separators=(",", ":")).encode()
    (OUT / f"{name}.json").write_bytes(raw)
    with gzip.open(OUT / f"{name}.json.gz", "wb") as f:      # bandwidth-friendly twin
        f.write(raw)


# ------------------------------------------------------------- solo vs duos
# Solo and Duos are counted as two separate datasets, never one. A duos lobby is
# four TEAMS, so it finishes 1st-4th while a solo lobby finishes 1st-8th: pool
# them and every solo average is dragged toward a number no solo player can
# reach, while every duos average is inflated by eight-place games. The modes
# also run different hero pools and different cards, so even the pick rates
# would be answering a question nobody asked.
#
# Three states, and the third one matters: a record from a client that could not
# yet tell the modes apart says nothing, and "nothing" is not "solo". Those games
# are counted in NEITHER feed and reported as unclassified, in keeping with the
# rest of this file - an absent number is absent, never zero and never a guess.
# They heal themselves: the client re-mines its logs and the ingest endpoint
# fills the mode in (see BACKFILL_DUO in ingest.py).
MODES = (("", False), ("-duo", True))       # (file-name infix, what `duo` must be)


def is_duo(g):
    """True / False / None(unknown). SQLite hands back 1/0, JSON true/false, and
    a database written before the column existed hands back nothing at all."""
    v = g.get("duo")
    return None if v is None else bool(v)


def split_modes(games):
    """(solo, duo, unknown) - the three pools, no game in two of them."""
    solo = [g for g in games if is_duo(g) is False]
    duo = [g for g in games if is_duo(g) is True]
    unknown = [g for g in games if is_duo(g) is None]
    return solo, duo, unknown


def emit_period(games, period, stamp, verbose=True, infix="", mode="solo"):
    """Write every MMR bucket this window can support, for one period and one
    game mode. `infix` goes into the file name ("" solo, "-duo" duos), so the
    two modes land in files that can never be mistaken for each other, and every
    file states its own `mode`.

    Returns the manifest rows for the buckets that were actually published.
    Shared with collect.py --local-feed, so a player's personal feed is bucketed
    by exactly the same rules as the community one."""
    cuts = mmr_cuts(games)
    published = []
    for b in MMR_BUCKETS:
        if b not in cuts:
            continue
        sub = in_bucket(games, cuts[b])
        if b != 100 and len(sub) < MMR_MIN_GAMES:
            continue                      # too thin to mean anything: no file at all
        published.append((b, cuts[b], sub))

    # Trinkets carry their per-bucket placements INSIDE the all-players file as
    # well (averagePlacementAtMmr). The client already prefers that field when it
    # matches the requested bucket, so even a sources.json whose URL has no {mmr}
    # placeholder gets the MMR split for trinkets, with no config change.
    tstats = {b: trinket_stats(sub) for b, _, sub in published}
    at_mmr = defaultdict(list)
    for b, _, _ in published:
        if b == 100:
            continue
        for row in tstats[b]["trinketStats"]:
            if row["averagePlacement"] is not None:
                at_mmr[row["trinketCardId"]].append(
                    {"mmr": b, "placement": row["averagePlacement"],
                     "dataPoints": row["dataPoints"]})

    for b, cut, sub in published:
        meta = {
            "generatedAt": stamp,
            "games": len(sub),
            # Which game this counted. Written into every file so a feed can
            # never be read as the other mode's numbers by accident - the
            # placements alone would not give it away (1st-4th vs 1st-8th).
            "mode": mode,
            # Say what the bucket IS, in the file, so a reader never has to
            # assume it matches anyone else's idea of "top 10%".
            "mmr": {
                "bucket": b,
                "minRating": cut,
                "games": len(sub),
                "basis": "every shared game, rated or not" if cut is None else
                         f"rating >= {cut}: the top {b}% of the ratings shared "
                         f"with this server in this window",
            },
        }
        trink = tstats[b]
        if b == 100:
            for row in trink["trinketStats"]:
                rows = at_mmr.get(row["trinketCardId"])
                if rows:
                    row["averagePlacementAtMmr"] = rows
        comps = comp_stats(sub)
        for base, obj in (("heroes", {**hero_stats(sub), **meta}),
                          ("heropowers", {**hero_power_stats(sub), **meta}),
                          ("trinkets", {**trink, **meta}),
                          ("cards", {**card_stats(sub), **meta}),
                          ("comps", {**comps, **meta})):
            write(f"{base}{infix}-{b}-{period}", obj)
            if b == 100:
                write(f"{base}{infix}-{period}", obj)   # pre-bucket names still work
        if verbose:
            floor = "any rating" if cut is None else f">= {cut}"
            print(f"  {period:11} {mode:4} top {b:>3}% ({floor:>11}) {len(sub):6} games")
            # Say what the comps file actually contains. An empty compStats can
            # mean three different things - no boards, no classifier, or nothing
            # over the floor yet - and only the counts tell them apart.
            info = comps["compClassification"]
            if info["boards"]:
                print(f"  {period:11} {mode:4} comps: {info['classified']} boards "
                      f"classified, {info['unclassified']} matched nothing, "
                      f"{len(comps['compStats'])} archetypes over "
                      f"{COMP_MIN_GAMES} games"
                      + (f" [{info['classifier']}]" if not info.get("byArchetype") else ""))

    if verbose:
        thin = [b for b in cuts if b not in [p[0] for p in published]]
        if thin:
            print(f"  {period:11} {mode:4} not published, under {MMR_MIN_GAMES} games: "
                  + ", ".join(f"top {b}%" for b in sorted(thin, reverse=True)))
    return [{"bucket": b, "minRating": cut, "games": len(sub)} for b, cut, sub in published]


def emit(games, stamp, verbose=True):
    """Every period x every mode x every publishable bucket.

    Solo and duos are aggregated from disjoint pools and written to disjoint
    file names, so neither can leak into the other. Games whose mode is unknown
    are in neither pool; the manifest says how many, rather than hiding them."""
    manifest = {"generatedAt": stamp, "minGamesPerBucket": MMR_MIN_GAMES,
                "basis": "top N% of the ratings shared with this server, per period",
                "modes": ["solo", "duo"],
                "periods": {}}
    for period, spec in PERIODS.items():
        window = in_window(games, cutoff_for(spec))
        solo, duo, unknown = split_modes(window)
        manifest["periods"][period] = {
            "solo": emit_period(solo, period, stamp, verbose, infix="", mode="solo"),
            "duo": emit_period(duo, period, stamp, verbose, infix="-duo", mode="duo"),
            # Counted, not quietly dropped: these are games recorded before the
            # client could tell the modes apart. Re-mining and re-uploading
            # clears them (ingest.py fills a NULL mode, never overwrites one).
            "unclassified": len(unknown),
        }
    return manifest


def main():
    games = load_games()
    solo, duo, unknown = split_modes(games)
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"aggregate: {len(games)} games in {DB_PATH} "
          f"({len(solo)} solo, {len(duo)} duos"
          + (f", {len(unknown)} unclassified - in neither feed" if unknown else "") + ")")
    write("buckets", emit(games, stamp))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
