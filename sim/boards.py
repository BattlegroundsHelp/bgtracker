"""Reconstruct BOTH Battlegrounds boards at combat start from Power.log alone.

Empirical question this module answers: when a BG combat begins
(TAG_CHANGE tag=BACON_CURRENT_COMBAT_PLAYER_ID value=N>0), can both warbands be
read out of the log BEFORE the first attack resolves?

How the log is structured (verified against real 2026-08 logs):
- Every combat is logged TWICE: once by GameState.DebugPrintPower() (the whole
  server batch, written within milliseconds of combat start, outcome included)
  and again by PowerTaskList.DebugPrintPower() (replayed as the animation runs).
  We parse ONLY the GameState copy and use the PowerTaskList marker just to
  measure the animation lead time.
- The real Hearthstone game has TWO controllers: the local player (real
  GameAccountId / battletag) and one AI seat that hosts Bob during recruit and
  every enemy warband during combat. The other 6-7 lobby players exist only as
  leaderboard hero entities parked in SETASIDE.
- At combat start the enemy hero, hero power, trinkets and minions are
  FULL_ENTITY-created (or SHOW_ENTITY-revealed) under the AI controller, then
  start-of-combat triggers run, then the first BLOCK_START BlockType=ATTACK.
- Our own board persists across phases, so it must be tracked from the whole
  log (FULL_ENTITY / SHOW_ENTITY / CHANGE_ENTITY / TAG_CHANGE zone moves).

Usage:
    python sim/boards.py <Power.log> [--min-round N] [--indent]
prints a JSON document: {"combats": [...], "summary": {...}}.

Every combat carries honest completeness flags; nothing is guessed.

Empirical results (2026-08-11, 6 real logs, 24 games, 222 combats):
- Round 5+: 149/149 combats (100%) had BOTH boards fully recovered with card
  ids, stats and keywords BEFORE the first attack; 100% outcomes extracted.
- All rounds: 220/222; the 2 "misses" were rounds 1-2 where the enemy board
  was GENUINELY empty (unanswered hero hit for 2-3 confirms it) - the
  enemy_board_recovered flag simply treats len==0 as unproven.
- Timing: the server batch (boards AND outcome) hits the log ~1.4s (median,
  min 0.7s) BEFORE the fight starts animating; the first attack line lands
  ~0.8-1.3s after the combat marker. An odds feature has the whole fight
  animation (tens of seconds) to display.
- Enemy minions are created with BASE stats; their buffed fight-true stats
  arrive via numeric TAG_CHANGE lines still before the first attack
  (verified: 12/14 base -> 129/145 actual).
- tests/fixture.log contains ZERO combat blocks (it is the offer-detection
  fixture) - only real Power.logs exercise this module.

Known limits (deliberate, documented, not silent):
- Ghost (dead-player) fights still report the hero-attack damage the log
  shows, even though nobody's health really changes.
- Duos player identification uses "first real GameAccountId" - fine for solo
  logs; duos would need the hero-draft trick from collect.py.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta

LINE_RE = re.compile(
    r"^D (?P<ts>\d{2}:\d{2}:\d{2}\.\d+) "
    r"(?P<src>GameState|PowerTaskList)\.DebugPrint(?:Power|Game)\(\) -(?P<body>.*)$"
)
BRACKET_RE = re.compile(
    r"\[entityName=(?P<name>.*?) id=(?P<id>\d+) zone=(?P<zone>\S+) "
    r"zonePos=(?P<zonePos>\d+) cardId=(?P<cardId>\S*) player=(?P<player>\d+)\]"
)
TAG_LINE_RE = re.compile(r"^tag=(?P<tag>\S+) value=(?P<value>.+?)\s*$")
TAG_CHANGE_RE = re.compile(
    r"^TAG_CHANGE Entity=(?P<ent>.+?) tag=(?P<tag>\S+) value=(?P<value>\S+)"
)
FULL_CREATE_RE = re.compile(r"^FULL_ENTITY - Creating ID=(?P<id>\d+) CardID=(?P<cardId>\S*)")
FULL_UPDATE_RE = re.compile(r"^FULL_ENTITY - Updating (?P<ent>.+?) CardID=(?P<cardId>\S*)")
SHOW_RE = re.compile(r"^SHOW_ENTITY - Updating (?:Entity=)?(?P<ent>.+?) CardID=(?P<cardId>\S*)")
CHANGE_RE = re.compile(r"^CHANGE_ENTITY - Updating (?:Entity=)?(?P<ent>.+?) CardID=(?P<cardId>\S*)")
HIDE_RE = re.compile(r"^HIDE_ENTITY - Entity=(?P<ent>.+?) tag=ZONE value=(?P<zone>\S+)")
PLAYER_RE = re.compile(
    r"Player EntityID=(?P<eid>\d+) PlayerID=(?P<pid>\d+) "
    r"GameAccountId=\[hi=(?P<hi>\d+) lo=(?P<lo>\d+)\]"
)
PLAYER_NAME_RE = re.compile(r"^PlayerID=(?P<pid>\d+), PlayerName=(?P<name>.+?)\s*$")
BLOCK_START_RE = re.compile(r"^BLOCK_START BlockType=(?P<type>\w+)")
ATTACK_ENT_RE = re.compile(r"Entity=(?P<ent>.+?) EffectCardId=")
META_DMG_RE = re.compile(r"^META_DATA - Meta=DAMAGE Data=(?P<data>\d+)")

# Keyword tags surfaced per minion in a snapshot.
KEYWORD_TAGS = (
    "TAUNT",
    "DIVINE_SHIELD",
    "POISONOUS",
    "VENOMOUS",
    "REBORN",
    "WINDFURY",
    "STEALTH",
    "DEATHRATTLE",
)

BOB_CARD_IDS = {"TB_BaconShopBob", "TB_BaconShop_HERO_PH"}


def _parse_ts(s: str) -> datetime:
    head, frac = s.split(".")
    return datetime.strptime(f"{head}.{frac[:6]}", "%H:%M:%S.%f")


def _ms(a: datetime, b: datetime) -> float:
    d = b - a
    if d < timedelta(0):  # midnight rollover
        d += timedelta(days=1)
    return round(d.total_seconds() * 1000.0, 1)


class Entity:
    __slots__ = ("eid", "card_id", "name", "tags")

    def __init__(self, eid: int, card_id: str = "", name: str = ""):
        self.eid = eid
        self.card_id = card_id
        self.name = name
        self.tags: dict[str, str] = {}

    def num(self, tag: str, default: int = 0) -> int:
        v = self.tags.get(tag)
        if v is None:
            return default
        try:
            return int(v)
        except ValueError:
            return default


class GameLogParser:
    """Streams one Power.log; emits one dict per GameState combat block."""

    def __init__(self):
        self.combats: list[dict] = []
        self.games = 0
        self._reset_game()

    # -- game state ---------------------------------------------------------
    def _reset_game(self):
        self.entities: dict[int, Entity] = {}
        self.local_eid = None  # player-entity id of the local player
        self.ai_eid = None
        self.local_ctrl = None  # PlayerID / CONTROLLER value of local player
        self.ai_ctrl = None
        self.local_name = None
        self.turn = 0
        self.depth = 0
        self.pending_tags_for: Entity | None = None
        self.combat: dict | None = None
        self._cb = None  # internal combat bookkeeping
        self._await_ptl_marker: list[dict] = []

    # -- entity reference resolution ---------------------------------------
    def _ent_from_ref(self, ref: str) -> Entity | None:
        ref = ref.strip()
        if ref.isdigit():
            return self._ent(int(ref))
        m = BRACKET_RE.search(ref)
        if m:
            e = self._ent(int(m.group("id")))
            if m.group("name") not in ("UNKNOWN ENTITY", ""):
                e.name = m.group("name")
            if m.group("cardId") and not e.card_id:
                e.card_id = m.group("cardId")
            return e
        if ref == "GameEntity":
            return None  # GameEntity tags handled where needed
        # plain name: a player entity. Local battletag -> local player entity,
        # anything else (Bartender Bob / current opponent's name) -> AI seat.
        if self.local_name and ref == self.local_name and self.local_eid:
            return self._ent(self.local_eid)
        if self.ai_eid:
            return self._ent(self.ai_eid)
        return None

    def _ent(self, eid: int) -> Entity:
        e = self.entities.get(eid)
        if e is None:
            e = Entity(eid)
            self.entities[eid] = e
        return e

    # -- snapshots ----------------------------------------------------------
    def _minion_row(self, e: Entity) -> dict:
        row = {
            "id": e.eid,
            "cardId": e.card_id,
            "name": e.name or None,
            "pos": e.num("ZONE_POSITION"),
            "atk": e.num("ATK"),
            "health": e.num("HEALTH"),
            "damage": e.num("DAMAGE"),
            "golden": e.num("PREMIUM") == 1,
        }
        for t in KEYWORD_TAGS:
            if e.num(t):
                row[t.lower()] = e.num(t)
        # DARK GIFTS. A gift whose effect is a stat or keyword change lands on
        # the minion as ordinary tags, so it is already in the fields above
        # (verified in a real log: Harpy's Talons wrote plain DIVINE_SHIELD=1
        # and WINDFURY=1 on the gifted minion). A gift whose effect is a
        # TRIGGER writes no stat tag at all - only HAS_DARK_GIFT=1 plus
        # DARK_GIFT_ENTITY pointing at the gift entity, whose CardID the log
        # does carry. Resolve that reference so the sim can script it.
        gift = e.num("DARK_GIFT_ENTITY")
        if gift:
            g = self.entities.get(gift)
            if g is not None and g.card_id:
                row["dark_gift"] = g.card_id
        return row

    def _board(self, ctrl: int) -> list[dict]:
        rows = [
            self._minion_row(e)
            for e in self.entities.values()
            if e.tags.get("CARDTYPE") == "MINION"
            and e.tags.get("ZONE") == "PLAY"
            and e.num("CONTROLLER") == ctrl
        ]
        rows.sort(key=lambda r: r["pos"])
        return rows

    def _hero_row(self, ctrl: int) -> dict | None:
        """The hero standing in PLAY for one controller, with the tags an odds
        display needs. PLAYER_TECH_LEVEL is written on hero entities (our own
        hero keeps it all game; the enemy combat copy receives it by
        TAG_CHANGE during combat setup, before the first attack - verified in
        real 2026-08 logs). HEALTH / ARMOR / DAMAGE ride the same entity, so
        remaining life = health - damage + armor."""
        for e in self.entities.values():
            if (
                e.tags.get("CARDTYPE") == "HERO"
                and e.tags.get("ZONE") == "PLAY"
                and e.num("CONTROLLER") == ctrl
                and e.card_id not in BOB_CARD_IDS
                and e.card_id
            ):
                return {
                    "cardId": e.card_id,
                    "tier": e.num("PLAYER_TECH_LEVEL"),
                    "health": e.num("HEALTH"),
                    "armor": e.num("ARMOR"),
                    "damage": e.num("DAMAGE"),
                }
        return None

    def _snapshot(self) -> dict:
        ours = self._board(self.local_ctrl) if self.local_ctrl is not None else []
        theirs = self._board(self.ai_ctrl) if self.ai_ctrl is not None else []
        heroes = {
            "friendly": self._hero_row(self.local_ctrl)
            if self.local_ctrl is not None else None,
            "enemy": self._hero_row(self.ai_ctrl)
            if self.ai_ctrl is not None else None,
        }
        return {"friendly": ours, "enemy": theirs, "heroes": heroes}

    # -- combat lifecycle ---------------------------------------------------
    def _combat_start(self, ts: str, lineno: int, first_value: int):
        # Empirical: GameEntity TURN == BG round (one Hearthstone turn per
        # recruit+combat round; verified 13 combats = TURN 1..13).
        rnd = self.turn
        self._await_ptl_marker.clear()  # a new combat supersedes an unmatched one
        self.combat = {
            "game": self.games,
            "line": lineno,
            "ts": ts,
            "turn_raw": self.turn,
            "round": rnd,
            "opponent_player_id": None,
            "opponent_hero": None,
            "opponent_name": None,
            "boards_at_reveal": None,
            "boards_pre_attack": None,
            "attacks": 0,
            "first_attack_ms_after_start": None,
            "animation_start_ms_after_start": None,
            "outcome": {"winner": "unknown", "damage": 0, "basis": "none"},
            "flags": {},
        }
        self._cb = {
            "start_ts": _parse_ts(ts),
            "marker_depth": self.depth,
            "marker_values": [first_value],
            # Outcome comes from the fight's final blow: a BlockType=ATTACK
            # whose attacker is a HERO. Winner = that hero's side; damage =
            # the META_DATA Meta=DAMAGE inside that block. (Comparing hero
            # DAMAGE/ARMOR end-state does NOT work: the combat copy is reset
            # inside the block after the fight.)
            "pending_ha": None,
            "hero_attack": None,
            "reveal_done": False,
        }

    def _maybe_take_reveal_snapshot(self):
        cb = self._cb
        if cb and not cb["reveal_done"] and self.depth < cb["marker_depth"]:
            cb["reveal_done"] = True
            self.combat["boards_at_reveal"] = self._snapshot()

    def _note_attack(self, ts: str):
        c, cb = self.combat, self._cb
        if c is None:
            return
        if c["boards_pre_attack"] is None:
            if not cb["reveal_done"]:
                cb["reveal_done"] = True
                c["boards_at_reveal"] = self._snapshot()
            c["boards_pre_attack"] = self._snapshot()
            c["first_attack_ms_after_start"] = _ms(cb["start_ts"], _parse_ts(ts))
        c["attacks"] += 1

    def _watch_hero_if_combat_copy(self, e: Entity):
        """A HERO in PLAY under the AI controller during combat is the
        opponent's combat-phase hero copy; record its card id."""
        if self.combat is None or self.combat["opponent_hero"] is not None:
            return
        if (
            e.tags.get("CARDTYPE") == "HERO"
            and e.tags.get("ZONE") == "PLAY"
            and self.ai_ctrl is not None
            and e.num("CONTROLLER") == self.ai_ctrl
            and e.card_id not in BOB_CARD_IDS
            and e.card_id
        ):
            self.combat["opponent_hero"] = e.card_id

    def _combat_end(self, ts: str):
        c, cb = self.combat, self._cb
        if c is None:
            return
        if c["boards_pre_attack"] is None:
            # no attack happened at all -> snapshot at combat end, flagged
            if not cb["reveal_done"]:
                c["boards_at_reveal"] = self._snapshot()
            c["boards_pre_attack"] = self._snapshot()
            c["flags"]["no_attacks"] = True
        # outcome from the final hero-attack block
        ha = cb["hero_attack"] or cb["pending_ha"]
        if ha is not None:
            winner = ha["side"]  # side of the ATTACKING hero = the winner
            c["outcome"] = {
                "winner": winner,
                "damage": ha["damage"] if ha["damage"] is not None else 0,
                "basis": "hero_attack_block",
            }
        else:
            c["outcome"] = {"winner": "tie", "damage": 0, "basis": "no_hero_attack"}
        # opponent player id: the marker value that is not our own player id
        vals = [v for v in cb["marker_values"] if v > 0]
        opp = [v for v in vals if v != self.local_ctrl]
        c["opponent_player_id"] = opp[0] if opp else (vals[0] if vals else None)
        self._finalize_flags(c)
        self.combats.append(c)
        if c["animation_start_ms_after_start"] is None:
            self._await_ptl_marker = [c]
        self.combat = None
        self._cb = None

    def _finalize_flags(self, c: dict):
        b = c["boards_pre_attack"] or {"friendly": [], "enemy": []}
        unknown = sum(1 for r in b["friendly"] + b["enemy"] if not r["cardId"])
        f = c["flags"]
        f["friendly_count"] = len(b["friendly"])
        f["enemy_count"] = len(b["enemy"])
        f["unknown_card_ids"] = unknown
        f["enemy_board_recovered"] = len(b["enemy"]) > 0 and all(
            r["cardId"] for r in b["enemy"]
        )
        f["friendly_board_recovered"] = len(b["friendly"]) > 0 and all(
            r["cardId"] for r in b["friendly"]
        )
        f["pre_attack"] = not f.get("no_attacks", False)
        f["complete"] = (
            f["enemy_board_recovered"]
            and f["friendly_board_recovered"]
            and c["outcome"]["winner"] != "unknown"
        )

    # -- line handling ------------------------------------------------------
    def feed(self, raw: str, lineno: int):
        if "DebugPrint" not in raw:
            return
        m = LINE_RE.match(raw)
        if m is None:
            return
        src, ts, body = m.group("src"), m.group("ts"), m.group("body")

        # PowerTaskList: only used to timestamp the animation replay of a
        # GameState combat. Never fed into entity state. On long fights the
        # PTL replay starts BEFORE the GS block finishes streaming, so the
        # currently-open combat is a valid match target too.
        if src == "PowerTaskList":
            if "BACON_CURRENT_COMBAT_PLAYER_ID" in body and "value=0" not in body:
                target = None
                if (
                    self.combat is not None
                    and self.combat["animation_start_ms_after_start"] is None
                ):
                    target = self.combat
                elif self._await_ptl_marker:
                    target = self._await_ptl_marker.pop(0)
                if target is not None and target["animation_start_ms_after_start"] is None:
                    target["animation_start_ms_after_start"] = _ms(
                        _parse_ts(target["ts"]), _parse_ts(ts)
                    )
            return

        stripped = body.strip()

        # PlayerID=N, PlayerName=X  (from GameState.DebugPrintGame)
        pm = PLAYER_NAME_RE.match(stripped)
        if pm:
            pid, name = int(pm.group("pid")), pm.group("name")
            if name != "UNKNOWN HUMAN PLAYER" and "#" in name and self.local_ctrl is None:
                self.local_ctrl = pid
                self.local_name = name
            return

        if stripped.startswith("CREATE_GAME"):
            self._reset_game()
            self.games += 1
            return

        pm = PLAYER_RE.search(stripped)
        if pm:
            eid, pid = int(pm.group("eid")), int(pm.group("pid"))
            e = self._ent(eid)
            e.tags["CARDTYPE"] = "PLAYER"
            e.tags["PLAYER_ID"] = str(pid)
            if pm.group("hi") == "0" and pm.group("lo") == "0":
                self.ai_eid = eid
                self.ai_ctrl = pid
            elif self.local_eid is None:
                # first real account = local player (solo logs; duos partner
                # disambiguation needs the hero-draft trick, out of scope)
                self.local_eid = eid
                self.local_ctrl = pid
            return

        # indented tag continuation for a pending FULL/SHOW/CHANGE entity
        tm = TAG_LINE_RE.match(stripped)
        if tm:
            if self.pending_tags_for is not None:
                e = self.pending_tags_for
                e.tags[tm.group("tag")] = tm.group("value")
                if tm.group("tag") in ("ZONE", "CONTROLLER", "CARDTYPE"):
                    self._watch_hero_if_combat_copy(e)
            return

        if stripped.startswith("BLOCK_START"):
            self.pending_tags_for = None
            self.depth += 1
            bm = BLOCK_START_RE.match(stripped)
            if bm and bm.group("type") == "ATTACK" and self.combat is not None:
                self._note_attack(ts)
                am = ATTACK_ENT_RE.search(stripped)
                atk = self._ent_from_ref(am.group("ent")) if am else None
                if atk is not None and atk.tags.get("CARDTYPE") == "HERO":
                    side = "us" if atk.num("CONTROLLER") == self.local_ctrl else "them"
                    self._cb["pending_ha"] = {
                        "side": side,
                        "damage": None,
                        "depth": self.depth,
                    }
            return
        if stripped.startswith("BLOCK_END"):
            self.pending_tags_for = None
            self.depth = max(0, self.depth - 1)
            if self.combat is not None:
                cb = self._cb
                ha = cb.get("pending_ha")
                if ha is not None and self.depth < ha["depth"]:
                    cb["hero_attack"] = ha  # last hero attack wins
                    cb["pending_ha"] = None
                self._maybe_take_reveal_snapshot()
            return

        mm = META_DMG_RE.match(stripped)
        if mm:
            cb = self._cb
            if cb is not None and cb.get("pending_ha") and cb["pending_ha"]["damage"] is None:
                cb["pending_ha"]["damage"] = int(mm.group("data"))
            return

        fm = FULL_CREATE_RE.match(stripped)
        if fm:
            e = self._ent(int(fm.group("id")))
            e.card_id = fm.group("cardId")
            e.tags = {}
            self.pending_tags_for = e
            return
        fm = (
            FULL_UPDATE_RE.match(stripped)
            or SHOW_RE.match(stripped)
            or CHANGE_RE.match(stripped)
        )
        if fm:
            e = self._ent_from_ref(fm.group("ent"))
            if e is not None:
                if fm.group("cardId"):
                    e.card_id = fm.group("cardId")
                self.pending_tags_for = e
            return
        hm = HIDE_RE.match(stripped)
        if hm:
            e = self._ent_from_ref(hm.group("ent"))
            if e is not None:
                e.tags["ZONE"] = hm.group("zone")
            self.pending_tags_for = None
            return

        tc = TAG_CHANGE_RE.match(stripped)
        if tc:
            self.pending_tags_for = None
            ent_ref, tag, value = tc.group("ent"), tc.group("tag"), tc.group("value")

            if tag == "BACON_CURRENT_COMBAT_PLAYER_ID":
                v = int(value)
                if v > 0:
                    if self.combat is None:
                        self._combat_start(ts, lineno, v)
                    else:
                        self._cb["marker_values"].append(v)
                elif self.combat is not None:
                    self._combat_end(ts)
                return

            if tag == "TURN":
                try:
                    self.turn = int(value)
                except ValueError:
                    pass
            if ent_ref == "GameEntity":
                return
            e = self._ent_from_ref(ent_ref)
            if e is None:
                return
            e.tags[tag] = value
            if tag in ("ZONE", "CONTROLLER", "CARDTYPE"):
                self._watch_hero_if_combat_copy(e)
            # opponent display name: HERO_ENTITY set on the AI seat entity
            if self.combat is not None and tag == "HERO_ENTITY" and e.eid == self.ai_eid:
                self.combat["opponent_name"] = e.name or None
            return


def parse_log(path: str) -> dict:
    p = GameLogParser()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            p.feed(line.rstrip("\n"), i)
    return {"combats": p.combats, "games": p.games}


def summarize(combats: list[dict], min_round: int = 1) -> dict:
    sel = [c for c in combats if c["round"] >= min_round]
    n = len(sel)
    both = sum(
        1
        for c in sel
        if c["flags"]["enemy_board_recovered"] and c["flags"]["friendly_board_recovered"]
    )
    pre = sum(
        1
        for c in sel
        if c["flags"]["pre_attack"]
        and c["flags"]["enemy_board_recovered"]
        and c["flags"]["friendly_board_recovered"]
    )
    outcome = sum(1 for c in sel if c["outcome"]["winner"] in ("us", "them", "tie"))
    lead = sorted(
        c["animation_start_ms_after_start"]
        for c in sel
        if c["animation_start_ms_after_start"] is not None
    )
    fa = sorted(
        c["first_attack_ms_after_start"]
        for c in sel
        if c["first_attack_ms_after_start"] is not None
    )
    return {
        "combats": n,
        "both_boards_recovered": both,
        "both_boards_pre_attack": pre,
        "pct_both_boards_pre_attack": round(100.0 * pre / n, 1) if n else None,
        "outcome_extracted": outcome,
        "pct_outcome": round(100.0 * outcome / n, 1) if n else None,
        "median_first_attack_ms": fa[len(fa) // 2] if fa else None,
        "median_animation_lead_ms": lead[len(lead) // 2] if lead else None,
    }


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = argv[0]
    min_round = 1
    indent = None
    if "--min-round" in argv:
        min_round = int(argv[argv.index("--min-round") + 1])
    if "--indent" in argv:
        indent = 2
    res = parse_log(path)
    sel = [c for c in res["combats"] if c["round"] >= min_round]
    doc = {
        "log": path,
        "games": res["games"],
        "min_round": min_round,
        "combats": sel,
        "summary": summarize(res["combats"], min_round),
    }
    print(json.dumps(doc, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
