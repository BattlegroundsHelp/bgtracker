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
- DIVINE_SHIELD eats one instance of >0 damage (shields are counted, so a gift
  that adds charges is expressible).
- POISONOUS destroys any minion it damages; VENOMOUS is the same, consumed
  after its first kill.
- WINDFURY attacks twice (mega-windfury is approximated as two attacks).
- REBORN: after its deathrattle the minion returns once as a FRESH card -
  its printed attack and 1 health, flag consumed, respecting the 7-minion
  cap. Measured over 314 real reborn events in the logs: every buffed
  minion's copy reverted to the attack printed on the card (142 -> 4,
  95 -> 2, 27 -> 3), matching cards.json exactly. (The Persisting Horror
  Dark Gift is the documented exception - it keeps full stats.)
- Deaths are queued and deathrattles resolved in board order, attacking side
  first (true play order is not recoverable from the log; this is the
  standard approximation), with the 7-minion summon cap enforced per summon.
- Hero damage = sum of the winner's surviving minions' tavern tiers. The
  winning HERO's own tavern tier is not in the board dict - the caller adds it.

Card-script registry
--------------------
SCRIPTS maps cardId -> a dict of hooks. Recognised keys:

  "summon": [n, atk, hp, taunt, reborn, races, token_name]
        deathrattle token summon (derived from card text)
  "cleave": True
        also damages the target's neighbours
  "deathrattle_buff": {...}
        declarative "on death, buff friendly minions" - see _apply_buff
  "aura": {"deathrattle_repeats": n}
        static, rule-changing aura; ends the moment the minion dies
  "start_of_combat": fn(m, own, enemy, rng)
  "on_attack":       fn(m, target, own, enemy, rng)     this minion attacks
  "on_friendly_attack": fn(m, attacker, own, enemy, rng)
  "on_reborn":       fn(m, reborn_minion, own, enemy, rng)
  "on_summon":       fn(m, token, own, enemy, rng)
  "on_damage":       fn(m, source, own, enemy, rng)
  "on_death":        fn(m, own, enemy, rng)             imperative deathrattle
  "overkill":        True                               excess damage splashes
  "immune_attack":   True                               takes no counterattack
  "reborn_full":     True                               reborn keeps full health

Manual SCRIPTS entries beat derived ones.

What is deliberately NOT scripted, and why (measured against real logs)
----------------------------------------------------------------------
sim/boards.py snapshots both boards at the FIRST ATTACK, so anything that has
already resolved by then is ALREADY in the stats and keywords it captured.
Re-applying it here would double-count it and make the sim worse:
  * START OF COMBAT effects. Confirmed in real logs: every board holding
    Thousandth Paper Drake (BG29_810, "Start of Combat: give your left-most
    Dragon +1/+2 and Windfury") shows its left-most dragon already carrying
    the WINDFURY tag, on cards with no natural windfury.
  * Tavern "Activate", Battlecry, end-of-turn and sell/spend effects.
  * Static STAT auras - the buffed values are what the log reports.
Only rule-changing auras (Titus Rivendare) are registered, because "your
deathrattles trigger twice" cannot show up as a stat.

Derived scripts: the CURRENT Battlegrounds pool is fetched from
hearthstonejson (cached a day in .cache/simscripts.json). Every pool
deathrattle whose text matches 'Deathrattle: Summon a/two/three ... X/Y ...'
becomes a token-summon script (Taunt / Reborn on the token detected, and the
token's tribe resolved from its name); cleave text ("...minions next to...")
becomes the cleave flag; the BACON_RALLY mechanic becomes the rally flag so
"after a friendly Rally minion attacks" watchers work even next to a rally
minion we do not script. Golden variants inherit the base script with doubled
tokens unless a golden-specific entry is registered by hand.
No network and no cache -> empty scripts; the sim still runs, minions are
just vanilla stats + keywords.

Calibration
-----------
The sim models no more than it models, so it must not claim certainty it has
not earned. simulate() shrinks its raw distribution toward a neutral prior by
eps, where eps grows with the number of distinct cards on the two boards whose
text describes a combat effect we do NOT script. The raw numbers are still
returned (raw_win / raw_tie / raw_loss) - nothing is hidden.

Usage:
    python sim/engine.py                     run the inline sanity tests
    python sim/engine.py --log <Power.log> [--n 500] [--min-round N]
        predict every complete combat in a real log, score vs the outcome
API:
    simulate(board_a, board_b, n=3000, seed=None, scripts=None, calibrate=True)
      -> {"win","tie","loss","avg_damage","avg_damage_taken","n",
          "raw_win","raw_tie","raw_loss","eps","unmodelled"}
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

try:
    from paths import APP_DIR
except ImportError:          # run directly: `python sim/engine.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from paths import APP_DIR

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
# The script cache is a runtime write, so it belongs beside the exe in a frozen
# build, not inside PyInstaller's read-only bundle. See paths.py.
CACHE_DIR = APP_DIR / ".cache"
SCRIPTS_CACHE = CACHE_DIR / "simscripts.json"
CACHE_TTL = 86400
DERIVED_VERSION = 4

MAX_BOARD = 7
MAX_ATTACKS = 1000

# Calibration. The prior is deliberately SYMMETRIC - it encodes only "ties
# happen ~9% of the time" (measured over 251 real logged fights) and no
# side bias, so shrinking toward it never invents an advantage for either
# player. eps is the weight given to the prior.
PRIOR = (0.455, 0.09, 0.455)
EPS_BASE = 0.04
EPS_PER_UNMODELLED = 0.02
EPS_MAX = 0.25

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
_SUMMON_RE = re.compile(
    r"Summons? (a|an|one|two|three|four|five) (\d+)/(\d+) ([A-Za-z'’-]+)"
)
_CLEAVE_RE = re.compile(r"minions next to", re.I)

TRIBES = {
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL", "MURLOC",
    "NAGA", "PIRATE", "QUILBOAR", "UNDEAD", "ALL",
}
_TRIBE_WORD = {
    "beast": "BEAST", "demon": "DEMON", "dragon": "DRAGON",
    "elemental": "ELEMENTAL", "mech": "MECHANICAL", "murloc": "MURLOC",
    "naga": "NAGA", "pirate": "PIRATE", "quilboar": "QUILBOAR",
    "undead": "UNDEAD",
}


def _races_of(c: dict) -> list:
    r = c.get("races") or ([c["race"]] if c.get("race") else [])
    return [x for x in r if x in TRIBES]


def _token_races(noun: str, by_name: dict) -> list:
    """Tribe of a summoned token, from its name in the card text."""
    n = noun.strip()
    low = n.lower().rstrip("s")
    if low in _TRIBE_WORD:
        return [_TRIBE_WORD[low]]
    for key in (n.lower(), n.lower().rstrip("s")):
        hit = by_name.get(key)
        if hit:
            return hit
    return []


def _derive(cards: list) -> dict:
    """cards.json -> scripts / tiers / races / rally, all JSON-serializable.

    Auto-derives ONLY what the text states mechanically: deathrattle token
    summons ('Deathrattle: Summon a/two/three ... X/Y <Token>'), cleave, and
    the BACON_RALLY flag. Everything else is a manual-registry concern -
    nothing is guessed.
    """
    pool = [
        c for c in cards
        if c.get("techLevel") and c.get("isBattlegroundsPoolMinion")
    ]
    by_dbf = {c["dbfId"]: c for c in pool if c.get("dbfId")}
    by_name: dict[str, list] = {}
    for c in cards:
        if c.get("type") == "MINION" and c.get("name"):
            by_name.setdefault(c["name"].lower(), _races_of(c))
    scripts: dict[str, dict] = {}
    tiers: dict[str, int] = {}
    races: dict[str, list] = {}
    stats: dict[str, list] = {}
    for c in pool:
        tiers[c["id"]] = c["techLevel"]
        races[c["id"]] = _races_of(c)
        stats[c["id"]] = [c.get("attack") or 0, c.get("health") or 1]
        mech = c.get("mechanics") or []
        txt = _TAG_RE.sub("", c.get("text") or "").replace("\n", " ")
        entry: dict = {}
        if _CLEAVE_RE.search(txt):
            entry["cleave"] = True
        if "BACON_RALLY" in mech:
            entry["rally"] = True
        if "DEATHRATTLE" in mech and "Deathrattle:" in txt:
            dr = txt.split("Deathrattle:", 1)[1]
            m = _SUMMON_RE.search(dr)
            if m:
                end = dr.find(".", m.end())
                tail = dr[m.end(): end if end != -1 else len(dr)]
                noun = m.group(4)
                entry["summon"] = [
                    _WORD_N[m.group(1)],
                    int(m.group(2)),
                    int(m.group(3)),
                    "Taunt" in tail,
                    "Reborn" in tail,
                    _token_races(noun, by_name),
                    noun.rstrip("s"),
                ]
        if entry:
            scripts[c["id"]] = entry
    # Golden variants: same script, tokens doubled, tier and tribes inherited.
    for c in cards:
        base = by_dbf.get(c.get("battlegroundsNormalDbfId"))
        if base is None or c["id"] in tiers:
            continue
        tiers[c["id"]] = base["techLevel"]
        races[c["id"]] = races.get(base["id"], [])
        stats[c["id"]] = [c.get("attack") or 0, c.get("health") or 1]
        e = scripts.get(base["id"])
        if e:
            g = dict(e)
            g["golden"] = True  # marks token stats as already doubled
            if "summon" in g:
                s = list(g["summon"])
                s[1] *= 2
                s[2] *= 2
                g["summon"] = s
            scripts[c["id"]] = g
    return {
        "v": DERIVED_VERSION, "scripts": scripts, "tiers": tiers,
        "races": races, "stats": stats,
    }


_LOADED: dict | None = None


def load_scripts(refresh: bool = False) -> dict:
    """Derived scripts + tiers + tribes, cached a day; degrades to stale cache,
    then to empty (the sim runs scriptless) - never raises for lack of network.
    """
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
    if data is not None and data.get("v") != DERIVED_VERSION:
        data = None  # cache written by an older script format
    if data is None:
        try:
            data = _derive(_fetch(CARDS_URL))
            CACHE_DIR.mkdir(exist_ok=True)
            SCRIPTS_CACHE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            try:
                data = json.loads(SCRIPTS_CACHE.read_text(encoding="utf-8"))
                if data.get("v") != DERIVED_VERSION:
                    raise ValueError("stale cache format")
            except Exception:
                data = {"v": DERIVED_VERSION, "scripts": {}, "tiers": {},
                        "races": {}, "stats": {}}
    _LOADED = data
    return data


# ----------------------------------------------------------------- data model

class Minion:
    __slots__ = (
        "cid", "atk", "hp", "max_hp", "base_atk", "taunt", "ds", "poison",
        "venom", "wf", "reborn", "stealth", "cleave", "summon", "soc",
        "on_atk", "f_atk", "on_reborn", "on_summon", "on_dmg", "od", "dr_buff",
        "dr_rep", "overkill", "immune", "reborn_full", "rally", "races",
        "tname", "tier",
    )

    def __init__(
        self, cid: str = "", atk: int = 0, hp: int = 1, taunt: bool = False,
        ds: int = 0, poison: bool = False, venom: bool = False,
        wf: bool = False, reborn: bool = False, stealth: bool = False,
        cleave: bool = False, summon=None, soc=None, on_atk=None, od=None,
        f_atk=None, on_reborn=None, on_summon=None, on_dmg=None, dr_buff=None,
        dr_rep: int = 0, overkill: bool = False, immune: bool = False,
        reborn_full: bool = False, rally: bool = False, races=(),
        tname: str = "", tier: int = 1,
    ):
        self.cid = cid
        self.atk = atk
        self.hp = hp
        self.max_hp = hp
        self.base_atk = atk
        self.taunt = taunt
        self.ds = int(ds)
        self.poison = poison
        self.venom = venom
        self.wf = wf
        self.reborn = reborn
        self.stealth = stealth
        self.cleave = cleave
        self.summon = summon
        self.soc = soc
        self.on_atk = on_atk
        self.f_atk = f_atk
        self.on_reborn = on_reborn
        self.on_summon = on_summon
        self.on_dmg = on_dmg
        self.od = od
        self.dr_buff = dr_buff
        self.dr_rep = dr_rep
        self.overkill = overkill
        self.immune = immune
        self.reborn_full = reborn_full
        self.rally = rally
        self.races = races
        self.tname = tname
        self.tier = tier

    def clone(self) -> "Minion":
        m = Minion.__new__(Minion)
        for s in Minion.__slots__:
            setattr(m, s, getattr(self, s))
        return m

    def has_race(self, race: str) -> bool:
        return race in self.races or "ALL" in self.races


class Side:
    """One warband: minions in board order + the left-to-right attack pointer,
    plus the side-wide state that combat triggers accumulate."""

    __slots__ = ("ms", "ptr", "w_atk", "w_reborn", "w_summon", "w_dmg",
                 "w_rep", "beetle_a", "beetle_h", "undead_atk")

    def __init__(self, ms: list):
        self.ms = ms
        self.ptr = 0
        self.beetle_a = 0
        self.beetle_h = 0
        self.undead_atk = 0
        self.refresh_watchers()

    def refresh_watchers(self):
        ms = self.ms
        self.w_atk = any(m.f_atk for m in ms)
        self.w_reborn = any(m.on_reborn for m in ms)
        self.w_summon = any(m.on_summon for m in ms)
        self.w_dmg = any(m.on_dmg for m in ms)
        self.w_rep = any(m.dr_rep for m in ms)

    def dr_repeats(self) -> int:
        """How many times each of this side's deathrattles fires. A
        rule-changing aura stops the instant its minion leaves the board."""
        if not self.w_rep:
            return 1
        return 1 + sum(m.dr_rep for m in self.ms)

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


def _chain(a, b):
    if a is None:
        return b

    def both(*args):
        a(*args)
        b(*args)
    return both


_SUMMON_PAD = (False, False, (), "")


def _from_row(row: dict, reg: dict, tiers: dict, races: dict | None = None,
              stats: dict | None = None) -> Minion:
    cid = row.get("cardId") or ""
    base = _strip_golden(cid)
    golden = bool(row.get("golden"))
    sc = reg.get(cid)
    if sc is None and base != cid:
        sc = reg.get(base)
    sc = sc or {}
    races = races or {}
    # A golden minion doubles its summoned tokens - unless the entry came from
    # a golden-specific card id, whose token stats are already doubled.
    scale = 2 if (golden and sc and not sc.get("golden")) else 1
    summon = sc.get("summon")
    if summon:
        s = list(summon)
        while len(s) < 7:
            s.append(_SUMMON_PAD[len(s) - 3])
        if scale != 1:
            s[1] *= scale
            s[2] *= scale
        summon = tuple(s)
    m = Minion(
        cid=cid,
        atk=row.get("atk", 0),
        hp=row.get("health", 1) - row.get("damage", 0),
        taunt=bool(row.get("taunt")),
        ds=1 if row.get("divine_shield") else 0,
        poison=bool(row.get("poisonous")),
        venom=bool(row.get("venomous")),
        wf=bool(row.get("windfury")),
        reborn=bool(row.get("reborn")),
        stealth=bool(row.get("stealth")),
        cleave=bool(sc.get("cleave")),
        summon=summon,
        soc=sc.get("start_of_combat"),
        on_atk=sc.get("on_attack"),
        f_atk=sc.get("on_friendly_attack"),
        on_reborn=sc.get("on_reborn"),
        on_summon=sc.get("on_summon"),
        on_dmg=sc.get("on_damage"),
        od=sc.get("on_death"),
        dr_buff=sc.get("deathrattle_buff"),
        dr_rep=(sc.get("aura") or {}).get("deathrattle_repeats", 0),
        overkill=bool(sc.get("overkill")),
        immune=bool(sc.get("immune_attack")),
        reborn_full=bool(sc.get("reborn_full")),
        rally=bool(sc.get("rally")),
        races=races.get(cid) or races.get(base) or (),
        tier=tiers.get(cid) or tiers.get(base) or 1,
    )
    m.max_hp = row.get("health", 1)
    st = (stats or {}).get(cid) or (stats or {}).get(base)
    m.base_atk = st[0] if st else m.atk
    # A Dark Gift whose effect is a TRIGGER reaches the board only as a
    # reference; boards.py resolves that reference to the gift's card id.
    gift = SCRIPTS.get(row.get("dark_gift") or "")
    if gift:
        m.ds += int(gift.get("ds_charges", 0))
        if gift.get("on_death"):
            m.od = _chain(m.od, gift["on_death"])
        if gift.get("reborn"):
            m.reborn = True
        if gift.get("reborn_full"):
            m.reborn_full = True
        if gift.get("immune_attack"):
            m.immune = True
    return m


# -------------------------------------------------------------- combat engine

def _damage(dst: Minion, amount: int) -> int:
    """Plain damage from no attacker. Returns the overkill excess."""
    if amount <= 0:
        return 0
    if dst.ds:
        dst.ds -= 1
        return 0
    before = dst.hp
    dst.hp -= amount
    return amount - before if before < amount else 0


def _hit(src: Minion, dst: Minion) -> int:
    a = src.atk
    if a <= 0:
        return 0
    if dst.ds:
        dst.ds -= 1
        return 0
    before = dst.hp
    dst.hp -= a
    if (src.poison or src.venom) and dst.hp > 0:
        dst.hp = 0
    if src.venom and dst.hp <= 0:
        src.venom = False
    return a - before if before < a else 0


def _pick_defender(dside: Side, rng: random.Random) -> Minion:
    ms = dside.ms
    pool = [m for m in ms if m.taunt and not m.stealth]
    if not pool:
        pool = [m for m in ms if not m.stealth] or ms
    return pool[rng.randrange(len(pool))] if len(pool) > 1 else pool[0]


def _buff(m: Minion, atk: int, hp: int):
    m.atk += atk
    m.hp += hp
    m.max_hp += hp


def _summon(side: Side, i: int, tok: Minion, other: Side, rng: random.Random,
            trk=None) -> int:
    """Insert a summoned token, respecting the cap, and fire summon watchers."""
    if len(side.ms) >= MAX_BOARD:
        return i
    if tok.tname == "Beetle":
        _buff(tok, side.beetle_a, side.beetle_h)
    if tok.has_race("UNDEAD"):
        tok.atk += side.undead_atk
    side.insert(i, tok)
    if trk is not None:
        trk["summoned"] = trk.get("summoned", 0) + 1
    if side.w_summon:
        for w in list(side.ms):
            if w.on_summon and w.hp > 0 and w is not tok:
                w.on_summon(w, tok, side, other, rng)
    return i + 1


def _apply_buff(spec: dict, side: Side, rng: random.Random, src: Minion):
    """Declarative deathrattle_buff: pick targets, grant stats / keywords.

    spec keys: atk, hp, count (None = every match), race, card, keywords.
    """
    cands = [m for m in side.ms if m.hp > 0 and m is not src]
    race = spec.get("race")
    if race:
        cands = [m for m in cands if m.has_race(race)]
    card = spec.get("card")
    if card:
        cands = [m for m in cands if _strip_golden(m.cid) == card]
    kw = spec.get("keywords") or ()
    if "reborn" in kw:
        cands = [m for m in cands if not m.reborn]
    n = spec.get("count")
    if n is not None and len(cands) > n:
        cands = rng.sample(cands, n)
    atk, hp = spec.get("atk", 0), spec.get("hp", 0)
    for m in cands:
        if atk or hp:
            _buff(m, atk, hp)
        for k in kw:
            setattr(m, k, True)


def _deathrattle(m: Minion, side: Side, other: Side, rng: random.Random,
                 i: int, trk=None) -> int:
    """Everything one death (or one Deathstrider trigger) does."""
    if m.summon:
        cnt, t_atk, t_hp, t_taunt, t_reborn, t_races, t_name = m.summon
        for _ in range(cnt):
            if len(side.ms) >= MAX_BOARD:
                break
            i = _summon(side, i, Minion(
                cid=m.cid + "_tok", atk=t_atk, hp=t_hp, taunt=t_taunt,
                reborn=t_reborn, races=t_races, tname=t_name, tier=m.tier,
            ), other, rng, trk)
    if m.dr_buff:
        _apply_buff(m.dr_buff, side, rng, m)
    if m.od:
        m.od(m, side, other, rng)
    return i


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
                for _ in range(side.dr_repeats()):
                    i = _deathrattle(m, side, other, rng, i, trk)
                if m.reborn and len(ms) < MAX_BOARD:
                    # A Reborn copy is a FRESH card: base Attack, 1 Health.
                    # Measured over 314 real reborn events - every buffed
                    # minion's copy reverted to its printed attack (142 -> 4,
                    # 95 -> 2, 27 -> 3), matching cards.json exactly.
                    rb = m.clone()
                    if m.reborn_full:
                        rb.hp = rb.max_hp
                    else:
                        rb.hp = 1
                        rb.atk = m.base_atk
                    rb.reborn = False
                    side.insert(i, rb)
                    i += 1
                    if side.w_reborn:
                        for w in list(ms):
                            if w.on_reborn and w.hp > 0 and w is not rb:
                                w.on_reborn(w, rb, side, other, rng)
                if trk is not None and len(ms) > trk.get("max", 0):
                    trk["max"] = len(ms)


def _attack(att: Minion, aside: Side, dside: Side, rng: random.Random, trk=None):
    att.stealth = False
    for _ in range(2 if att.wf else 1):
        if att.hp <= 0 or not dside.ms:
            return
        dfn = _pick_defender(dside, rng)
        # Rally and friendly-attack watchers resolve INSIDE the attack block,
        # before damage - confirmed in real logs (the BACON_RALLY TRIGGER block
        # is nested in BlockType=ATTACK, just after PROPOSED_DEFENDER).
        triggered = False
        if att.on_atk:
            att.on_atk(att, dfn, aside, dside, rng)
            triggered = True
        if aside.w_atk:
            for w in list(aside.ms):
                if w.f_atk and w.hp > 0:
                    w.f_atk(w, att, aside, dside, rng)
            triggered = True
        if triggered:
            _resolve_deaths(aside, dside, rng, trk)
            if att.hp <= 0 or not dside.ms:
                return
            if dfn.hp <= 0 or dfn not in dside.ms:
                continue  # the rally killed the target: this swing fizzles
        di = dside.ms.index(dfn)
        if att.cleave:
            excess = 0
            victims = [dfn]
            if di > 0:
                victims.append(dside.ms[di - 1])
            if di + 1 < len(dside.ms):
                victims.append(dside.ms[di + 1])
            for v in victims:
                e = _hit(att, v)
                if v is dfn:
                    excess = e
        else:
            excess = _hit(att, dfn)
        if att.overkill and excess > 0 and dfn.hp <= 0:
            nb = []
            if di > 0:
                nb.append(dside.ms[di - 1])
            if di + 1 < len(dside.ms):
                nb.append(dside.ms[di + 1])
            if nb:
                _damage(nb[rng.randrange(len(nb))], excess)
        if not att.immune:
            _hit(dfn, att)
        if dside.w_dmg and dfn.on_dmg:
            dfn.on_dmg(dfn, att, dside, aside, rng)
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


# --------------------------------------------------------------- card scripts

def _reg(cid: str, entry: dict, golden: dict | None = None):
    """Register a manual script. The golden entry carries the numbers printed
    on the GOLDEN card, never a guessed doubling."""
    SCRIPTS[cid] = entry
    SCRIPTS[cid + "_G"] = golden if golden is not None else entry


def _others(m: Minion, side: Side) -> list:
    return [x for x in side.ms if x is not m and x.hp > 0]


def _rally_buff_others(atk: int, hp: int):
    def fn(m, target, own, enemy, rng):
        for x in _others(m, own):
            _buff(x, atk, hp)
    return fn


def _rally_self_atk(atk: int):
    def fn(m, target, own, enemy, rng):
        m.atk += atk
    return fn


def _rally_summon(n: int, atk: int, hp: int, races, name: str):
    def fn(m, target, own, enemy, rng):
        i = own.ms.index(m) + 1 if m in own.ms else len(own.ms)
        for _ in range(n):
            i = _summon(own, i, Minion(cid=m.cid + "_tok", atk=atk, hp=hp,
                                       races=races, tname=name, tier=m.tier),
                        enemy, rng)
    return fn


def _rally_race_atk(race: str, atk: int):
    def fn(m, target, own, enemy, rng):
        for x in own.ms:
            if x.has_race(race):
                x.atk += atk
        if race == "UNDEAD":
            own.undead_atk += atk
    return fn


def _rally_grant(race: str, n: int, keyword: str):
    def fn(m, target, own, enemy, rng):
        cands = [x for x in _others(m, own)
                 if x.has_race(race) and not getattr(x, keyword)]
        for x in (rng.sample(cands, n) if len(cands) > n else cands):
            setattr(x, keyword, True)
    return fn


def _ravager(both_neighbours: bool):
    """Obsidian Ravager - Rally: deal this minion's Attack to the target and
    an adjacent minion (golden: to both of its neighbours)."""
    def fn(m, target, own, enemy, rng):
        if target not in enemy.ms:
            return
        di = enemy.ms.index(target)
        nb = []
        if di > 0:
            nb.append(enemy.ms[di - 1])
        if di + 1 < len(enemy.ms):
            nb.append(enemy.ms[di + 1])
        _damage(target, m.atk)
        if not nb:
            return
        for x in (nb if both_neighbours else [nb[rng.randrange(len(nb))]]):
            _damage(x, m.atk)
    return fn


def _straight_shot(m, target, own, enemy, rng):
    target.reborn = False
    target.taunt = False


def _underdog(mult: int):
    def fn(m, target, own, enemy, rng):
        m.atk += target.atk * mult
    return fn


def _banshee(atk: int, hp: int):
    def fn(m, reborn_minion, own, enemy, rng):
        m.ds += 1
        _buff(m, atk, hp)
    return fn


def _phantom(mult: int):
    def fn(m, reborn_minion, own, enemy, rng):
        undead = [x for x in own.ms if x.has_race("UNDEAD") and x.hp > 0]
        gain = reborn_minion.atk * mult
        if undead and gain:
            _buff(undead[-1], gain, gain)
    return fn


def _eternal_knight(m, own, enemy, rng):
    """Every friendly Eternal Knight grows when one of them dies; the amount is
    printed on the RECEIVER's card, so a golden knight gains more."""
    for x in own.ms:
        if _strip_golden(x.cid) == "BG25_008" and x.hp > 0:
            if x.cid.endswith("_G"):
                _buff(x, 8, 4)
            else:
                _buff(x, 4, 2)


def _deathstrider(times: int):
    """After a friendly RALLY minion attacks, trigger the left-most friendly
    Deathrattle - without killing the minion it belongs to."""
    def fn(m, attacker, own, enemy, rng):
        if not attacker.rally:
            return
        for x in own.ms:
            if x.hp > 0 and (x.summon or x.dr_buff or x.od):
                idx = own.ms.index(x) + 1
                for _ in range(times):
                    idx = _deathrattle(x, own, enemy, rng, idx)
                return
    return fn


def _scorpid(atk: int, hp: int):
    def fn(m, attacker, own, enemy, rng):
        own.beetle_a += atk
        own.beetle_h += hp
        for x in own.ms:
            if x.tname == "Beetle":
                _buff(x, atk, hp)
    return fn


def _deflect(m, tok, own, enemy, rng):
    if tok.has_race("MECHANICAL"):
        m.atk += 2
        m.ds += 1


def _gift_golem(m, own, enemy, rng):
    """Golemancy - Deathrattle: summon a Golem with this minion's stats."""
    _summon(own, len(own.ms), Minion(
        cid="GIFT_Golem", atk=m.atk, hp=max(1, m.max_hp),
        races=["MECHANICAL"], tname="Golem", tier=m.tier), enemy, rng)


def _gift_give(stat: str):
    def fn(m, own, enemy, rng):
        cands = [x for x in own.ms if x.hp > 0]
        if not cands:
            return
        t = cands[rng.randrange(len(cands))]
        if stat == "atk":
            _buff(t, m.atk, 0)
        else:
            _buff(t, 0, m.max_hp)
    return fn


def _register_scripts():
    """The manual registry, ordered by measured error impact over real logs.
    Every value is read off the card's own text (golden values off the golden
    card's own text) - nothing is doubled by assumption."""
    # --- deathrattle buffs -------------------------------------------------
    _reg("BGS_018",  # Goldrinn - worst mean error of any card in the logs
         {"deathrattle_buff": {"atk": 8, "hp": 8, "race": "BEAST"}},
         {"deathrattle_buff": {"atk": 16, "hp": 16, "race": "BEAST"}})
    _reg("BG36_202",  # Tasty Lobster (printed value; its upgrade is not logged)
         {"deathrattle_buff": {"atk": 1, "hp": 1, "race": "BEAST", "count": 2}},
         {"deathrattle_buff": {"atk": 2, "hp": 2, "race": "BEAST", "count": 2}})
    _reg("BG28_309",  # Mummifier
         {"deathrattle_buff": {"keywords": ["reborn"], "race": "UNDEAD",
                               "count": 1}},
         {"deathrattle_buff": {"keywords": ["reborn"], "race": "UNDEAD",
                               "count": 2}})
    _reg("BG25_008", {"on_death": _eternal_knight})  # Eternal Knight
    # --- rally (on-attack, every attack) -----------------------------------
    _reg("BG29_888", {"on_attack": _rally_self_atk(2), "rally": True},
         {"on_attack": _rally_self_atk(4), "rally": True})  # Glim Guardian
    _reg("BG36_207", {"on_attack": _rally_buff_others(4, 2), "rally": True},
         {"on_attack": _rally_buff_others(8, 4), "rally": True})  # Wolf Pup
    _reg("BG36_200",  # Flittering Bat
         {"on_attack": _rally_summon(1, 1, 1, ["BEAST"], "Beast"),
          "rally": True},
         {"on_attack": _rally_summon(2, 1, 1, ["BEAST"], "Beast"),
          "rally": True})
    _reg("BG27_017", {"on_attack": _ravager(False), "rally": True},
         {"on_attack": _ravager(True), "rally": True})  # Obsidian Ravager
    _reg("BG25_016", {"on_attack": _straight_shot, "rally": True})  # Sin'dorei
    _reg("BG33_323", {"on_attack": _rally_race_atk("UNDEAD", 2), "rally": True},
         {"on_attack": _rally_race_atk("UNDEAD", 4), "rally": True})  # Dustbone
    _reg("BG34_604", {"on_attack": _underdog(1), "rally": True},
         {"on_attack": _underdog(2), "rally": True})  # Heroic Underdog
    _reg("BG33_318",  # Bile Spitter
         {"on_attack": _rally_grant("MURLOC", 1, "venom"), "rally": True},
         {"on_attack": _rally_grant("MURLOC", 2, "venom"), "rally": True})
    # --- reborn watchers ---------------------------------------------------
    _reg("BG36_514", {"on_reborn": _banshee(7, 7)},
         {"on_reborn": _banshee(14, 14)})  # Barrier Banshee
    _reg("BG36_515", {"on_reborn": _phantom(1)},
         {"on_reborn": _phantom(2)})  # Snazzy Phantom
    # --- rule-changing aura ------------------------------------------------
    _reg("BG25_354", {"aura": {"deathrattle_repeats": 1}},
         {"aura": {"deathrattle_repeats": 2}})  # Titus Rivendare
    # --- friendly-attack watchers ------------------------------------------
    _reg("BG36_208", {"on_friendly_attack": _deathstrider(1)},
         {"on_friendly_attack": _deathstrider(2)})  # Deathstrider
    _reg("BG36_209", {"on_friendly_attack": _scorpid(3, 3)},
         {"on_friendly_attack": _scorpid(6, 6)})  # Ravaging Scorpid
    # --- summon watcher / overkill -----------------------------------------
    _reg("BGS_071", {"on_summon": _deflect})  # Deflect-o-Bot
    _reg("BGS_126", {"overkill": True})  # Wildfire Elemental
    # --- Dark Gifts whose effect is a TRIGGER. Stat / keyword gifts already
    # land on the minion as ordinary tags and are captured by boards.py.
    SCRIPTS["BG36_MidGameEffect_000t61"] = {"on_death": _gift_golem}
    SCRIPTS["BG36_MidGameEffect_000t"] = {"on_death": _gift_give("atk")}
    SCRIPTS["BG36_MidGameEffect_000t2"] = {"on_death": _gift_give("hp")}
    SCRIPTS["BG36_MidGameEffect_000t12"] = {"reborn": True, "reborn_full": True}
    SCRIPTS["BG36_MidGameEffect_000t15"] = {"ds_charges": 2}
    SCRIPTS["BG36_MidGameEffect_000t60"] = {"immune_attack": True}


_register_scripts()

# Cards whose text describes a COMBAT effect we do NOT model. Their presence
# widens the odds instead of being silently ignored. Cards whose effect has
# already resolved into the snapshot (start of combat, tavern, battlecry) are
# NOT here - for those the sim is not missing anything.
UNMODELLED = frozenset({
    # Blood Gem effects: the gem's size is a hidden player enchantment.
    "BG20_101", "BG20_104", "BG33_886", "BG33_883", "BG33_430",
    "BG34_682", "BG31_320", "BG34_684",
    # Summons/gets that depend on hand contents or a random pull.
    "BG31_835", "BG34_140", "BG34_319", "BG25_009", "BG26_148", "BG25_806",
    "BG36_204", "BG36_242", "BG33_822", "BG36_331",
    # Hidden this-game counters we cannot read from a combat snapshot.
    "BG31_801", "BG_TTN_401", "BG25_011", "BG36_351", "BG33_924",
    # Spell casts and hand-targeting triggers during combat.
    "BG36_241", "BG34_925", "BG34_320", "BG29_300", "BG35_814",
    "BG26_174", "BG32_873",
})


def _count_unmodelled(rows_a: list, rows_b: list) -> int:
    seen = set()
    for r in rows_a + rows_b:
        cid = _strip_golden(r.get("cardId") or "")
        if cid in UNMODELLED:
            seen.add(cid)
    return len(seen)


# ---------------------------------------------------------------- Monte Carlo

def simulate(
    board_a: list, board_b: list, n: int = 3000, seed=None,
    scripts: dict | None = None, calibrate: bool = True,
) -> dict:
    """Monte Carlo the fight n times.

    board_a / board_b: lists of sim/boards.py minion rows (friendly = a).
    scripts: explicit registry (cardId -> entry) to use instead of the derived
    one - pass {} for a fully scriptless, offline run. When None, derived
    scripts (cached cards.json) merged under manual SCRIPTS are used.
    calibrate: shrink the result toward a neutral prior so the sim never
    reports a certainty its unmodelled cards cannot support. The raw rollout
    fractions are still returned as raw_win / raw_tie / raw_loss.
    Returns fractions plus avg hero damage on wins/losses (hero tavern tier
    NOT included - the caller adds it).
    """
    if scripts is None:
        data = load_scripts()
        reg = dict(data["scripts"])
        reg.update(SCRIPTS)
        tiers = data["tiers"]
        races = data.get("races") or {}
        stats = data.get("stats") or {}
    else:
        reg = scripts
        tiers = {}
        races = {}
        stats = {}
    ta = [_from_row(r, reg, tiers, races, stats) for r in board_a]
    tb = [_from_row(r, reg, tiers, races, stats) for r in board_b]
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
    rw, rt, rl = w / n, t / n, loss / n
    unmod = _count_unmodelled(board_a, board_b) if calibrate else 0
    eps = (
        min(EPS_MAX, EPS_BASE + EPS_PER_UNMODELLED * unmod) if calibrate else 0.0
    )
    return {
        "win": round((1 - eps) * rw + eps * PRIOR[0], 4),
        "tie": round((1 - eps) * rt + eps * PRIOR[1], 4),
        "loss": round((1 - eps) * rl + eps * PRIOR[2], 4),
        "raw_win": round(rw, 4),
        "raw_tie": round(rt, 4),
        "raw_loss": round(rl, 4),
        "eps": round(eps, 4),
        "unmodelled": unmod,
        "avg_damage": round(dmg_w / w, 2) if w else 0.0,
        "avg_damage_taken": round(dmg_l / loss, 2) if loss else 0.0,
        "n": n,
    }


def simulate_combat(combat: dict, n: int = 3000, seed=None,
                    calibrate: bool = True) -> dict:
    """Convenience: run simulate() straight off a sim/boards.py combat dict."""
    b = combat.get("boards_pre_attack") or {"friendly": [], "enemy": []}
    return simulate(b["friendly"], b["enemy"], n=n, seed=seed,
                    calibrate=calibrate)


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
    r = simulate(board, board, n=3000, seed=42, scripts={}, calibrate=False)
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
        n=500, seed=3, scripts={}, calibrate=False,
    )
    check("poison kills through 50 hp", r["win"] == 1.0, f"win {r['win']}")

    # 4. Divine shield eats exactly one hit (with-vs-without control).
    r1 = simulate([_row(10, 10, divine_shield=1)],
                  [_row(10, 10), _row(10, 10)], n=400, seed=5, scripts={},
                  calibrate=False)
    r2 = simulate([_row(10, 10)],
                  [_row(10, 10), _row(10, 10)], n=400, seed=5, scripts={},
                  calibrate=False)
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
    simulate(pa, pb, n=3000, seed=9, scripts={}, calibrate=False)
    dt = time.perf_counter() - t0
    check("perf: 7v7 x3000 rollouts < 1.5s", dt < 1.5, f"{dt:.2f}s")

    # 7. Rally fires on EVERY attack (log-confirmed), before damage.
    reg = {"R": SCRIPTS["BG36_207"]}
    own = Side([_from_row({"cardId": "R", "atk": 1, "health": 20}, reg, {}),
                _from_row(_row(1, 20), {}, {})])
    enemy = Side([_from_row(_row(0, 99), {}, {})])
    _attack(own.ms[0], own, enemy, random.Random(1))
    _attack(own.ms[0], own, enemy, random.Random(1))
    mate = own.ms[1]
    check(
        "rally fires on every attack (Wolf Pup +4/+2 twice)",
        mate.atk == 9 and mate.hp == 24,
        f"ally after 2 rally attacks: {mate.atk}/{mate.hp} (expected 9/24)",
    )

    # 8. deathrattle_buff hook: Goldrinn pumps only friendly Beasts.
    reg = {"G": SCRIPTS["BGS_018"]}
    side = Side([
        _from_row({"cardId": "G", "atk": 1, "health": 1, "damage": 1}, reg, {}),
        _from_row({"cardId": "B", "atk": 2, "health": 2}, reg, {},
                  {"B": ["BEAST"]}),
        _from_row({"cardId": "N", "atk": 2, "health": 2}, reg, {}),
    ])
    _resolve_deaths(side, Side([]), random.Random(2))
    beast, other = side.ms[0], side.ms[1]
    check(
        "deathrattle_buff: Goldrinn buffs friendly Beasts only",
        beast.atk == 10 and beast.hp == 10 and other.atk == 2,
        f"beast {beast.atk}/{beast.hp} (expected 10/10), non-beast "
        f"{other.atk}/{other.hp} (expected 2/2)",
    )

    # 9. aura hook: Titus doubles deathrattles, and stops when he is gone.
    reg = {"T": SCRIPTS["BG25_354"],
           "D": {"summon": [1, 1, 1, False, False, (), "Tok"]}}
    side = Side([
        _from_row({"cardId": "T", "atk": 1, "health": 5}, reg, {}),
        _from_row({"cardId": "D", "atk": 1, "health": 1, "damage": 1}, reg, {}),
    ])
    _resolve_deaths(side, Side([]), random.Random(3))
    with_titus = sum(1 for m in side.ms if m.cid.endswith("_tok"))
    side2 = Side([_from_row({"cardId": "D", "atk": 1, "health": 1,
                             "damage": 1}, reg, {})])
    _resolve_deaths(side2, Side([]), random.Random(3))
    without = sum(1 for m in side2.ms if m.cid.endswith("_tok"))
    check(
        "aura: Titus doubles deathrattle summons",
        with_titus == 2 and without == 1,
        f"tokens with Titus {with_titus} (expected 2), without {without} "
        f"(expected 1)",
    )

    # 10. Reborn watcher: Barrier Banshee grows on each friendly reborn.
    reg = {"BB": SCRIPTS["BG36_514"]}
    side = Side([
        _from_row({"cardId": "BB", "atk": 1, "health": 10}, reg, {}),
        _from_row({"cardId": "X", "atk": 1, "health": 1, "damage": 1,
                   "reborn": 1}, reg, {}),
    ])
    _resolve_deaths(side, Side([]), random.Random(4))
    bb = side.ms[0]
    check(
        "on_reborn: Barrier Banshee reacts to a friendly Reborn",
        bb.atk == 8 and bb.hp == 17 and bb.ds == 1,
        f"banshee {bb.atk}/{bb.hp} ds={bb.ds} (expected 8/17 ds=1)",
    )

    # 11. A Reborn copy comes back at its PRINTED attack, not its buffed one.
    stats = {"RB": [2, 1]}
    side = Side([_from_row({"cardId": "RB", "atk": 95, "health": 40,
                            "damage": 40, "reborn": 1}, {}, {}, {}, stats)])
    _resolve_deaths(side, Side([]), random.Random(8))
    rb = side.ms[0]
    check(
        "reborn returns at base attack with 1 health",
        rb.atk == 2 and rb.hp == 1 and not rb.reborn,
        f"reborn copy {rb.atk}/{rb.hp} (expected 2/1, buffed parent was 95)",
    )

    # 12. Calibration never emits a raw 0%/100% and keeps the ordering.
    r = simulate([_row(50, 50)], [_row(1, 1)], n=300, seed=6)
    check(
        "calibrated odds never claim certainty",
        r["raw_win"] == 1.0 and 0.9 < r["win"] < 1.0
        and abs(r["win"] + r["tie"] + r["loss"] - 1.0) < 1e-6,
        f"raw win {r['raw_win']} -> shown {r['win']} (tie {r['tie']}, "
        f"loss {r['loss']}, eps {r['eps']})",
    )

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
