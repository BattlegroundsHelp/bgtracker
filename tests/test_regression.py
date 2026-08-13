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
# Every hero in the frozen id fixture now has a tip. It is a floor, not an
# equality: a patch that adds heroes must not fail CI before anyone has had the
# chance to write their lines, but LOSING a tip is a regression and fails here.
EXPECTED_TIPS = 121

TRIBES = {"BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL",
          "MURLOC", "NAGA", "PIRATE", "QUILBOAR", "UNDEAD"}


def check_tips(hero_ids: set) -> bool:
    """data/hero_tips.json obeys data/hero_tips.schema.json.

    Hero tips arrive by pull request, often from someone who has never run the
    overlay, so the file is checked rather than trusted - this is the only
    automated review a contributed line gets. Every rule asserted here is one
    the schema states, and the hero ids come from the frozen offline fixture,
    so a tip for a hero that does not exist (a typo, a renamed card) fails CI
    instead of silently never appearing.

    An absent file is NOT a failure: the tips are optional data and the overlay
    simply draws nothing without them.
    """
    path = Path(__file__).resolve().parents[1] / "data" / "hero_tips.json"
    if not path.exists():
        print("hero tips:      absent (optional)")
        return True
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"hero tips:      UNREADABLE - {e}")
        return False
    errs = []
    if doc.get("version") != 1:
        errs.append(f"version must be 1, got {doc.get('version')!r}")
    tips = doc.get("tips")
    if not isinstance(tips, dict):
        print("hero tips:      'tips' must be an object")
        return False
    for cid, e in sorted(tips.items()):
        if cid not in hero_ids:
            errs.append(f"{cid}: not a Battlegrounds hero cardId")
            continue
        if not isinstance(e, dict):
            errs.append(f"{cid}: entry must be an object")
            continue
        extra = set(e) - {"name", "when", "bullets", "tribes"}
        if extra:
            errs.append(f"{cid}: unknown field(s) {sorted(extra)}")
        when = e.get("when")
        if not isinstance(when, str) or not 8 <= len(when) <= 80:
            errs.append(f"{cid}: 'when' must be a string of 8-80 characters")
        elif when.rstrip().endswith("."):
            errs.append(f"{cid}: 'when' should not end in a full stop")
        bullets = e.get("bullets")
        if not isinstance(bullets, list) or not 1 <= len(bullets) <= 3:
            errs.append(f"{cid}: 'bullets' must be a list of 1 to 3 items")
        else:
            for b in bullets:
                if not isinstance(b, str) or not 8 <= len(b) <= 100:
                    errs.append(f"{cid}: every bullet is a string of 8-100 characters")
        if "tribes" in e:
            t = e["tribes"]
            if not isinstance(t, list) or not set(t) <= TRIBES or len(set(t)) != len(t):
                errs.append(f"{cid}: 'tribes' must be unique names from {sorted(TRIBES)}")
        if "name" in e and (not isinstance(e["name"], str) or len(e["name"]) > 60):
            errs.append(f"{cid}: 'name' must be a string of at most 60 characters")
    if len(tips) < EXPECTED_TIPS:
        errs.append(f"coverage fell to {len(tips)} tips, {EXPECTED_TIPS} expected")
    print(f"hero tips:      {len(tips):3} of {len(hero_ids)} heroes, "
          f"{len(errs)} problem(s)")
    for m in errs[:20]:
        print(f"  {m}")
    return not errs


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
    ok = check_tips(set(heroes)) and ok
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
