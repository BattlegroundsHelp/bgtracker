"""Battlegrounds COMBAT simulator core - Monte Carlo over sim/boards.py boards.

Consumes the minion dicts sim/boards.py emits (boards_pre_attack["friendly"] /
["enemy"] rows: cardId / atk / health / damage / golden + keyword flags) and
estimates win / tie / loss and expected hero damage by replaying the fight
n times with randomized targeting.

Combat rules implemented:
- Alternating attacks; the side with more minions attacks first (tie: random).
- Attackers proceed left to right and wrap; 0-attack minions never attack.
- Defender is random among the enemy's minions; TAUNT (non-stealth) has
  priority; STEALTH minions cannot be targeted (stealth drops on attacking).
- Damage is simultaneous; the main target counterattacks, cleave victims don't.
- DIVINE_SHIELD eats one instance of >0 damage.
- POISONOUS destroys any minion it damages; VENOMOUS is the same, consumed
  after its first kill.
- WINDFURY attacks twice (mega-windfury is approximated as two attacks).
- REBORN: after its deathrattle the minion returns once with 1 health
  (attack as it stood; the flag is consumed), respecting the 7-minion cap.
- Deaths are queued and deathrattles resolved in board order, attacking side
  first (true play order is not recoverable from the log; this is the
  standard approximation), with the 7-minion summon cap enforced per summon.
- Hero damage = sum of the winner's surviving minions' tavern tiers. The
  winning HERO's own tavern tier is not in the board dict - the caller adds it.

Card-script registry:
- SCRIPTS: dict cardId -> hooks. Recognised keys:
    "summon": (count, atk, health, taunt)   deathrattle token summon
    "cleave": True                          also damages the target's neighbours
    "start_of_combat": fn(minion, own_side, enemy_side, rng)
    "on_attack":       fn(attacker, defender, own_side, enemy_side, rng)
    "on_death":        fn(minion, own_side, enemy_side, rng)
  Manual SCRIPTS entries beat derived ones.
- Derived scripts: the CURRENT Battlegrounds pool is fetched from
  hearthstonejson (cached a day in .cache/simscripts.json). Every pool
  deathrattle whose text matches 'Deathrattle: Summon a/two/three ... X/Y ...'
  becomes a token-summon script (with Taunt detection on the tokens); cleave
  text ("...minions next to...") becomes the cleave flag; golden variants
  (battlegroundsNormalDbfId) inherit the base script with doubled tokens.
  No network and no cache -> empty scripts; the sim still runs, minions are
  just vanilla stats + keywords.

Usage:
    python sim/engine.py                     run the inline sanity tests
    python sim/engine.py --log <Power.log> [--n 500] [--min-round N]
        predict every complete combat in a real log, score vs the outcome
API:
    simulate(board_a, board_b, n=3000, seed=None, scripts=None)
      -> {"win","tie","loss","avg_damage","avg_damage_taken","n"}
    win/tie/loss are fractions of rollouts; avg_damage is the mean tier-sum
    dealt to the enemy hero across winning rollouts (avg_damage_taken the
    mirror for losses).
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
SCRIPTS_CACHE = CACHE_DIR / "simscripts.json"
CACHE_TTL = 86400

MAX_BOARD = 7
MAX_ATTACKS = 1000

# Manual registry - entries here beat anything derived from cards.json.
SCRIPTS: dict[str, dict] = {}


# ------------------------------------------------------------- script loading

def _fetch(url: str):
    req = urllib.request.Request(
        url, headers={"Accept-Encoding": "gzip", "User-Agent": "bgtracker/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip

        raw = gzip.decompress(raw)
    return json.loads(raw)


_WORD_N = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_TAG_RE = re.compile(r"<[^>]+>")
_SUMMON_RE = re.compile(r"Summons? (a|an|one|two|three|four|five) (\d+)/(\d+)")
_CLEAVE_RE = re.compile(r"minions next to", re.I)


def _derive(cards: list) -> dict:
    """cards.json -> {"scripts": {cardId: entry}, "tiers": {cardId: techLevel}}.

    Auto-derives ONLY what the text states mechanically: deathrattle token
    summons ('Deathrattle: Summon a/two/three ... X/Y ...') and cleave.
    Everything else stays a manual-registry concern - nothing is guessed.
    """
    pool = [c for c in cards if c.get("techLevel") and c.get("isBattlegroundsPoolMinion")]
    by_dbf = {c["dbfId"]: c for c in pool if c.get("dbfId")}
    scripts: dict[str, dict] = {}
    tiers: dict[str, int] = {}
    for c in pool:
        tiers[c["id"]] = c["techLevel"]
        txt = _TAG_RE.sub("", c.get("text") or "").replace("\n", " ")
        entry: dict = {}
        if _CLEAVE_RE.search(txt):
            entry["cleave"] = True
        if "DEATHRATTLE" in (c.get("mechanics") or []) and "Deathrattle:" in txt:
            dr = txt.split("Deathrattle:", 1)[1]
            m = _SUMMON_RE.search(dr)
            if m:
                end = dr.find(".", m.end())
                tail = dr[m.end(): end if end != -1 else len(dr)]
                entry["summon"] = [
                    _WORD_N[m.group(1)],
                    int(m.group(2)),
                    int(m.group(3)),
                    "Taunt" in tail,
                ]
        if entry:
            scripts[c["id"]] = entry
    # Golden variants: same script, tokens doubled, tier inherited.
    for c in cards:
        base = by_dbf.get(c.get("battlegroundsNormalDbfId"))
        if base is None or c["id"] in tiers:
            continue
        tiers[c["id"]] = base["techLevel"]
        e = scripts.get(base["id"])
        if e:
            g = dict(e)
            g["golden"] = True  # marks token stats as already doubled
            if "summon" in g:
                s = g["summon"]
                g["summon"] = [s[0], s[1] * 2, s[2] * 2, s[3]]
            scripts[c["id"]] = g
    return {"scripts": scripts, "tiers": tiers}


_LOADED: dict | None = None


def load_scripts(refresh: bool = False) -> dict:
    """Derived scripts + tiers, cached a day; degrades to stale cache, then to
    empty (the sim runs scriptless) - never raises for lack of network."""
    global _LOADED
    if _LOADED is not None and not refresh:
        return _LOADED
    data = None
    if not refresh:
        try:
            if (
                SCRIPTS_CACHE.exists()
                and time.time() - SCRIPTS_CACHE.stat().st_mtime < CACHE_TTL
            ):
                data = json.loads(SCRIPTS_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
    if data is None:
        try:
            data = _derive(_fetch(CARDS_URL))
            CACHE_DIR.mkdir(exist_ok=True)
            SCRIPTS_CACHE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            try:
                data = json.loads(SCRIPTS_CACHE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"scripts": {}, "tiers": {}}
    _LOADED = data
    return data


# ----------------------------------------------------------------- data model

class Minion:
    __slots__ = (
        "cid", "atk", "hp", "taunt", "ds", "poison", "venom", "wf", "reborn",
        "stealth", "cleave", "summon", "soc", "on_atk", "od", "tier",
    )

    def __init__(
        self, cid: str = "", atk: int = 0, hp: int = 1, taunt: bool = False,
        ds: bool = False, poison: bool = False, venom: bool = False,
        wf: bool = False, reborn: bool = False, stealth: bool = False,
        cleave: bool = False, summon=None, soc=None, on_atk=None, od=None,
        tier: int = 1,
    ):
        self.cid = cid
        self.atk = atk
        self.hp = hp
        self.taunt = taunt
        self.ds = ds
        self.poison = poison
        self.venom = venom
        self.wf = wf
        self.reborn = reborn
        self.stealth = stealth
        self.cleave = cleave
        self.summon = summon
        self.soc = soc
        self.on_atk = on_atk
        self.od = od
        self.tier = tier

    def clone(self) -> "Minion":
        m = Minion.__new__(Minion)
        m.cid = self.cid
        m.atk = self.atk
        m.hp = self.hp
        m.taunt = self.taunt
        m.ds = self.ds
        m.poison = self.poison
        m.venom = self.venom
        m.wf = self.wf
        m.reborn = self.reborn
        m.stealth = self.stealth
        m.cleave = self.cleave
        m.summon = self.summon
        m.soc = self.soc
        m.on_atk = self.on_atk
        m.od = self.od
        m.tier = self.tier
        return m


class Side:
    """One warband: minions in board order + the left-to-right attack pointer."""

    __slots__ = ("ms", "ptr")

    def __init__(self, ms: list):
        self.ms = ms
        self.ptr = 0

    def next_attacker_idx(self) -> int:
        ms = self.ms
        n = len(ms)
        if n == 0:
            return -1
        p = self.ptr % n
        for k in range(n):
            i = p + k
            if i >= n:
                i -= n
            if ms[i].atk > 0:
                return i
        return -1

    def remove(self, i: int):
        del self.ms[i]
        if i < self.ptr:
            self.ptr -= 1

    def insert(self, i: int, m: Minion):
        self.ms.insert(i, m)
        if i < self.ptr:
            self.ptr += 1


def _strip_golden(cid: str) -> str:
    return cid[:-2] if cid.endswith("_G") else cid


def _from_row(row: dict, reg: dict, tiers: dict) -> Minion:
    cid = row.get("cardId") or ""
    base = _strip_golden(cid)
    golden = bool(row.get("golden"))
    sc = reg.get(cid)
    if sc is None and base != cid:
        sc = reg.get(base)
    sc = sc or {}
    # A golden minion doubles its summoned tokens - unless the entry came from
    # a golden-specific card id, whose token stats are already doubled.
    scale = 2 if (golden and sc and not sc.get("golden")) else 1
    summon = sc.get("summon")
    if summon and scale != 1:
        summon = (summon[0], summon[1] * scale, summon[2] * scale, summon[3])
    elif summon:
        summon = tuple(summon)
    return Minion(
        cid=cid,
        atk=row.get("atk", 0),
        hp=row.get("health", 1) - row.get("damage", 0),
        taunt=bool(row.get("taunt")),
        ds=bool(row.get("divine_shield")),
        poison=bool(row.get("poisonous")),
        venom=bool(row.get("venomous")),
        wf=bool(row.get("windfury")),
        reborn=bool(row.get("reborn")),
        stealth=bool(row.get("stealth")),
        cleave=bool(sc.get("cleave")),
        summon=summon,
        soc=sc.get("start_of_combat"),
        on_atk=sc.get("on_attack"),
        od=sc.get("on_death"),
        tier=tiers.get(cid) or tiers.get(base) or 1,
    )


# -------------------------------------------------------------- combat engine

def _hit(src: Minion, dst: Minion):
    a = src.atk
    if a <= 0:
        return
    if dst.ds:
        dst.ds = False
        return
    dst.hp -= a
    if (src.poison or src.venom) and dst.hp > 0:
        dst.hp = 0
    if src.venom and dst.hp <= 0:
        src.venom = False


def _pick_defender(dside: Side, rng: random.Random) -> Minion:
    ms = dside.ms
    pool = [m for m in ms if m.taunt and not m.stealth]
    if not pool:
        pool = [m for m in ms if not m.stealth] or ms
    return pool[rng.randrange(len(pool))] if len(pool) > 1 else pool[0]


def _resolve_deaths(first: Side, second: Side, rng: random.Random, trk=None):
    """Remove the dead, run deathrattles (queue in board order, attacking side
    first), then reborn - looping until stable. 7-minion cap on every summon."""
    changed = True
    while changed:
        changed = False
        for side, other in ((first, second), (second, first)):
            ms = side.ms
            i = 0
            while i < len(ms):
                m = ms[i]
                if m.hp > 0:
                    i += 1
                    continue
                changed = True
                side.remove(i)
                if m.summon:
                    cnt, t_atk, t_hp, t_taunt = m.summon
                    for _ in range(cnt):
                        if len(ms) >= MAX_BOARD:
                            break
                        side.insert(
                            i, Minion(cid=m.cid + "_tok", atk=t_atk, hp=t_hp,
                                      taunt=t_taunt)
                        )
                        i += 1
                        if trk is not None:
                            trk["summoned"] = trk.get("summoned", 0) + 1
                if m.od:
                    m.od(m, side, other, rng)
                if m.reborn and len(ms) < MAX_BOARD:
                    rb = m.clone()
                    rb.hp = 1
                    rb.reborn = False
                    side.insert(i, rb)
                    i += 1
                if trk is not None and len(ms) > trk.get("max", 0):
                    trk["max"] = len(ms)


def _attack(att: Minion, aside: Side, dside: Side, rng: random.Random, trk=None):
    att.stealth = False
    for _ in range(2 if att.wf else 1):
        if att.hp <= 0 or not dside.ms:
            return
        dfn = _pick_defender(dside, rng)
        if att.on_atk:
            att.on_atk(att, dfn, aside, dside, rng)
        if att.cleave:
            di = dside.ms.index(dfn)
            victims = [dfn]
            if di > 0:
                victims.append(dside.ms[di - 1])
            if di + 1 < len(dside.ms):
                victims.append(dside.ms[di + 1])
            for v in victims:
                _hit(att, v)
        else:
            _hit(att, dfn)
        _hit(dfn, att)  # simultaneous counterattack (main target only)
        _resolve_deaths(aside, dside, rng, trk)


def fight(ta: list, tb: list, rng: random.Random, trk=None) -> tuple[int, int]:
    """One full combat between two template-minion lists (templates are cloned,
    never mutated). Returns (result, damage): result +1 a wins / 0 tie / -1
    b wins; damage = tier-sum of the winner's survivors (0 on tie)."""
    a = Side([m.clone() for m in ta])
    b = Side([m.clone() for m in tb])
    if len(a.ms) != len(b.ms):
        turn = 0 if len(a.ms) > len(b.ms) else 1
    else:
        turn = rng.randrange(2)
    first, second = (a, b) if turn == 0 else (b, a)
    for side, other in ((first, second), (second, first)):
        for m in list(side.ms):
            if m.soc is not None and m.hp > 0:
                m.soc(m, side, other, rng)
    _resolve_deaths(first, second, rng, trk)
    attacks = 0
    skips = 0
    while a.ms and b.ms and attacks < MAX_ATTACKS:
        aside, dside = (a, b) if turn == 0 else (b, a)
        i = aside.next_attacker_idx()
        if i < 0:
            skips += 1
            if skips >= 2:
                break  # neither side can attack -> stalemate
            turn ^= 1
            continue
        skips = 0
        aside.ptr = i + 1
        _attack(aside.ms[i], aside, dside, rng, trk)
        attacks += 1
        turn ^= 1
    if a.ms and not b.ms:
        return 1, sum(m.tier for m in a.ms)
    if b.ms and not a.ms:
        return -1, sum(m.tier for m in b.ms)
    return 0, 0


# ---------------------------------------------------------------- Monte Carlo

def simulate(
    board_a: list, board_b: list, n: int = 3000, seed=None, scripts: dict | None = None
) -> dict:
    """Monte Carlo the fight n times.

    board_a / board_b: lists of sim/boards.py minion rows (friendly = a).
    scripts: explicit registry (cardId -> entry) to use instead of the derived
    one - pass {} for a fully scriptless, offline run. When None, derived
    scripts (cached cards.json) merged under manual SCRIPTS are used.
    Returns fractions plus avg hero damage on wins/losses (hero tavern tier
    NOT included - the caller adds it).
    """
    if scripts is None:
        data = load_scripts()
        reg = dict(data["scripts"])
        reg.update(SCRIPTS)
        tiers = data["tiers"]
    else:
        reg = scripts
        tiers = {}
    ta = [_from_row(r, reg, tiers) for r in board_a]
    tb = [_from_row(r, reg, tiers) for r in board_b]
    rng = random.Random(seed)
    w = t = loss = 0
    dmg_w = dmg_l = 0
    for _ in range(n):
        res, dmg = fight(ta, tb, rng)
        if res > 0:
            w += 1
            dmg_w += dmg
        elif res < 0:
            loss += 1
            dmg_l += dmg
        else:
            t += 1
    return {
        "win": round(w / n, 4),
        "tie": round(t / n, 4),
        "loss": round(loss / n, 4),
        "avg_damage": round(dmg_w / w, 2) if w else 0.0,
        "avg_damage_taken": round(dmg_l / loss, 2) if loss else 0.0,
        "n": n,
    }


def simulate_combat(combat: dict, n: int = 3000, seed=None) -> dict:
    """Convenience: run simulate() straight off a sim/boards.py combat dict."""
    b = combat.get("boards_pre_attack") or {"friendly": [], "enemy": []}
    return simulate(b["friendly"], b["enemy"], n=n, seed=seed)


# ------------------------------------------------------------- log validation

def _validate_log(path: str, n: int = 500, min_round: int = 1) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import boards

    res = boards.parse_log(path)
    per = []
    correct = total = 0
    for c in res["combats"]:
        if c["round"] < min_round or not c["flags"].get("complete"):
            continue
        b = c["boards_pre_attack"]
        r = simulate(b["friendly"], b["enemy"], n=n, seed=1)
        pred = max(
            (("us", r["win"]), ("them", r["loss"]), ("tie", r["tie"])),
            key=lambda kv: kv[1],
        )[0]
        actual = c["outcome"]["winner"]
        total += 1
        correct += pred == actual
        per.append({
            "game": c["game"], "round": c["round"], "pred": pred,
            "actual": actual, "win": r["win"], "tie": r["tie"],
            "loss": r["loss"],
        })
    print(json.dumps({
        "log": path,
        "rollouts_per_combat": n,
        "combats_scored": total,
        "predicted_correctly": correct,
        "accuracy_pct": round(100.0 * correct / total, 1) if total else None,
        "per_combat": per,
    }, indent=2))
    return 0


# --------------------------------------------------------------- sanity tests

def _row(atk, hp, **kw) -> dict:
    r = {"cardId": "TEST", "atk": atk, "health": hp, "damage": 0}
    r.update(kw)
    return r


def _run_tests() -> int:
    results = []

    def check(name, ok, detail):
        results.append({"test": name, "pass": bool(ok), "detail": detail})

    # 1. Mirror board -> ~50/50 among decisive rollouts.
    board = [_row(4, 3), _row(2, 6), _row(5, 4), _row(3, 3), _row(6, 2)]
    r = simulate(board, board, n=3000, seed=42, scripts={})
    dec = r["win"] + r["loss"]
    share = r["win"] / dec if dec else 0.5
    check(
        "mirror board ~50/50 (+/-5)",
        0.45 <= share <= 0.55,
        f"win {r['win']} loss {r['loss']} tie {r['tie']} -> win share of "
        f"decisive {share:.3f}",
    )

    # 2. Taunt forces targeting.
    dside = Side([
        _from_row(_row(2, 2, taunt=1), {}, {}),
        _from_row(_row(10, 2), {}, {}),
    ])
    rng = random.Random(7)
    all_taunt = all(_pick_defender(dside, rng).taunt for _ in range(300))
    check(
        "taunt forces targeting",
        all_taunt,
        "300/300 defender picks were the taunt minion" if all_taunt
        else "a non-taunt minion was picked",
    )

    # 3. Poison kills through big health.
    r = simulate(
        [_row(1, 1, poisonous=1), _row(1, 1, poisonous=1)],
        [_row(20, 50)],
        n=500, seed=3, scripts={},
    )
    check("poison kills through 50 hp", r["win"] == 1.0, f"win {r['win']}")

    # 4. Divine shield eats exactly one hit (with-vs-without control).
    r1 = simulate([_row(10, 10, divine_shield=1)],
                  [_row(10, 10), _row(10, 10)], n=400, seed=5, scripts={})
    r2 = simulate([_row(10, 10)],
                  [_row(10, 10), _row(10, 10)], n=400, seed=5, scripts={})
    check(
        "divine shield eats one hit",
        r1["tie"] == 1.0 and r2["loss"] == 1.0,
        f"with DS tie {r1['tie']} (expected 1.0), without DS loss {r2['loss']}"
        f" (expected 1.0)",
    )

    # 5a. Deathrattle summon respects the 7-minion cap (direct queue check).
    dr_reg = {"TEST_DR": {"summon": (3, 1, 1, False)}}
    side = Side(
        [_from_row({"cardId": "TEST_DR", "atk": 1, "health": 1, "damage": 1},
                   dr_reg, {})]
        + [_from_row(_row(1, 1), {}, {}) for _ in range(6)]
    )
    trk: dict = {}
    _resolve_deaths(side, Side([]), random.Random(1), trk)
    toks = sum(1 for m in side.ms if m.cid.endswith("_tok"))
    check(
        "deathrattle cap: 6 alive + summon-three -> exactly 1 token",
        len(side.ms) == 7 and toks == 1,
        f"board {len(side.ms)}/7, tokens summoned {toks} (2 of 3 lost to cap)",
    )

    # 5b. Full DR-heavy fight never exceeds 7 minions per side.
    ta = [_from_row({"cardId": "TEST_DR", "atk": 1, "health": 1, "damage": 0},
                    dr_reg, {}) for _ in range(7)]
    tb = [_from_row(_row(4, 4), {}, {}) for _ in range(7)]
    rng = random.Random(11)
    trk = {}
    for _ in range(200):
        fight(ta, tb, rng, trk)
    check(
        "deathrattle fights: board size never exceeds 7",
        trk.get("max", 0) <= 7 and trk.get("summoned", 0) > 0,
        f"max side size {trk.get('max', 0)}, tokens summoned "
        f"{trk.get('summoned', 0)} over 200 fights",
    )

    # 6. Performance: 7v7, 3000 rollouts, target < 1.5s.
    pa = [_row(4, 3), _row(2, 6, taunt=1), _row(5, 4, divine_shield=1),
          _row(3, 3), _row(6, 2), _row(3, 5, windfury=1), _row(4, 4)]
    pb = [_row(3, 4), _row(5, 3), _row(2, 7, taunt=1),
          _row(4, 4, poisonous=1), _row(6, 3), _row(3, 3, divine_shield=1),
          _row(4, 5)]
    t0 = time.perf_counter()
    simulate(pa, pb, n=3000, seed=9, scripts={})
    dt = time.perf_counter() - t0
    check("perf: 7v7 x3000 rollouts < 1.5s", dt < 1.5, f"{dt:.2f}s")

    failed = [x for x in results if not x["pass"]]
    for x in results:
        mark = "PASS" if x["pass"] else "FAIL"
        print(f"[{mark}] {x['test']}: {x['detail']}")
    print(f"{len(results) - len(failed)}/{len(results)} tests passed")
    return 1 if failed else 0


def main(argv: list) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if "--log" in argv:
        path = argv[argv.index("--log") + 1]
        n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 500
        mr = int(argv[argv.index("--min-round") + 1]) if "--min-round" in argv else 1
        return _validate_log(path, n=n, min_round=mr)
    return _run_tests()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
