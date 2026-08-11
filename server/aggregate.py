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
  - trinkets: averagePlacement + sample, from games that took the trinket. Pick-rate
              likewise needs the offered set.
  - cards:    played-vs-not placement delta, from games that upload their final board.
  - comps:    EMPTY for now - archetype labelling needs a classifier we don't have
              yet (see server/README.md "What's not computed"). The file is still
              written so the client degrades to "no comp data", never errors.

Nothing here invents a number. A hero with no placements, a trinket nobody was
recorded taking, a card never seen on a board: absent, not zero-filled.

Env: BGTRACKER_DB, BGTRACKER_OUT (dir), BGTRACKER_PATCH_DATE (YYYY-MM-DD; the
     cut-off for the "last-patch" window - defaults to a rolling 14 days).
"""

import gzip
import json
import os
import sqlite3
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
        for k in ("tribes", "offered_heroes", "offered_trinkets", "picked_trinkets", "final_board"):
            g[k] = json.loads(g[k]) if g[k] else []
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
    # Archetype labelling (Beasts / Murlocs / Menagerie ...) needs a classifier we
    # haven't built. Emit an empty-but-valid file so the client shows "no comp
    # data" instead of erroring. See server/README.md "What's not computed".
    return {"compStats": []}


def write(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, separators=(",", ":")).encode()
    (OUT / f"{name}.json").write_bytes(raw)
    with gzip.open(OUT / f"{name}.json.gz", "wb") as f:      # bandwidth-friendly twin
        f.write(raw)


def main():
    games = load_games()
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"aggregate: {len(games)} games in {DB_PATH}")
    for period, spec in PERIODS.items():
        window = in_window(games, cutoff_for(spec))
        write(f"heroes-{period}", {**hero_stats(window), "generatedAt": stamp, "games": len(window)})
        write(f"trinkets-{period}", {**trinket_stats(window), "generatedAt": stamp, "games": len(window)})
        write(f"cards-{period}", {**card_stats(window), "generatedAt": stamp, "games": len(window)})
        write(f"comps-{period}", {**comp_stats(window), "generatedAt": stamp, "games": len(window)})
        print(f"  {period:11} {len(window):6} games -> heroes/trinkets/cards/comps")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
