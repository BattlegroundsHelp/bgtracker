#!/usr/bin/env python3
"""The tavern-buff counters against the lines the CURRENT game actually writes.

    python tests/test_shopbuff.py

Born from a live game (2026-08-13, elemental board): the game's own tooltip
said the standing buff was +59/+54 while the strip said "elem +3/+4". The
totals had moved off the legacy player tags onto hidden accumulator
enchantments - and the strip was faithfully mirroring a number whose meaning
had changed under it. Every line below is shaped exactly like the live log's
(same prefixes, same bracket spellings, values from the real game), so this
file is the contract for how those lines must land.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.counters import CounterState  # noqa: E402

P = "D 23:01:53.0000000 PowerTaskList.DebugPrintPower() - "
G = "D 23:01:53.0000000 GameState.DebugPrintGame() - "

ME = "TavernFan#1234"
ACCUM = ("[entityName=Random minion Tavern Minion Buff Player Ench [DNT] "
         "id=3003 zone=SETASIDE zonePos=0 cardId=BG34_854pe player=2]")
SHOPBUFF = ("[entityName=BG_ShopBuff_Elemental id=8616 zone=PLAY zonePos=0 "
            "cardId=BG_ShopBuff_Elemental player=2]")
STAMP = ("[entityName=Eastern Winds id=10899 zone=PLAY zonePos=1 "
         "cardId=BG34_854e player=2]")
MIRROR = ("[entityName=TagTransferPlayerEnchant [DNT] id=536 zone=PLAY "
          "zonePos=0 cardId=Bacon_TagTransferPlayerE player=2]")


def boot(state, name=ME, player="2"):
    """Identity, exactly as the log states it: the PlayerID dump plus the
    drag-buy token that names our player id."""
    state.feed(f"{G}PlayerID={player}, PlayerName={name}")
    state.feed(f"{P}FULL_ENTITY - Updating [entityName=Drag To Buy id=100 "
               f"zone=PLAY zonePos=0 cardId=TB_BaconShop_DragBuy "
               f"player={player}] CardID=TB_BaconShop_DragBuy")
    state.feed(f"{P}TAG_CHANGE Entity=GameEntity tag=TURN value=1 ")


def main() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + msg)
        ok = ok and cond

    # 1. The tribe-wide accumulator IS the elem chip; legacy is not doubled.
    s = CounterState()
    boot(s)
    s.feed(f"{P}    TAG_CHANGE Entity={ME} tag=BACON_ELEMENTAL_BUFFATKVALUE value=3 ")
    s.feed(f"{P}    TAG_CHANGE Entity={ME} tag=BACON_ELEMENTAL_BUFFHEALTHVALUE value=4 ")
    s.feed(f"{P}    TAG_CHANGE Entity={SHOPBUFF} tag=TAG_SCRIPT_DATA_NUM_1 value=133 ")
    s.feed(f"{P}    TAG_CHANGE Entity={SHOPBUFF} tag=TAG_SCRIPT_DATA_NUM_2 value=136 ")
    buffs = list(s.shop_buffs.values())
    check(len(buffs) == 1 and buffs[0]["atk"] == 133 and buffs[0]["hp"] == 136,
          f"ShopBuff_Elemental accumulator read: {buffs}")
    check(buffs and buffs[0]["label"] == "ELEMENTAL", "labelled by its tribe")
    check(s.elem_atk == 3 and s.elem_hp == 4,
          "legacy pair still tracked (drawn only as fallback)")

    # 2. The stamping accumulator, named by its visible stamp.
    s.feed(f"{P}    TAG_CHANGE Entity={ACCUM} tag=TAG_SCRIPT_DATA_NUM_1 value=59 ")
    s.feed(f"{P}    TAG_CHANGE Entity={ACCUM} tag=TAG_SCRIPT_DATA_NUM_2 value=54 ")
    rec = s.shop_buffs.get("3003")
    check(rec is not None and rec["atk"] == 59 and rec["hp"] == 54,
          f"stamping accumulator read: {rec}")
    check(rec is not None and rec["label"] is None,
          "unnamed until its stamp is sighted")
    s.feed(f"{P}    TAG_CHANGE Entity={STAMP} tag=ZONE_POSITION value=1 ")
    check(rec["label"] == "Eastern Winds",
          f"named by the enchantment the player sees: {rec['label']!r}")

    # 3. Fight-time writes on our player id are the opponent's mirror: frozen.
    s.feed(f"{P}TAG_CHANGE Entity=GameEntity tag=TURN value=2 ")
    s.feed(f"{P}    TAG_CHANGE Entity={ACCUM} tag=TAG_SCRIPT_DATA_NUM_1 value=999 ")
    check(rec["atk"] == 59, "accumulator frozen during the fight")
    s.feed(f"{P}TAG_CHANGE Entity=GameEntity tag=TURN value=3 ")
    s.feed(f"{P}    TAG_CHANGE Entity={ACCUM} tag=TAG_SCRIPT_DATA_NUM_1 value=65 ")
    check(rec["atk"] == 65, "and live again in the next shop")

    # 4. Random script data on an unknown enchantment is NOT a buff.
    s.feed(f"{P}    TAG_CHANGE Entity=[entityName=Some Aura id=77 zone=PLAY "
           f"zonePos=0 cardId=BG99_Whatever_e player=2] "
           f"tag=TAG_SCRIPT_DATA_NUM_1 value=40 ")
    check("77" not in s.shop_buffs, "unknown script data ignored")

    # 5. A battletag with a space: every player tag must still attribute.
    s2 = CounterState()
    boot(s2, name="Bartender Bob")
    s2.feed(f"{P}    TAG_CHANGE Entity=Bartender Bob tag=RESOURCES value=7 ")
    check(s2.gold_base == 7, "spaced battletag reads its player tags")

    # 6. The TagTransfer mirror is a second road to the same fields.
    s3 = CounterState()
    boot(s3)
    s3.feed(f"{P}    TAG_CHANGE Entity={MIRROR} tag=RESOURCES value=9 ")
    check(s3.gold_base == 9, "mirror enchantment restates the player tags")

    # 7. Our hero: its entity entering PLAY in a recruit phase names it; a
    #    combat sighting (the opponent's hero mirrored into our controller)
    #    must not.
    s_h = CounterState()
    boot(s_h)
    s_h.feed(f"{P}TAG_CHANGE Entity=GameEntity tag=TURN value=2 ")
    s_h.feed(f"{P}FULL_ENTITY - Updating [entityName=Foe id=900 zone=PLAY "
             f"zonePos=0 cardId=BG25_HERO_999 player=2] CardID=BG25_HERO_999")
    check(s_h.hero is None, "a fight-time hero sighting is ignored")
    s_h.feed(f"{P}TAG_CHANGE Entity=GameEntity tag=TURN value=3 ")
    s_h.feed(f"{P}FULL_ENTITY - Updating [entityName=Us id=901 zone=PLAY "
             f"zonePos=0 cardId=BG25_HERO_103 player=2] CardID=BG25_HERO_103")
    check(s_h.hero == "BG25_HERO_103", "our hero lands from the recruit phase")

    # 8. A new game forgets the buffs and the hero with everything else.
    s_h.new_game()
    check(s_h.hero is None, "new game forgets the hero")
    s.new_game()
    check(not s.shop_buffs, "new game clears the accumulators")

    # 8. Same evening, same class of bug, different module: a patch-day
    #    minion the daily pool cache does not know yet reaches synergy() as
    #    None - WITH the board readable. That exact call killed the reader
    #    thread live; it must answer "nothing to say", never raise.
    from ui.synergy import synergy
    try:
        got = synergy(None, {"BEAST": 2}, 0, board_known=True)
        check(got is None, "an unknown card has no synergy, not a crash")
    except Exception as e:
        check(False, f"synergy(None) raised {type(e).__name__}")

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
