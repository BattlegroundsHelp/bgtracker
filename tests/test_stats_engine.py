#!/usr/bin/env python3
"""The two stats the engine could not produce: hero powers, and comps.

    python tests/test_stats_engine.py

Both gaps had the same shape - the log carries the fact, nothing mined it, so
the aggregator had nothing to publish and the panels showed a dash forever.
This holds the whole chain: mine -> upload shape -> store -> aggregate -> the
client reading its own output.

What each part is pinned to, and why:

  hero powers   one dialog is logged TWICE (SendChoices, then the server's echo)
                and one game can pick several powers, so the counts are the two
                places this can silently double. Both are checked with numbers.
  comps         a board that matches nothing must come back "none". A classifier
                that always answers is worthless: it moves the piles' placements
                into real archetypes and flattens every average toward the same
                number.
  the floor     a comp row below the floor must NOT be published, because the
                client drops its curated family list the moment one measured row
                arrives - a four-game ranking would replace a useful list.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import aggregate as agg  # noqa: E402
import bgtracker as bg  # noqa: E402
import collect  # noqa: E402
import ingest  # noqa: E402

PRE = "D 12:00:00.0000000 GameState."


def choice_block(cards, player="3", zone="SETASIDE"):
    """One EntityChoices block, written the way Hearthstone writes it - Source
    line included, because the Source of an ordinary discover is itself a hero
    power, and reading it as an option is the obvious way to get this wrong."""
    out = [f"{PRE}DebugPrintEntityChoices() - id=2 Player=Player#12345 "
           f"TaskList=1 ChoiceType=GENERAL CountMin=1 CountMax=1",
           f"{PRE}DebugPrintEntityChoices() -   Source=[entityName=Some Power "
           f"id=99 zone=PLAY zonePos=0 cardId=TB_BaconShop_HP_999 player={player}]"]
    for i, c in enumerate(cards):
        out.append(f"{PRE}DebugPrintEntityChoices() -   Entities[{i}]="
                   f"[entityName=Option {i} id={100 + i} zone={zone} zonePos=0 "
                   f"cardId={c} player={player}]")
    out.append(f"{PRE}DebugPrintPower() - TAG_CHANGE Entity=1 tag=ZONE value=PLAY")
    return out


def chosen(idx, card, player="3"):
    """A pick, logged twice: this client answering, then the server echoing."""
    ent = (f"[entityName=Option {idx} id={100 + idx} zone=SETASIDE zonePos=0 "
           f"cardId={card} player={player}]")
    return [f"{PRE}SendChoices() -   m_chosenEntities[0]={ent}",
            f"{PRE}DebugPrintEntitiesChosen() - id=2 Player=Player#12345 EntitiesCount=1",
            f"{PRE}DebugPrintEntitiesChosen() -   Entities[0]={ent}"]


def draft(hero_ids, player="3"):
    """The hero draft - the one thing that proves which player id is us."""
    return [f"D 12:00:00.0000000 GameState.DebugPrintPower() -     FULL_ENTITY "
            f"- Updating [entityName=Hero {i} id={10 + i} zone=HAND "
            f"zonePos={i + 1} cardId={h} player={player}] CardID={h}"
            for i, h in enumerate(hero_ids)]


HEROES = ["TB_BaconShop_HERO_01", "TB_BaconShop_HERO_02"]
POWERS = ["TB_BaconShop_HP_010", "BG26_HERO_102p", "TB_BaconShop_HP_068"]
MINIONS = ["BG36_202", "BG36_208", "BG36_209"]


def hero_power_mining() -> bool:
    ok = True
    _, _, powers_seen = collect.universe()
    if not powers_seen:
        print("  (no card database: hero powers are matched by id shape)")
    lines = (draft(HEROES) + choice_block(POWERS) + chosen(1, POWERS[1])
             + choice_block(MINIONS))

    _, off_h, _, _, off_p, pick_p = collect.offers(lines)
    print(f"  offered powers: {off_p}")
    print(f"  picked  powers: {pick_p}")
    if off_p != POWERS:
        print("    FAIL: the hero-power block was not mined as an offer")
        ok = False
    if pick_p != [POWERS[1]]:
        # The pick is logged twice; counting both is a 200% pick rate.
        print("    FAIL: the pick is wrong or double-counted")
        ok = False
    if any(c in off_p for c in MINIONS):
        print("    FAIL: a minion discover leaked into the hero-power offer")
        ok = False
    if "TB_BaconShop_HP_999" in off_p:
        print("    FAIL: the Source line was read as an option")
        ok = False
    if not off_h:
        print("    FAIL: mining hero powers broke the hero offer")
        ok = False

    # A game whose hero has a fixed power carries two empty lists, not a guess.
    plain = draft(HEROES) + choice_block(MINIONS)
    _, _, _, _, off2, pick2 = collect.offers(plain)
    print(f"  a game with no hero-power dialog -> {off2}, {pick2}")
    if off2 or pick2:
        print("    FAIL: invented a hero-power offer out of nothing")
        ok = False

    # Somebody else's dialog is not ours: the block must carry OUR player id.
    # extract() always hands the draft-proven id down, so this passes it too -
    # offers() on its own falls back to "whoever the first block belongs to",
    # which cannot tell this case apart and is not what runs in the collector.
    theirs = draft(HEROES) + choice_block(POWERS, player="7")
    _, _, _, _, off3, _ = collect.offers(theirs, "3")
    print(f"  another player's dialog -> {off3}")
    if off3:
        print("    FAIL: mined a hero-power offer that was not ours")
        ok = False
    return ok


def ingest_accepts() -> bool:
    ok = True
    base = {"uid": "a" * 32, "date": "2020-01-02", "hero": "BG20_HERO_100",
            "place": 3}
    old = ingest.validate(dict(base))
    print(f"  a record from an older client (no hero powers): stored, "
          f"offered={old['offered_hero_powers']}")
    if old["offered_hero_powers"] is not None or old["picked_hero_powers"] is not None:
        print("    FAIL: absent fields did not fall to null")
        ok = False

    new = ingest.validate({**base,
                           "offered_hero_powers": ["TB_BaconShop_HP_010", "!bad id"],
                           "picked_hero_powers": ["TB_BaconShop_HP_010"]})
    print(f"  whitelisted: {new['offered_hero_powers']}")
    if json.loads(new["offered_hero_powers"]) != ["TB_BaconShop_HP_010"]:
        print("    FAIL: the id whitelist let something through or dropped a good id")
        ok = False

    junk = ingest.validate({**base, "offered_hero_powers": "not a list"})
    if junk["offered_hero_powers"] is not None:
        print("    FAIL: a bad type became a value instead of null")
        ok = False
    print("  a bad type falls to null and the game is still stored")

    # The columns must appear in a store created before this field existed.
    with tempfile.TemporaryDirectory() as d:
        c = sqlite3.connect(Path(d) / "games.db")
        c.execute("CREATE TABLE games (uid TEXT PRIMARY KEY, ts INTEGER)")
        ingest.migrate(c)
        cols = {r[1] for r in c.execute("PRAGMA table_info(games)")}
        c.close()
    print(f"  migrate() added: {sorted(cols - {'uid', 'ts'})}")
    if not {"offered_hero_powers", "picked_hero_powers"} <= cols:
        print("    FAIL: an existing table never gains the new columns")
        ok = False
    return ok


def _blank(**over):
    """One aggregator-shaped game with nothing in it but what a test sets."""
    g = {"hero": None, "place": None, "duo": False, "date": "2020-01-01",
         "mmr": None, "tribes": [], "offered_heroes": [], "offered_trinkets": [],
         "picked_trinkets": [], "offered_hero_powers": [],
         "picked_hero_powers": [], "final_board": []}
    g.update(over)
    return g


def hero_power_table() -> bool:
    ok = True
    # A is picked in 30 games, alternating 2nd and 6th, so its average is
    # exactly 4.0 and its sample clears the client's MIN_SAMPLE. B is offered
    # every time and never taken. D is offered and taken in the first three
    # games only, which is the THIN case: a real average over three games,
    # which the client must not draw as a fact (see hero_power_table's floor).
    games = [_blank(place=2 if i % 2 == 0 else 6,
                    offered_hero_powers=(["A", "B", "C"] + (["D"] if i < 3 else [])),
                    picked_hero_powers=(["A"] + (["D"] if i < 3 else [])))
             for i in range(30)]
    # One more game picks the same power twice - a power that hands out another
    # power re-offers - which must count as ONE placement and TWO showings.
    games.append(_blank(place=4, offered_hero_powers=["A", "B", "C", "A", "B"],
                        picked_hero_powers=["A", "A"]))
    rows = {r["heroPowerCardId"]: r for r in agg.hero_power_stats(games)["heroPowerStats"]}
    a, b, d = rows["A"], rows["B"], rows["D"]
    for k, r in (("A", a), ("B", b), ("D", d)):
        print(f"  {k}: avg={r['averagePosition']} n={r['dataPoints']} "
              f"offered={r['totalOffered']} picked={r['totalPicked']}")
    if a["dataPoints"] != 31 or a["averagePosition"] != 4.0:
        print("    FAIL: a game that picked one power twice counted twice")
        ok = False
    if a["totalOffered"] != 32 or a["totalPicked"] != 32:
        print("    FAIL: offered/picked must count every showing (pick rate)")
        ok = False
    if b["averagePosition"] is not None or b["dataPoints"]:
        print("    FAIL: a power nobody took was given a placement")
        ok = False
    if not b["totalOffered"]:
        print("    FAIL: a power nobody took lost its offer count")
        ok = False
    if d["dataPoints"] != 3 or d["averagePosition"] is None:
        print("    FAIL: the aggregator is supposed to publish thin rows and "
              "let the client decide what to do with them")
        ok = False

    table = read_back({"heroPowerStats": list(rows.values())}, "heropowers",
                      lambda: bg.hero_power_table("100", "all-time"))
    print(f"  the client reads it back: {len(table)} powers, "
          f"A avg={table['A']['avg']} pick={table['A']['pick']:.0f}% "
          f"n={table['A']['n']} top4={bg.top4_rate(table['A']['dist'])}%")
    if table["A"]["avg"] != 4.0 or round(table["A"]["pick"]) != 100:
        print("    FAIL: the loader does not read its own aggregator's output")
        ok = False
    # The floor, and why this table enforces one where the hero table does not:
    # the hero-power window draws the number with no sample size beside it, so
    # there is nowhere to write "thin" and a three-game average would be read
    # as a measurement. It keeps its `n` and loses its number.
    for k in ("B", "D"):
        r = table[k]
        print(f"  {k} reads back as: avg={r['avg']} pick={r['pick']} "
              f"n={r['n']} thin={r['thin']}")
        if r["avg"] is not None or r["pick"] is not None or not r["thin"]:
            print(f"    FAIL: {k} is under {bg.MIN_SAMPLE} games and was still "
                  f"given a number")
            ok = False
    if table["D"]["n"] != 3:
        print("    FAIL: a thin row lost the sample size that explains it")
        ok = False
    if table["A"]["thin"]:
        print("    FAIL: a row over the floor was marked thin")
        ok = False
    return ok


def read_back(blob, key, load):
    """Write one feed file, point a throwaway sources.json at it, and let the
    client load it - the only way to prove the two halves agree on a shape."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "feed.json"
        p.write_text(json.dumps(blob), encoding="utf-8")
        old = bg.SOURCES_FILE
        bg.SOURCES_FILE = Path(d) / "sources.json"
        bg.SOURCES_FILE.write_text(json.dumps({key: str(p)}), encoding="utf-8")
        try:
            return load()
        finally:
            bg.SOURCES_FILE = old


def family_board(archetype, tribe, size=6):
    """A board built the way a player builds that comp: the family's own engine
    pieces first, all of its tribe, taken out of the LIVE pool."""
    entry = bg.comp_roles()[archetype]
    mine = [m for m in bg.bg_pool() if tribe in m["races"] or "ALL" in m["races"]]
    core = [m for m in mine if bg._role_hit(m, entry["core"])]
    rest = [m for m in mine if m not in core]
    return [m["id"] for m in (core[:2] + rest)[:size]]


def board_classification() -> bool:
    ok = True
    for archetype, tribe in (("undead deathrattle", "UNDEAD"),
                             ("naga spellcraft", "NAGA"),
                             ("mech magnetic", "MECHANICAL")):
        got = bg.classify_board(family_board(archetype, tribe))
        print(f"  {archetype:22} -> {got and got['archetype']} "
              f"(share {got and got['share']}, core {got and got['core']})")
        if not got or got["archetype"] != archetype:
            print("    FAIL: a board built as this family was not recognised")
            ok = False

    # A spread board: one minion from each of six tribes, nothing dominant.
    one_each, seen = [], set()
    for m in bg.bg_pool():
        r = next((t for t in m["races"] if t in bg.TRIBES), None)
        if r and r not in seen:
            seen.add(r)
            one_each.append(m["id"])
        if len(one_each) == 6:
            break
    got = bg.classify_board(one_each)
    print(f"  six tribes, one minion each -> {got and got['archetype']}")
    if got and got["archetype"] != "menagerie":
        print("    FAIL: a spread board was forced into a tribe bucket")
        ok = False

    small = bg.classify_board(one_each[:2])
    print(f"  a two-minion board -> {small}")
    if small is not None:
        print("    FAIL: a board too small to have an identity was classified")
        ok = False
    if bg.classify_board([]) is not None:
        print("    FAIL: an empty board was classified")
        ok = False
    print("  an empty board -> None")

    # Golden pieces are the same comp.
    gold = bg.golden_aliases()
    board = family_board("undead deathrattle", "UNDEAD")
    base_of = {}
    for g, base in gold.items():
        base_of.setdefault(base, g)
    swapped = [base_of.get(c, c) for c in board]
    got = bg.classify_board(swapped)
    print(f"  the same board, {sum(1 for a, b in zip(board, swapped) if a != b)} "
          f"of {len(board)} pieces golden -> {got and got['archetype']}")
    if not got or got["archetype"] != "undead deathrattle":
        print("    FAIL: golden pieces broke the classification")
        ok = False
    return ok


def comp_publish_floor() -> bool:
    ok = True
    board = family_board("undead deathrattle", "UNDEAD")

    def games(n):
        return [_blank(place=(i % 8) + 1, final_board=board) for i in range(n)]

    thin = agg.comp_stats(games(agg.COMP_MIN_GAMES - 1))
    print(f"  {agg.COMP_MIN_GAMES - 1} games of one archetype -> "
          f"{len(thin['compStats'])} rows, counts "
          f"{thin['compClassification']['byArchetype']}")
    if thin["compStats"]:
        print("    FAIL: published a comp row under the floor")
        ok = False
    if thin["compClassification"]["classified"] != agg.COMP_MIN_GAMES - 1:
        print("    FAIL: the classification counts are wrong")
        ok = False

    full = agg.comp_stats(games(agg.COMP_MIN_GAMES))
    row = full["compStats"][0] if full["compStats"] else None
    print(f"  {agg.COMP_MIN_GAMES} games -> {row and row['archetype']}, "
          f"avg={row and row['averagePlacement']}, n={row and row['dataPoints']}, "
          f"freq={row and row['frequency']}")
    if not row or row["dataPoints"] != agg.COMP_MIN_GAMES:
        print("    FAIL: an archetype over the floor was not published")
        ok = False

    # ...and the client turns that row into the comps panel, key minions and all.
    table = read_back(full, "comps", lambda: bg.comp_table("all-time", "100"))
    got = table[0]
    print(f"  the client reads it: {got['archetype']} avg={got['avg']} n={got['n']} "
          f"key={got['key'][:2]} freq of the first="
          f"{list(got['freq'].values())[:1]}")
    if got.get("baseline") or not got["key"]:
        print("    FAIL: the measured row did not reach the panel with its minions")
        ok = False

    # Nothing to classify is not an empty answer with no explanation.
    none = agg.comp_stats([_blank(place=1)])
    print(f"  no boards at all -> {none['compClassification']}")
    if none["compStats"] or none["compClassification"]["boards"]:
        print("    FAIL: a pool with no boards did not report itself as such")
        ok = False
    return ok


def main() -> int:
    try:
        bg.bg_pool()
    except Exception as e:
        print(f"no card pool available ({e}) - cannot run")
        return 1
    ok = True
    for name, fn in (("hero powers: mining", hero_power_mining),
                     ("hero powers: ingest", ingest_accepts),
                     ("hero powers: table", hero_power_table),
                     ("comps: classification", board_classification),
                     ("comps: publish floor", comp_publish_floor)):
        print(f"\n{name}")
        ok &= fn()
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
