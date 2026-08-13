#!/usr/bin/env python3
"""Board classification: the rule bgtracker.classify_board applies, held to
boards worked out by hand.

This is the test classify_board's own docstring points at. What it is for: the
classifier decides which archetype a finished warband counts as, and that
answer goes straight into the comp table's averages. Sweeping a pile of six
unrelated minions into the nearest bucket does not just mislabel one game, it
moves that game's placement into a real archetype's average and makes every
comp look like every other comp. So "none" has to stay a real answer, and the
cases below are as much about what is NOT classified as what is.

Every board is a list of real cardIds from the live pool, and every expected
answer is derived by hand from the rule rather than from running it:

  the tribe counts come from each minion's own `races`
  share   = the biggest tribe's count / the number of minions the pool knows
  a tribe archetype needs share >= COMP_TRIBE_SHARE (0.5) AND at least one
          minion of that tribe carrying the family's CORE role
  menagerie needs COMP_MENAGERIE_TRIBES (5) different tribes AND a share below
          the majority line, so a board is never both
  under COMP_MIN_BOARD (4) known minions there is no answer at all

Usage:
    python tests/test_compclass.py

Needs the cached card pool (.cache/bgpool.json, written by any prior run) or a
network connection; with neither it SKIPs (exit 0) like the other tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg          # noqa: E402

# The minions the boards are built from. Each line states what the pool says
# about that card, because that is what the arithmetic below rests on - and if
# a patch changes a card's tribe or text, the check in main() names which one
# went stale rather than leaving a case failing for an invented reason.
#
# Beasts that CARRY the "beast summons" core (their own text says Summon):
RAPTOR = "BG25_806"        # Sly Raptor         BEAST, deathrattle summon
ROVER = "BG31_801"         # Forest Rover       BEAST, deathrattle summon
VERMIN = "BG31_803"        # Buzzing Vermin     BEAST, deathrattle summon
# Beasts that do NOT carry it - bodies for the tribe, not the payoff:
LIONFISH = "BG36_201"      # Lurking Lionfish   BEAST
SHARK = "BG36_206"         # Snarky Shark       BEAST
LOBSTER = "BG36_202"       # Tasty Lobster      BEAST
BIRD = "BG26_805"          # Humming Bird       BEAST
SCARAB = "BG27_084"        # Sprightly Scarab   BEAST
GRYPHON = "BG36_204"       # Headhunter Gryphon BEAST
# One single-tribe minion each, for the mixed boards:
BREAM = "BG26_137"         # Bream Counter      MURLOC
TARECGOSA = "BG21_015"     # Tarecgosa          DRAGON
SANDERS = "BG25_034"       # Captain Sanders    PIRATE
URZUL = "BG21_004"         # Insatiable Ur'zul  DEMON
GEOMANCER = "BG20_100"     # Razorfen Geomancer QUILBOAR

BEAST_CORE = (RAPTOR, ROVER, VERMIN)
BEAST_PLAIN = (LIONFISH, SHARK, LOBSTER, BIRD, SCARAB, GRYPHON)
SINGLE_TRIBE = (BREAM, TARECGOSA, SANDERS, URZUL, GEOMANCER)

CASES = [
    (
        "six Beasts, three of them summoners",
        [RAPTOR, ROVER, VERMIN, LIONFISH, SHARK, LOBSTER],
        # 6 known minions, all BEAST -> share 6/6 = 1.0, over the 0.5 line.
        # Three carry the core role, so the family is claimed and `core` is
        # the count of them, not of the board.
        {"archetype": "beast summons", "tribe": "BEAST", "share": 1.0,
         "core": 3, "minions": 6},
    ),
    (
        "six Beasts and not one summoner",
        [BIRD, SCARAB, LIONFISH, LOBSTER, GRYPHON, SHARK],
        # The same 1.0 share, but core = 0. A board that is all of one tribe
        # and runs none of what that tribe's build is FOR is not that build,
        # and counting it as one would drag the archetype's average toward the
        # placements of people who just bought six of the same animal.
        None,
    ),
    (
        "exactly half Beasts, and the half are the summoners",
        [RAPTOR, ROVER, VERMIN, BREAM, TARECGOSA, SANDERS],
        # BEAST 3, MURLOC 1, DRAGON 1, PIRATE 1 -> share 3/6 = 0.5. The rule
        # is ">=", so a board exactly half a tribe IS that tribe's build; this
        # case exists to pin which side of the boundary that is.
        {"archetype": "beast summons", "tribe": "BEAST", "share": 0.5,
         "core": 3, "minions": 6},
    ),
    (
        "five tribes, one minion each",
        list(SINGLE_TRIBE),
        # Five different tribes, biggest share 1/5 = 0.2. Under the majority
        # line and at the menagerie floor, so it is a menagerie - where `core`
        # counts TRIBES represented, not minions carrying a role.
        {"archetype": "menagerie", "tribe": None, "share": 0.2,
         "core": 5, "minions": 5},
    ),
    (
        "four tribes, one minion each",
        list(SINGLE_TRIBE[:4]),
        # Share 1/4 = 0.25, so no majority, and four tribes is one short of a
        # menagerie. This is the pile the whole rule exists to leave alone.
        None,
    ),
    (
        "three Beasts",
        [RAPTOR, ROVER, VERMIN],
        # Under COMP_MIN_BOARD. A board this small is a board mid-game, and
        # every early board looks like whatever its first two buys were.
        None,
    ),
    (
        "three tokens and three Beasts",
        ["BGS_NOT_A_REAL_CARD", "BG_TOKEN_X", "TB_NOT_IN_POOL", RAPTOR, ROVER, VERMIN],
        # Ids the pool does not carry are DROPPED, not counted as tribeless -
        # they were never a comp decision. Three known minions is then under
        # the floor, which is the point: counting the tokens would have made
        # this a six-minion all-Beast board and handed it an archetype.
        None,
    ),
    (
        "the golden version of the same board",
        [RAPTOR + "_G", ROVER, VERMIN + "_G", LIONFISH, SHARK, LOBSTER],
        # A golden minion is the same minion. The pool is indexed under both
        # ids, so tripling a Beast must not quietly drop it off the board.
        {"archetype": "beast summons", "tribe": "BEAST", "share": 1.0,
         "core": 3, "minions": 6},
    ),
]


def main() -> int:
    try:
        pool = bg.bg_pool()
    except Exception as e:
        print(f"SKIP: no card pool available ({e})")
        return 0
    if not pool:
        print("SKIP: the card pool is empty")
        return 0

    print(f"floors in force: min board {bg.COMP_MIN_BOARD} minions, "
          f"tribe share {bg.COMP_TRIBE_SHARE}, "
          f"menagerie {bg.COMP_MENAGERIE_TRIBES} tribes")

    # The cards the cases are built on have to still be the cards the comments
    # say they are, or every expectation below is describing a different game.
    # This is checked first and reported apart, so a patch that re-tribes a
    # minion reads as "the fixture went stale", never as "the rule broke".
    byid = {m["id"]: m for m in pool}
    ok = True
    for cid in BEAST_CORE + BEAST_PLAIN:
        m = byid.get(cid)
        if m is None or "BEAST" not in m["races"]:
            print(f"    FAIL: {cid} is no longer a Beast in the pool ({m})")
            ok = False
    for cid, tribe in zip(SINGLE_TRIBE,
                          ("MURLOC", "DRAGON", "PIRATE", "DEMON", "QUILBOAR")):
        m = byid.get(cid)
        if m is None or m["races"] != [tribe]:
            print(f"    FAIL: {cid} is no longer {tribe} and nothing else ({m})")
            ok = False
    core_role = bg.comp_roles().get("beast summons", {}).get("core")
    carry = [c for c in BEAST_CORE if c in byid and bg._role_hit(byid[c], core_role)]
    wrong = [c for c in BEAST_PLAIN if c in byid and bg._role_hit(byid[c], core_role)]
    print(f"  fixture check: {len(carry)} of 3 summoners still carry the core "
          f"role, {len(wrong)} of 6 plain Beasts wrongly carry it")
    if len(carry) != 3 or wrong:
        print("    FAIL: the pool no longer splits these cards the way the "
              "cases assume - the expectations are stale, not wrong")
        ok = False

    for label, board, want in CASES:
        got = bg.classify_board(board)
        agree = got == want
        print(f"  {'ok  ' if agree else 'FAIL'}  {label}")
        print(f"          expected {want}")
        if not agree:
            print(f"          got      {got}")
            ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
