#!/usr/bin/env python3
"""
The spec sheet for the combat simulator: every card, every effect, every
enchantment that really lands on a minion.

    python tools/catalog.py                 # write docs/CARD_EFFECTS.md + data/effects_catalog.json
    python tools/catalog.py --enchantments  # also mine YOUR logs for enchantments actually applied

Three lists, and one of them cannot come from the card database:

1. THE CARDS. Every minion in the current Battlegrounds pool, with tier, tribe
   and printed text, plus the hero and trinket counts. Straight from
   HearthstoneJSON, so it is always this patch's pool.

2. THE EFFECTS. Each pool minion's text classified by WHEN it happens, which is
   the only thing the simulator cares about:
     - PRE_SNAPSHOT: start of combat, battlecry, tavern-phase buffs, static
       auras. sim/boards.py snapshots both warbands at the FIRST ATTACK, so
       these have ALREADY resolved into the stats and keyword tags we read.
       Scripting them double-counts and makes the sim worse. They are listed
       so nobody scripts them by mistake.
     - IN_COMBAT: deathrattles, on-attack, on-damage, whenever-triggers. This
       is the real work queue.
     - VANILLA: no text, or text with no combat effect. Nothing to do.

3. THE DARK GIFTS. HearthstoneJSON carries no Dark Gift marker: searching the
   whole database for DARK_GIFT returns nothing. But the game names the gift
   outright when it lands (DARK_GIFT_ENTITY -> an entity whose CardID the log
   carries), and mining 6 real logs showed every one of 318 applications was a
   card in the SAME id family. So the family is the list, and it comes from the
   database complete rather than only the ones that happened to be offered.
   `--gifts` re-runs that log check: it is what proves the family is right, and
   it says which gifts have actually been seen.

   The classification matters more than the list. A gift lands in the TAVERN,
   so a stat or a keyword it grants is an ordinary tag on the minion long
   before the board is captured, and scripting it would double-count. Only a
   gift that fires DURING the fight and changes the BOARD needs a script.
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bgtracker as bg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "docs" / "CARD_EFFECTS.md"
OUT_JSON = ROOT / "data" / "effects_catalog.json"

# WHEN an effect happens, which is all the simulator needs to know. Order
# matters: the first match wins, and PRE_SNAPSHOT is checked first precisely
# because a card can say both ("Start of Combat" plus a Deathrattle).
PRE_SNAPSHOT = [
    ("start of combat", r"[Ss]tart of [Cc]ombat"),
    ("battlecry", r"<b>Battlecry</b>|[Bb]attlecry:"),
    ("end of turn", r"[Aa]t the end of your turn"),
    ("aura (static)", r"[Yy]our other|[Oo]ther friendly|[Ww]henever you (buy|play|sell)"),
    ("tavern only", r"[Tt]avern|[Rr]efresh|[Bb]lood [Gg]em|[Gg]old|[Tt]riple|[Dd]iscover"),
]
IN_COMBAT = [
    ("deathrattle summon", r"[Dd]eathrattle:.*[Ss]ummon"),
    ("deathrattle buff", r"[Dd]eathrattle:.*(give|gain|\+\d)"),
    ("deathrattle other", r"[Dd]eathrattle:"),
    ("on attack", r"[Aa]fter this (minion )?attacks|[Ww]henever this (minion )?attacks"),
    ("on damage", r"[Ww]henever this (minion )?(takes|is dealt)"),
    ("on kill", r"[Ww]henever this (minion )?kills"),
    ("cleave", r"[Aa]lso damages? the minions next to"),
    ("avenge", r"<b>Avenge"),
]


# A Dark Gift is judged by a different clock than a minion. It lands in the
# TAVERN, so anything it does there - a stat grant, a keyword, a card played,
# an end-of-turn tick - has already resolved into the stats boards.py captures
# at the first attack. Only a gift that fires DURING the fight needs a script,
# and only if it changes the BOARD (a gift that hands you a card or a refresh
# changes nothing about who wins the combat).
# The bold markup is stripped before these run, so match the plain words.
GIFT_NO_EFFECT = r"[Gg]et (a|2|an) |[Rr]efresh|[Bb]lood [Gg]em|Fodder|Triple Reward"
GIFT_IN_COMBAT = [
    ("deathrattle", r"[Dd]eathrattle"),
    ("rally", r"[Rr]ally"),
    ("attacking", r"while attacking"),
    ("divine shield", r"[Dd]ivine [Ss]hield takes"),
    ("reborn", r"[Rr]eborn"),
]
# WHEN beats WHAT. These are checked before the keywords above, because a gift
# can name a keyword and still have finished its work before the fight: "Start
# of Combat: Trigger this minion's Deathrattles" resolves, and its tokens are
# standing on the board, before the snapshot is taken; "+2/+2 for each
# Deathrattle you've triggered this game" is already inside the printed stats.
GIFT_PRE_SNAPSHOT = [
    ("start of combat", r"[Ss]tart of [Cc]ombat"),
    ("this-game counter", r"for each"),
    ("end of turn", r"end of (your |every )?turn|end of every"),
    ("on play (tavern)", r"[Ww]henever you play"),
]


def classify_gift(text):
    """(bucket, label) for one Dark Gift's printed text."""
    t = (text or "").replace("\n", " ")
    if not t.strip():
        return "VANILLA", "no text"
    if re.search(GIFT_NO_EFFECT, t) and not re.search(r"[Ss]ummon|[Gg]ive this", t):
        return "NO_BOARD_EFFECT", "changes your cards, not the fight"
    for label, pat in GIFT_PRE_SNAPSHOT:
        if re.search(pat, t):
            return "PRE_SNAPSHOT", label
    for label, pat in GIFT_IN_COMBAT:
        if re.search(pat, t):
            return "IN_COMBAT", label
    return "PRE_SNAPSHOT", "stat / keyword grant"


def gift_universe():
    """Every Dark Gift in the game this patch, from the card database.

    They carry no DARK_GIFT marker, but they DO share an id family - measured
    off a real log, every gift the game applied was a `BG36_MidGameEffect_000t*`
    card - so the family is discoverable and this list stays complete when the
    next set renames it. Each gift exists several times over (the offered
    spell, then one enchantment per stage); they are grouped by name and the
    shortest id kept, which is the one the log names in DARK_GIFT_ENTITY.
    """
    fam = re.compile(r"^BG\d+_MidGameEffect_\d+t")
    rows = [c for c in bg._fetch(bg.CARDS_URL) if fam.match(c.get("id") or "")]
    by_name = collections.defaultdict(list)
    for c in rows:
        by_name[c.get("name") or "?"].append(c)
    out = []
    for name, group in by_name.items():
        group.sort(key=lambda c: (len(c["id"]), c["id"]))
        text = next((c["text"] for c in group if c.get("text")), "")
        # A gift you can actually be OFFERED exists twice over: the card the
        # Dark Discovery shows, and the enchantment it leaves behind. One with
        # nothing but an enchantment is a leftover the game no longer deals -
        # measured: every gift seen in 318 real applications had both, and the
        # single enchantment-only gift never appeared once.
        offered = [c for c in group if (c.get("type") or "") != "ENCHANTMENT"]
        out.append({"id": (offered or group)[0]["id"], "name": name,
                    "text": re.sub(r"</?b>", "", text).replace("\n", " "),
                    "variants": len(group), "offered": bool(offered)})
    out.sort(key=lambda r: r["name"])
    return out


def classify(text):
    """(bucket, label) for one card's printed text."""
    t = (text or "").replace("\n", " ")
    if not t.strip():
        return "VANILLA", "no text"
    for label, pat in PRE_SNAPSHOT:
        if re.search(pat, t):
            return "PRE_SNAPSHOT", label
    for label, pat in IN_COMBAT:
        if re.search(pat, t):
            return "IN_COMBAT", label
    return "VANILLA", "no combat effect"


def build():
    pool = bg.bg_pool()
    ids = bg.bg_ids()
    try:
        from sim import engine
        scripted = set(engine.SCRIPTS)
        # Derived scripts count too: a card whose printed text auto-derives a
        # token summon or cleave IS scripted, and listing it as work made the
        # queue lie (Buzzing Vermin sat in it with its Beetle fully modelled).
        # The bare rally flag models nothing by itself - it only marks the
        # minion for rally watchers - so entries carrying nothing else stay
        # in the queue.
        for cid, entry in engine.merged_scripts().items():
            if set(entry) - {"rally", "golden"}:
                scripted.add(cid)
        floors = set(engine.UNMODELLED)
    except Exception:
        scripted = set()
        floors = set()

    rows = []
    for m in pool:
        bucket, label = classify(m.get("text"))
        rows.append({
            "id": m["id"], "name": m["name"], "tier": m.get("techLevel"),
            "races": m.get("races") or [], "text": (m.get("text") or "").replace("\n", " "),
            "bucket": bucket, "effect": label, "scripted": m["id"] in scripted,
            "floor": m["id"] in floors,
        })
    rows.sort(key=lambda r: (r["bucket"] != "IN_COMBAT", -(r["tier"] or 0), r["name"]))

    counts = collections.Counter(r["bucket"] for r in rows)
    todo = [r for r in rows if r["bucket"] == "IN_COMBAT" and not r["scripted"]]

    try:
        gifts = gift_universe()
    except Exception as e:
        print(f"dark gifts unavailable ({e})")
        gifts = []
    for g in gifts:
        g["bucket"], g["effect"] = classify_gift(g["text"])
        g["scripted"] = g["id"] in scripted
    gcounts = collections.Counter(g["bucket"] for g in gifts)
    gtodo = [g for g in gifts
             if g["bucket"] == "IN_COMBAT" and not g["scripted"] and g["offered"]]
    retired = [g for g in gifts if not g["offered"]]

    cat = {
        "generated_from": "HearthstoneJSON, the live card database",
        "pool_minions": len(rows), "heroes": len(ids["heroes"]),
        "trinkets": len(ids["trinkets"]),
        "buckets": dict(counts),
        "scripted": sum(1 for r in rows if r["scripted"]),
        "work_queue": len(todo),
        "dark_gifts": len(gifts),
        "dark_gift_buckets": dict(gcounts),
        "dark_gift_work_queue": len(gtodo),
        "dark_gifts_retired": [g["name"] for g in retired],
        "minions": rows,
        "gifts": gifts,
    }
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(cat, indent=1), encoding="utf-8")

    md = ["# Card effects catalogue", "",
          "Generated by `python tools/catalog.py` from the live card database, so it",
          "is always this patch's pool. Do not hand-edit.", "",
          f"- **{len(rows)}** minions in the pool, **{len(ids['heroes'])}** heroes, "
          f"**{len(ids['trinkets'])}** trinkets",
          f"- **{counts.get('IN_COMBAT', 0)}** have an effect that happens DURING combat "
          f"(the only ones a script can help), of which **{len(todo)}** are unscripted",
          f"- **{counts.get('PRE_SNAPSHOT', 0)}** resolve BEFORE the snapshot and must never be "
          "scripted: they are already inside the stats we read",
          f"- **{counts.get('VANILLA', 0)}** have no combat effect at all", "",
          "## The work queue: in-combat effects with no script yet", "",
          "| tier | card | effect | text |", "|---|---|---|---|"]
    for r in todo:
        md.append(f"| {r['tier']} | {r['name']} | {r['effect']} | {r['text'][:90]} |")
    part = [r for r in rows if r["floor"] and r["scripted"]]
    if part:
        md += ["", "## Scripted as a FLOOR (a hidden remainder still widens the odds)", "",
               "The board-visible part is modelled; the invisible part (a this-game",
               "counter, a random pull's own text, a hand) stays in `engine.UNMODELLED`",
               "so the sim keeps claiming less certainty on boards that hold these.", "",
               "| tier | card | text |", "|---|---|---|"]
        for r in sorted(part, key=lambda r: (-(r["tier"] or 0), r["name"])):
            md.append(f"| {r['tier']} | {r['name']} | {r['text'][:90]} |")
    md += ["", "## Already resolved before the snapshot (do NOT script)", "",
           "| card | why | text |", "|---|---|---|"]
    for r in (x for x in rows if x["bucket"] == "PRE_SNAPSHOT"):
        md.append(f"| {r['name']} | {r['effect']} | {r['text'][:80]} |")

    if gifts:
        md += ["", f"# Dark Gifts ({len(gifts)})", "",
               "The card database has no Dark Gift marker, but every gift the game applied",
               "in a real log was a card in the same id family, so the family IS the list.",
               "A gift lands in the tavern, so a stat or keyword it grants is already an",
               "ordinary tag on the minion by the time the board is captured. Only a gift",
               f"that fires during the fight AND changes the board needs a script: **{len(gtodo)}**",
               "of them are unscripted.", "",
               "| gift | when | scripted | text |", "|---|---|---|---|"]
        for g in sorted(gifts, key=lambda x: (x["bucket"] != "IN_COMBAT",
                                              x["scripted"], x["name"])):
            if not g["offered"]:
                mark = "retired"
            elif g["scripted"]:
                mark = "yes"
            else:
                mark = "**NO**" if g["bucket"] == "IN_COMBAT" else "n/a"
            md.append(f"| {g['name']} | {g['bucket'].lower()}: {g['effect']} | {mark} "
                      f"| {g['text'][:70]} |")

    OUT_MD.parent.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"pool minions      {len(rows)}")
    for b in ("IN_COMBAT", "PRE_SNAPSHOT", "VANILLA"):
        print(f"  {b:14} {counts.get(b, 0)}")
    print(f"scripted          {cat['scripted']}")
    print(f"WORK QUEUE        {len(todo)} in-combat effects with no script")
    if gifts:
        print(f"dark gifts        {len(gifts)}")
        for b in ("IN_COMBAT", "PRE_SNAPSHOT", "NO_BOARD_EFFECT", "VANILLA"):
            if gcounts.get(b):
                print(f"  {b:16} {gcounts[b]}")
        print(f"  scripted         {sum(1 for g in gifts if g['scripted'])}")
        if retired:
            print(f"  retired          {len(retired)} "
                  f"({', '.join(g['name'] for g in retired)})")
        print(f"GIFT WORK QUEUE   {len(gtodo)}"
              + (": " + ", ".join(g["name"] for g in gtodo) if gtodo
                 else " - every gift that can be offered is either already in the "
                      "snapshot or scripted"))
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}")
    return rows


# How the game states a Dark Gift, measured in a real Power.log:
#
#   TAG_CHANGE Entity=7235 tag=DARK_GIFT_ENTITY value=7238
#   SHOW_ENTITY - Updating Entity=7238 CardID=BG36_...
#
# so the MINION is 7235 and the GIFT is a separate entity 7238 whose CardID
# the log does carry. An earlier version of this miner looked for
# `tag=ATTACHED`, which is a different thing entirely (and is written on its
# own line with no cardId on it) - it found zero gifts across 1.3 GB of logs.
GIFT_RE = re.compile(r"tag=DARK_GIFT_ENTITY value=(\d+)")
# entity ids restart every game, so the id -> card map has to restart too
NEWGAME = "CREATE_GAME"
CARDID_RE = re.compile(r"(?:FULL_ENTITY - Creating ID|SHOW_ENTITY - Updating Entity)=(\d+)"
                       r" CardID=(\S+)")
BRACKET_RE = re.compile(r"\[entityName=(.+?) id=(\d+) zone=\S+ zonePos=\d+ cardId=(\S*)")


def dark_gifts(limit=60):
    """Every Dark Gift that really landed on a minion in YOUR logs.

    The card database has no Dark Gift marker - searching it for DARK_GIFT
    returns nothing - so the game itself is the only honest source.
    """
    names = bg.card_names()
    gifts = collections.Counter()     # gift cardId -> times applied
    carriers = collections.Counter()  # which minions got gifted
    logs = sorted(bg.HS_LOGS.glob("Hearthstone_*/Power.log"))
    if not logs:
        print("no Power.log found")
        return
    unresolved = 0
    for lg in logs:
        ents, pending = {}, {}
        with open(lg, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "GameState" not in line:
                    continue        # PowerTaskList repeats every line; count once
                if NEWGAME in line:
                    for eid in pending:
                        cid = ents.get(eid)
                        if cid:
                            gifts[cid] += 1
                        else:
                            unresolved += 1
                    ents, pending = {}, {}
                    continue
                if "CardID=" in line:
                    m = CARDID_RE.search(line)
                    if m and m.group(2):
                        ents[int(m.group(1))] = m.group(2)
                    continue
                if "DARK_GIFT_ENTITY" not in line:
                    continue
                g = GIFT_RE.search(line)
                if not g or g.group(1) == "0":
                    continue          # value=0 is the gift being cleared
                pending[int(g.group(1))] = True
                b = BRACKET_RE.search(line)
                if b and b.group(3):
                    carriers[b.group(3)] += 1
        for eid in pending:
            cid = ents.get(eid)
            if cid:
                gifts[cid] += 1
            else:
                unresolved += 1

    print(f"DARK GIFTS really applied, across {len(logs)} logs: "
          f"{len(gifts)} distinct, {sum(gifts.values())} applications"
          + (f" ({unresolved} whose card the log never revealed)" if unresolved else ""))
    for cid, n in gifts.most_common(limit):
        print(f"  {n:5}  {cid:22} {names.get(cid, '?')}")
    if carriers:
        print(f"\nminions that received one: {len(carriers)} distinct")
        for cid, n in carriers.most_common(12):
            print(f"  {n:5}  {cid:22} {names.get(cid, '?')}")
    return gifts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gifts", "--enchantments", dest="gifts", action="store_true",
                    help="mine your own logs for the Dark Gifts that really landed")
    a = ap.parse_args()
    build()
    if a.gifts:
        print()
        dark_gifts()
