#!/usr/bin/env python3
"""Freeze a starting opinion of every minion from the pool we already have.

The stars in the shop need about thirty games on a card before the live table
will say anything, and the community pool is young - measured 2026-08-15, the
best-covered minion had eleven games and most had one. So the shop showed no
stars at all, which is honest and useless.

This writes the bootstrap: one provisional rating per minion, computed ONCE
from the pool as it stands and shipped as text. The overlay then blends it
with the live measurement by sample size, so every game played quietly moves
a card off this file's opinion and onto its own record. Nothing here is
permanent and nothing here is anybody else's data - it is our own feed, read
once and written down.

The maths, and why it is not just "average the games":

  A card with one game has a wild average, and ranking on it would put a
  minion somebody happened to win with above one they happened to lose with.
  Each card's differential is therefore pulled toward the average of its OWN
  tavern tier, by how little evidence stands behind it:

      shrunk = (n * delta + K * tier_mean) / (n + K)

  With one game a card sits essentially at its tier's average - the file says
  "no opinion" rather than a loud wrong one. With ten it has moved a real
  distance. K is bgtracker.MIN_SAMPLE, the same threshold the live stars use,
  so the two agree about what "enough" means.

  Stars are then cut per tier on the same top-heavy bands the live path uses
  (top 8% = five, top quarter = four), so a bootstrap star and a measured
  star mean the same thing on the same scale.

    python tools/make_minion_priors.py            # writes data/minion_ratings.json
    python tools/make_minion_priors.py --dry-run  # print, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg  # noqa: E402

OUT = ROOT / "data" / "minion_ratings.json"
CUTS = (0.08, 0.25, 0.50, 0.75)
# How many games a card needs before this file will hold ANY opinion of it.
# Not a sample size that proves anything - it is the floor under which the
# shrunk value cannot be told apart from the tier's average, so a rank would
# be noise wearing a star.
MIN_EVIDENCE = 3


def stars_from(delta: float, cut) -> int:
    """Lower delta is better: it is placement WITH the card minus without."""
    return (5 if delta <= cut[0] else 4 if delta <= cut[1] else
            3 if delta <= cut[2] else 2 if delta <= cut[3] else 1)


def build(mmr: str = "100", period: str = "all-time"):
    """all-time on purpose: the bootstrap wants every game the pool has ever
    seen, where the live stars want this patch only."""
    cards = bg.card_table(mmr, period)
    tiers = bg.card_tiers()
    names = bg.card_names()
    try:                                  # the browsable pool knows tiers the
        for m in bg.bg_pool():            # stats table has never heard of
            tiers.setdefault(m["id"], m["techLevel"])
            names.setdefault(m["id"], m["name"])
    except Exception:
        pass

    rows = [(cid, v) for cid, v in cards.items()
            if v.get("delta") is not None and v.get("n", 0) > 0
            and tiers.get(cid, 0) >= 1]

    by_tier = {}
    for cid, v in rows:
        by_tier.setdefault(tiers[cid], []).append((cid, v))

    K = bg.MIN_SAMPLE
    out, skipped = {}, 0
    for tier, items in sorted(by_tier.items()):
        # The tier's own centre of gravity, weighted by evidence, is what a
        # card with nothing behind it should be assumed to be. Every card in
        # the tier informs it, including the one-game ones.
        total_n = sum(v["n"] for _, v in items)
        tier_mean = (sum(v["delta"] * v["n"] for _, v in items) / total_n
                     if total_n else 0.0)

        # An opinion needs a few real games behind it. Below that the shrunk
        # value cannot be told apart from the tier's average, and ranking
        # those against each other produces a confident-looking order made of
        # noise. Those cards are simply left out and the shop shows them with
        # no star, exactly as it does today.
        rated = [(cid, v) for cid, v in items if v["n"] >= MIN_EVIDENCE]
        skipped += len(items) - len(rated)
        if len(rated) < 6:
            # Too few cards left in this tier to cut bands that mean
            # anything - one card would be "the best" by default.
            skipped += len(rated)
            continue

        shrunk = [(cid, (v["n"] * v["delta"] + K * tier_mean) / (v["n"] + K),
                   v["n"]) for cid, v in rated]
        # The bands are cut on THIS population, the rated one. Cutting them
        # on every card in the tier put the whole rated set in the tails: a
        # tier is mostly one-game cards sitting on the mean, so anything with
        # real evidence looked extreme by comparison.
        vals = sorted(s for _, s, _ in shrunk)
        cut = [vals[int(len(vals) * k)] for k in CUTS]
        for cid, s, n in shrunk:
            name = names.get(cid)
            if not name:
                continue
            out[name] = {"stars": stars_from(s, cut), "n": n, "tier": tier}
    return out, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mmr", default="100")
    ap.add_argument("--time", default="all-time")
    ap.add_argument("--dated", default="2026-08-15",
                    help="the date written into the file")
    args = ap.parse_args()

    ratings, skipped = build(args.mmr, args.time)
    if not ratings:
        print("no ratings could be built - is a stats source reachable?")
        return 1

    doc = {
        "_comment": (
            "A STARTING opinion of each minion, frozen from the community "
            "pool by tools/make_minion_priors.py. It is not a measurement: "
            "every card's differential was pulled toward its own tavern "
            "tier's average by how few games stood behind it, so a card with "
            "one game sits at its tier's average rather than wherever that "
            "one game happened to land. The overlay blends these with the "
            "live table by sample size (weight n/(n+30)), so a card the pool "
            "has really measured stops listening to this file. A star that "
            "still leans on this file is drawn hollow, never as a "
            "measurement. Regenerate after a patch, or edit by hand - your "
            "copy beside the exe wins over the bundled one."),
        "dated": args.dated,
        "method": "shrunk-to-tier-mean, K=%d, %s, top %s%%" % (
            bg.MIN_SAMPLE, args.time, args.mmr),
        "source": "the community pool only - no third-party stats",
        "ratings": dict(sorted(ratings.items())),
    }
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    spread = {}
    for r in ratings.values():
        spread[r["stars"]] = spread.get(r["stars"], 0) + 1
    print(f"{len(ratings)} minions rated  (skipped {skipped} in thin tiers)")
    print("stars:", dict(sorted(spread.items())))
    print("with 5+ games behind them:",
          sum(1 for r in ratings.values() if r["n"] >= 5))
    if args.dry_run:
        print(text[:600])
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
