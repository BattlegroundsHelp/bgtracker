"""The bootstrap star: it must help, and it must never lie about itself.

The pool is young, so tools/make_minion_priors.py freezes a starting opinion
of each minion and the overlay blends it with the live table by sample size.
Two things have to hold for that to stay honest, and they are what this file
pins:

  1. the blend SLIDES - no games means the frozen opinion, a well-measured
     card means its own games, and the crossover sits at MIN_SAMPLE
  2. a star still leaning on the frozen opinion is reported as such, so the
     windows can draw it hollow. A measured star and a guessed star must
     never be the same mark on screen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg  # noqa: E402


def blend(measured, prior, n):
    """The rule both the shop and the browser implement, written once here so
    the test pins the arithmetic rather than one copy of it."""
    w = n / (n + bg.MIN_SAMPLE)
    return max(1, min(5, round(w * measured + (1 - w) * prior))), w < 0.5


def test_blend_slides():
    print("\n=== the blend slides from guess to measurement")
    # A card the frozen file calls 5 and the live table calls 1.
    at_zero, guessed0 = blend(1, 5, 0)
    assert (at_zero, guessed0) == (5, True), (at_zero, guessed0)
    print(f"  n=0    -> {at_zero} stars, guess={guessed0}   (the frozen opinion)")

    mid, guessed_mid = blend(1, 5, bg.MIN_SAMPLE)
    assert guessed_mid is False, "MIN_SAMPLE games must count as measured"
    print(f"  n={bg.MIN_SAMPLE}   -> {mid} stars, guess={guessed_mid}   (half and half)")

    lots, guessed_lots = blend(1, 5, 500)
    assert lots == 1 and guessed_lots is False, (lots, guessed_lots)
    print(f"  n=500  -> {lots} stars, guess={guessed_lots}   (its own games win)")

    # Monotone: more evidence never moves the answer back toward the guess.
    seq = [blend(1, 5, n)[0] for n in (0, 1, 5, 15, 30, 60, 200, 1000)]
    assert seq == sorted(seq, reverse=True), seq
    print(f"  monotone: {seq}")


def test_prior_file_is_sane():
    print("\n=== the shipped file")
    p = ROOT / "data" / "minion_ratings.json"
    assert p.is_file(), "data/minion_ratings.json is missing"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc.get("dated"), "the file must say when it was frozen"
    ratings = doc["ratings"]
    assert ratings, "no ratings in the file"
    for name, rec in ratings.items():
        assert 1 <= rec["stars"] <= 5, (name, rec)
        # The generator refuses to hold an opinion about a card with almost
        # no games; a file that broke that rule would be ranking noise.
        assert rec["n"] >= 3, f"{name} was rated on {rec['n']} games"
    print(f"  {len(ratings)} minions, dated {doc['dated']}, fewest games "
          f"behind any rating: {min(r['n'] for r in ratings.values())}")


def test_loader_rejects_junk():
    print("\n=== the loader only passes what it can trust")
    loaded = bg.minion_priors()
    assert isinstance(loaded, dict) and loaded, "the shipped file should load"
    for name, rec in loaded.items():
        assert isinstance(name, str)
        assert isinstance(rec["stars"], int) and 1 <= rec["stars"] <= 5
        assert isinstance(rec["n"], int) and rec["n"] >= 0
    print(f"  {len(loaded)} priors loaded, every one inside its range")


if __name__ == "__main__":
    test_blend_slides()
    test_prior_file_is_sane()
    test_loader_rejects_junk()
    print("\nPASS")
