#!/usr/bin/env python3
"""
Offline regression: replay tests/fixture.log through the OfferDetector and
demand EXACTLY the offer counts that match reality.

fixture.log is one real day of play boiled down to the lines that matter:
19 games. 19 games means 19 hero drafts; two trinket offers per game, minus
one run that ended before the greater trinket, plus extras from heroes that
grant one = 36. Those two numbers are the whole test:

- trinkets near 137 -> the four-option rule broke and opponent trinket
  reveals (staged in SETASIDE every time you fight someone) are leaking in.
- heroes != 19      -> the timestamp grouping or the HAND filter broke.

Runs fully offline: the detector only needs recognition SETS of cardIds, so
the frozen HearthstoneJSON-derived id lists in tests/fixtures/ stand in for
bg_ids(). No network, ever - this is what CI runs.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bgtracker as bg

EXPECTED_HEROES = 19
EXPECTED_TRINKETS = 36


def main() -> int:
    here = Path(__file__).parent
    heroes = {i: {} for i in json.loads((here / "fixtures" / "hero_ids.json").read_text())}
    trinkets = {i: {} for i in json.loads((here / "fixtures" / "trinket_ids.json").read_text())}
    det = bg.OfferDetector(heroes, trinkets, universe=heroes)

    counts = {"hero choice": 0, "trinket choice": 0}
    with open(here / "fixture.log", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ev = det.feed(line)
            if ev:
                counts[ev[0]] += 1
    ev = det.flush()
    if ev:
        counts[ev[0]] += 1

    ok = (counts["hero choice"] == EXPECTED_HEROES
          and counts["trinket choice"] == EXPECTED_TRINKETS)
    print(f"hero offers:    {counts['hero choice']:3}  (expected {EXPECTED_HEROES})")
    print(f"trinket offers: {counts['trinket choice']:3}  (expected {EXPECTED_TRINKETS})")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
