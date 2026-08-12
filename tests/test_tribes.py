#!/usr/bin/env python3
"""Lobby tribes: only what a bought minion proves.

    python tests/test_tribes.py

The bug this pins down, measured on a real game before the fix: 9 tribes
counted in one lobby, three of them from cards that were never buyable there.
A CARDRACE tag says what a CARD is, not what the LOBBY holds, and three kinds
of card carry one without being evidence:

  * a card generated straight into a hand (a Get, a discover, a Dark Gift
    reward) comes from outside the lobby's pool;
  * a token summoned mid fight (Skeleton, Beetle, Golem) carries its own
    tribe whether or not that tribe is in the lobby;
  * a minion sitting in a deck or set aside has not been offered to anyone.

Only a real pool minion standing in PLAY proves its tribe. The log can never
prove a tribe is OUT, and nothing here claims it can.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bgtracker as bg  # noqa: E402
import collect  # noqa: E402

PRE = "D 12:00:00.0000000 GameState.DebugPrintPower() - "


def block(card, zone, race, indent=8):
    """One FULL_ENTITY block the way Hearthstone writes it."""
    pad = " " * indent
    return [
        f"{PRE}    FULL_ENTITY - Creating ID=1 CardID={card}",
        f"{PRE}{pad}tag=ZONE value={zone}",
        f"{PRE}{pad}tag=CARDRACE value={race}",
        f"{PRE}{pad}tag=CARDTYPE value=MINION",
    ]


def main() -> int:
    if not collect.pool_ids():
        print("no card pool available (offline?) - cannot run")
        return 1

    # Three real buyable minions of three different tribes, plus a token id
    # that is deliberately not buyable.
    by_race = {}
    for m in bg.bg_pool():
        for r in (m.get("races") or []):
            if r in bg.TRIBES:
                by_race.setdefault(r, m["id"])
    picks = list(by_race.items())[:3]
    if len(picks) < 3:
        print("card pool did not yield three tribes - cannot run")
        return 1
    (shop_race, shop_card), (board_race, board_card), (hand_race, hand_card) = picks
    token = "BG28_603t"                      # a Beetle token, not buyable
    if token in collect.pool_ids():
        print(f"FAIL: {token} is in the pool, pick another token for this test")
        return 1

    ok = True

    game = []
    game += block(shop_card, "PLAY", shop_race)      # in the shop: counts
    game += block(board_card, "PLAY", board_race)    # on a board: counts
    game += block(hand_card, "HAND", hand_race)      # generated to hand: no
    game += block(token, "PLAY", "UNDEAD")           # summoned token: no
    got = collect.lobby_tribes(game)
    want = sorted({shop_race, board_race})
    print(f"\nshop {shop_race} + board {board_race} count, "
          f"hand {hand_race} and a token are ignored")
    print(f"  got  {got}\n  want {want}")
    if got != want:
        print("  FAIL: wrong tribe set")
        ok = False

    # The one-line form (a TAG_CHANGE carrying the entity bracket) must obey
    # the same rule: this is how a minion states its race after it moves.
    inline = [
        f"{PRE}    TAG_CHANGE Entity=[entityName=X id=9 zone=PLAY zonePos=1 "
        f"cardId={shop_card} player=4] tag=CARDRACE value={shop_race}",
        f"{PRE}    TAG_CHANGE Entity=[entityName=Y id=8 zone=HAND zonePos=2 "
        f"cardId={hand_card} player=4] tag=CARDRACE value={hand_race}",
    ]
    got2 = collect.lobby_tribes(inline)
    print(f"\ninline form: got {got2}, want ['{shop_race}']")
    if got2 != [shop_race]:
        print("  FAIL: the one-line form ignored zone or pool")
        ok = False

    # A golden minion is the same card and must still count.
    got3 = collect.lobby_tribes(block(shop_card + "_G", "PLAY", shop_race))
    print(f"\ngolden counts as its base card: got {got3}")
    if got3 != [shop_race]:
        print("  FAIL: golden ids are not resolving to the base card")
        ok = False

    # Nothing provable means an empty list, never a guess.
    got4 = collect.lobby_tribes(block(token, "PLAY", "BEAST"))
    print(f"\nnothing provable -> {got4}")
    if got4 != []:
        print("  FAIL: invented a tribe from a token alone")
        ok = False

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
