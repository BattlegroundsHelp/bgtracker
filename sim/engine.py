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
  "on_friendly_death":  fn(m, dead_minion, own, enemy, rng)
  "on_reborn":       fn(m, reborn_minion, own, enemy, rng)
  "on_summon":       fn(m, token, own, enemy, rng)
  "on_damage":       fn(m, source, own, enemy, rng)
  "on_death":        fn(m, own, enemy, rng)             imperative deathrattle
  "overkill":        True | "both"    excess damage splashes one neighbour
                                      ("both": both of them - golden Wildfire)
  "immune_attack":   True                               takes no counterattack
  "reborn_full":     True                               reborn keeps full health

Manual SCRIPTS entries are laid over the derived ones PER KEY (see
merged_scripts): a hand-written hook adds to what the card's own printed text
already derived instead of erasing it, so e.g. Ravaging Scorpid keeps its
Beetle deathrattle while gaining its hand-written Rally watcher.

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
token's tribe resolved from its name); cleave text ("...minions/enemies next
to...") becomes the cleave flag; the BACON_RALLY mechanic becomes the rally flag so
"after a friendly Rally minion attacks" watchers work even next to a rally
minion we do not script. A GOLDEN variant is read off the GOLDEN card's own
text, never guessed by doubling the base: measured over the live pool, 6 of
the 8 golden deathrattle-summoners double the COUNT and keep the printed token
size ("Summon two 2/2 Beetles"), so doubling the token was wrong for all six.
Doubling the base token survives only as the fallback for the rare golden card
that carries no text of its own.
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
    simulate(board_a, board_b, n=3000, seed=None, scripts=None,
             calibrate=True, heroes=None)
      -> {"win","tie","loss","avg_damage","avg_damage_taken","n",
          "raw_win","raw_tie","raw_loss","eps","unmodelled",
          "dmg_dealt","dmg_taken","lethal","kill","raw_lethal","raw_kill"}
    win/tie/loss are fractions of rollouts; avg_damage is the mean tier-sum
    dealt to the enemy hero across winning rollouts (avg_damage_taken the
    mirror for losses).
    heroes: the snapshot's heroes dict from sim/boards.py
    ({"friendly": {tier, health, armor, damage}, "enemy": {...}}). When given,
    dmg_dealt / dmg_taken {"mean","q25","q75"} include the winning HERO's
    tavern tier (real BG face damage); lethal = P(we die this fight) and
    kill = P(they die), each widened by the same eps mixture as win/loss so
    they never print 0% or 100% on a board with unmodelled cards. Without
    heroes the dmg bands are minion-tier sums only and lethal/kill are None
    (measured 2026-08-12 over the 6 cached logs: tier and friendly health
    were present in 339/339 pre-attack snapshots, enemy health in 322 - the
    17 misses are Kel'Thuzad ghost fights where the dead owner's remaining
    health is honestly 0, so kill stays None against a ghost).
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
DERIVED_VERSION = 7

MAX_BOARD = 7
MAX_ATTACKS = 1000

# Calibration. The prior is deliberately SYMMETRIC - it encodes only "ties
# happen ~9% of the time" (7.7% - 26 of the 339 cached real fights measured;
# the wider 9% from the earlier 251-fight sample is kept on purpose) and no
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


# "six" earns its place: Cadaver Caretaker's golden prints "Summon six 1/1
# Skeletons", and without the word here the derivation missed and the
# doubled-base fallback guessed [3,2,2] instead of the printed [6,1,1].
# seven/eight cost nothing and stop the same miss on a future card.
_WORD_N = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
           "six": 6, "seven": 7, "eight": 8}
_TAG_RE = re.compile(r"<[^>]+>")
_SUMMON_RE = re.compile(
    r"Summons? (a|an|one|two|three|four|five|six|seven|eight) (\d+)/(\d+) ([A-Za-z'’-]+)"
)
# "Also damages the minions next to whomever it attacks" (Foe Reaper, Cave
# Hydra) - but the live pool's only cleave minion, Blade Collector BG26_817,
# prints "the ENEMIES next to", so matching only "minions" derived 0 cleave
# minions from the current pool.
_CLEAVE_RE = re.compile(r"(?:minions|enemies) next to", re.I)

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


def _entry_of(c: dict, by_name: dict) -> dict:
    """The script ONE card's own printed text states, and nothing else.

    Deathrattle token summons ('Deathrattle: Summon a/two/three ... X/Y
    <Token>'), cleave, and the BACON_RALLY flag. Used for base cards AND for
    golden cards, so a golden variant is always read off the golden card
    rather than inferred from its base.
    """
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
    return entry


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
        entry = _entry_of(c, by_name)
        if entry:
            scripts[c["id"]] = entry
    # Golden variants: read the GOLDEN card's own text; tier and tribes are
    # inherited from the base (goldens carry no techLevel of their own).
    for c in cards:
        base = by_dbf.get(c.get("battlegroundsNormalDbfId"))
        if base is None or c["id"] in tiers:
            continue
        tiers[c["id"]] = base["techLevel"]
        races[c["id"]] = races.get(base["id"], [])
        stats[c["id"]] = [c.get("attack") or 0, c.get("health") or 1]
        e = scripts.get(base["id"])
        own = _entry_of(c, by_name)
        if not (e or own):
            continue
        g = dict(e or {})
        g.update(own)
        g["golden"] = True  # token stats are the ones the golden card prints
        if "summon" in g and "summon" not in own:
            # Fallback ONLY for a golden card with no text of its own (rare):
            # keep the historical approximation of doubling the base token.
            s = list(g["summon"])
            s[1] *= 2
            s[2] *= 2
            g["summon"] = s
        scripts[c["id"]] = g
    # Cards we script by hand that are not in the recruitment pool (hero-power
    # tokens such as Fish of N'Zoth) still need a tier / tribe / printed stats,
    # or they count as tier 1, tribeless, and come back from Reborn wrong.
    by_id = {c["id"]: c for c in cards}
    for cid in SCRIPTS:
        if cid in tiers:
            continue
        c = by_id.get(cid)
        if not c or c.get("type") != "MINION":
            continue
        tiers[cid] = c.get("techLevel") or 1
        races[cid] = _races_of(c)
        stats[cid] = [c.get("attack") or 0, c.get("health") or 1]
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
        "cid", "atk", "hp", "max_hp", "base_atk", "base_hp", "taunt", "ds",
        "poison", "venom", "wf", "reborn", "stealth", "cleave", "summon",
        "soc", "on_atk", "f_atk", "f_death", "on_reborn", "on_summon",
        "on_dmg", "od", "dr_buff", "gained", "dr_rep", "overkill", "immune",
        "reborn_full", "rally", "races", "tname", "tier", "killer",
    )

    def __init__(
        self, cid: str = "", atk: int = 0, hp: int = 1, taunt: bool = False,
        ds: int = 0, poison: bool = False, venom: bool = False,
        wf: bool = False, reborn: bool = False, stealth: bool = False,
        cleave: bool = False, summon=None, soc=None, on_atk=None, od=None,
        f_atk=None, f_death=None, on_reborn=None, on_summon=None, on_dmg=None,
        dr_buff=None, gained=(), dr_rep: int = 0, overkill: bool = False,
        immune: bool = False, reborn_full: bool = False, rally: bool = False,
        races=(), tname: str = "", tier: int = 1,
    ):
        self.cid = cid
        self.atk = atk
        self.hp = hp
        self.max_hp = hp
        self.base_atk = atk
        self.base_hp = hp
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
        self.f_death = f_death
        self.on_reborn = on_reborn
        self.on_summon = on_summon
        self.on_dmg = on_dmg
        self.od = od
        self.dr_buff = dr_buff
        # Deathrattles this minion has GAINED during the fight (Fish of
        # N'Zoth). A tuple, and every gain rebinds it - a clone must never
        # share a mutable stack with the template it was cloned from.
        self.gained = gained
        self.dr_rep = dr_rep
        self.overkill = overkill
        self.immune = immune
        self.reborn_full = reborn_full
        self.rally = rally
        self.races = races
        self.tname = tname
        self.tier = tier
        # The minion whose hit killed this one, written by _hit when hp drops
        # to 0. Read by Leeroy the Reckless ("Destroy the minion that killed
        # this"). Plain _damage (splash, script damage) leaves it alone - the
        # game credits those kills to a minion too, but they are rare and a
        # missed destroy is the safe (under-counting) direction.
        self.killer = None

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

    __slots__ = ("ms", "ptr", "w_atk", "w_death", "w_reborn", "w_summon",
                 "w_dmg", "w_rep", "beetle_a", "beetle_h", "undead_atk",
                 "dead_mechs", "knight_deaths")

    def __init__(self, ms: list):
        self.ms = ms
        self.ptr = 0
        self.beetle_a = 0
        self.beetle_h = 0
        self.undead_atk = 0
        # Died-this-fight memories, as cheap as the counters above. dead_mechs
        # is only ever appended to by Kangor's Apprentice's watcher (capped at
        # the 4 its golden card reads); knight_deaths counts friendly Eternal
        # Knight deaths for Eternal Summoner's floor.
        self.dead_mechs = []
        self.knight_deaths = 0
        self.refresh_watchers()

    def refresh_watchers(self):
        ms = self.ms
        self.w_atk = any(m.f_atk for m in ms)
        self.w_death = any(m.f_death for m in ms)
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

# The Beetle token's own card id. A Beetle standing on the CAPTURED board
# arrives as a plain row (cardId BG28_603t, tname "") while one born during
# the fight is a script token carrying tname "Beetle" - side-wide Beetle
# buffs have to recognise both.
_BEETLE_ID = "BG28_603t"


def _is_beetle(m: Minion) -> bool:
    return m.tname == "Beetle" or _strip_golden(m.cid) == _BEETLE_ID


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
        f_death=sc.get("on_friendly_death"),
        on_reborn=sc.get("on_reborn"),
        on_summon=sc.get("on_summon"),
        on_dmg=sc.get("on_damage"),
        od=sc.get("on_death"),
        dr_buff=sc.get("deathrattle_buff"),
        dr_rep=(sc.get("aura") or {}).get("deathrattle_repeats", 0),
        overkill=sc.get("overkill") or False,
        immune=bool(sc.get("immune_attack")),
        reborn_full=bool(sc.get("reborn_full")),
        rally=bool(sc.get("rally")),
        races=races.get(cid) or races.get(base) or (),
        tier=tiers.get(cid) or tiers.get(base) or 1,
    )
    m.max_hp = row.get("health", 1)
    st = (stats or {}).get(cid) or (stats or {}).get(base)
    m.base_atk = st[0] if st else m.atk
    m.base_hp = st[1] if st else row.get("health", 1)
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
    if dst.hp <= 0:
        dst.killer = src
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
    if _is_beetle(tok):
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


def _replay(rec: tuple, m: Minion, side: Side, other: Side,
            rng: random.Random, i: int, trk=None) -> int:
    """Run ONE deathrattle - the minion's own, or one it gained (Fish of
    N'Zoth). rec = (summon, dr_buff, on_death, token tier, source cardId).
    Effects always resolve for `m`, the minion the deathrattle now belongs to,
    which is what 'gain its Deathrattle' means."""
    summon, dr_buff, od, tier, cid = rec
    if summon:
        cnt, t_atk, t_hp, t_taunt, t_reborn, t_races, t_name = summon
        for _ in range(cnt):
            if len(side.ms) >= MAX_BOARD:
                break
            i = _summon(side, i, Minion(
                cid=cid + "_tok", atk=t_atk, hp=t_hp, taunt=t_taunt,
                reborn=t_reborn, races=t_races, tname=t_name, tier=tier,
            ), other, rng, trk)
    if dr_buff:
        _apply_buff(dr_buff, side, rng, m)
    if od:
        od(m, side, other, rng)
    return i


def _deathrattle(m: Minion, side: Side, other: Side, rng: random.Random,
                 i: int, trk=None) -> int:
    """Everything one death (or one Deathstrider trigger) does: the minion's
    printed deathrattle first, then every deathrattle it gained in this fight."""
    i = _replay((m.summon, m.dr_buff, m.od, m.tier, m.cid), m, side, other,
                rng, i, trk)
    for rec in m.gained:
        i = _replay(rec, m, side, other, rng, i, trk)
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
                    rb.gained = ()  # a fresh card never carries gained ones
                    if m.reborn_full:
                        rb.hp = rb.max_hp
                    else:
                        rb.hp = 1
                        rb.atk = m.base_atk
                        # A side-wide 'your Undead have +N Attack this game,
                        # wherever they are' enchantment applies to the copy
                        # too, exactly as it does to a summoned token.
                        if side.undead_atk and rb.has_race("UNDEAD"):
                            rb.atk += side.undead_atk
                    rb.reborn = False
                    side.insert(i, rb)
                    i += 1
                    if side.w_reborn:
                        for w in list(ms):
                            if w.on_reborn and w.hp > 0 and w is not rb:
                                w.on_reborn(w, rb, side, other, rng)
                if side.w_death:
                    # 'After a DIFFERENT friendly minion dies' - m is already
                    # off the board, so identity is enough to exclude it.
                    for w in list(ms):
                        if w.f_death and w.hp > 0 and w is not m:
                            w.f_death(w, m, side, other, rng)
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
                # Base Wildfire: "deal excess damage to an adjacent enemy";
                # the golden card prints "to both adjacent enemies".
                if att.overkill == "both":
                    for v in nb:
                        _damage(v, excess)
                else:
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

def _reg(cid: str, entry: dict, golden: dict | None = None,
         gid: str | None = None):
    """Register a manual script. The golden entry carries the numbers printed
    on the GOLDEN card, never a guessed doubling.

    gid: pre-BG25 goldens live under a TB_BaconUps_* id, not <id>_G (Goldrinn
    TB_BaconUps_085, Deflect-o-Bot TB_BaconUps_123, Wildfire TB_BaconUps_166).
    Registering only <id>_G left those real logged ids scriptless. The gid
    entry is marked golden so _from_row never re-doubles a summon on it."""
    SCRIPTS[cid] = entry
    g = golden if golden is not None else entry
    SCRIPTS[cid + "_G"] = g
    if gid:
        SCRIPTS[gid] = {**g, "golden": True}


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


def _grant_race_atk(own: Side, race: str, atk: int):
    """'Your <race> have +N Attack this game (wherever they are)': every one on
    the board now, and every one that arrives later - Side.undead_atk is read
    by _summon and by the Reborn path."""
    for x in own.ms:
        if x.has_race(race):
            x.atk += atk
    if race == "UNDEAD":
        own.undead_atk += atk


def _rally_race_atk(race: str, atk: int):
    def fn(m, target, own, enemy, rng):
        _grant_race_atk(own, race, atk)
    return fn


def _dr_race_atk(race: str, atk: int):
    """The same side-wide grant on a DEATHRATTLE (Plaguerunner). The card's
    parenthetical bonus is for dying OUTSIDE combat - a minion dying in a fight
    we are simulating always takes the in-combat number."""
    def fn(m, own, enemy, rng):
        _grant_race_atk(own, race, atk)
    return fn


def _beetles_this_game(atk: int, hp: int):
    """'Your Beetles have +X/+Y this game', granted OUTSIDE combat (Forest
    Rover's Battlecry). The Beetles already on the board are carrying it in the
    captured stats, so this must NOT touch a single one of them - it only seeds
    the side counter, which _summon reads for Beetles BORN during the fight.
    Rovers already sold or dead are invisible, so the counter is a floor."""
    def fn(m, own, enemy, rng):
        own.beetle_a += atk
        own.beetle_h += hp
    return fn


def _fish(times: int):
    """Fish of N'Zoth - 'After a different friendly Deathrattle minion dies in
    combat, gain its Deathrattle.' The gained stack fires when the Fish itself
    dies (or when Deathstrider triggers it). Golden takes each gain twice, per
    the golden card's own text. Nothing is gained from a minion whose
    deathrattle we do not model - an unknown deathrattle stays unknown."""
    def fn(m, dead, own, enemy, rng):
        got = []
        if dead.summon or dead.dr_buff or dead.od:
            got.append((dead.summon, dead.dr_buff, dead.od, dead.tier,
                        dead.cid))
        got.extend(dead.gained)
        if got:
            m.gained = tuple(m.gained) + tuple(got) * times
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
    printed on the RECEIVER's card, so a golden knight gains more. The death
    also feeds Side.knight_deaths, which Eternal Summoner's floor reads."""
    own.knight_deaths += 1
    for x in own.ms:
        if _strip_golden(x.cid) == "BG25_008" and x.hp > 0:
            if x.cid.endswith("_G"):
                _buff(x, 8, 4)
            else:
                _buff(x, 4, 2)


def _eternal_summoner(golden: bool):
    """Eternal Summoner - "Deathrattle: Summon 1 Eternal Knight" (the golden
    card summons a Golden one). The knight's printed text is an aura, "+4/+2
    for each friendly Eternal Knight that died this game" (golden +8/+4), and
    the game-long death count is hidden from a combat snapshot. The knight is
    summoned at printed stats plus the deaths seen THIS FIGHT - a board-visible
    floor exactly like Forest Rover's Beetle counter - and BG25_009 stays in
    UNMODELLED so the invisible earlier deaths keep widening the odds."""
    per_a, per_h = (8, 4) if golden else (4, 2)

    def fn(m, own, enemy, rng):
        n = own.knight_deaths
        _summon(own, len(own.ms), Minion(
            cid="BG25_008_G" if golden else "BG25_008",
            atk=per_a * (1 + n), hp=per_h * (1 + n),
            races=("UNDEAD",), tname="Eternal Knight", tier=2,
            od=_eternal_knight,
        ), enemy, rng)
    return fn


def _sewer_lord(golden: bool):
    """Sewer Lord - "Deathrattle: Summon two Sewer Rats that summon 2/3
    Turtles with Taunt." (the golden card summons two GOLDEN Rats whose
    Turtles are 4/6). A nested summon: each Rat is a real token carrying the
    Rat card's own printed deathrattle (BG19_010 / BG19_010_G), so Titus,
    Fish of N'Zoth and summon watchers all see it like any other token."""
    rat_cid = "BG19_010_G" if golden else "BG19_010"
    r_atk, r_hp = (6, 4) if golden else (3, 2)
    t_sum = ((1, 4, 6, True, False, ("BEAST",), "Turtle") if golden
             else (1, 2, 3, True, False, ("BEAST",), "Turtle"))

    def fn(m, own, enemy, rng):
        for _ in range(2):
            if len(own.ms) >= MAX_BOARD:
                break
            _summon(own, len(own.ms), Minion(
                cid=rat_cid, atk=r_atk, hp=r_hp, races=("BEAST",),
                tname="Sewer Rat", tier=2, summon=t_sum,
            ), enemy, rng)
    return fn


def _kangor_watch(m, dead, own, enemy, rng):
    """Kangor's Apprentice's memory: the first Mechs that died this combat.
    Capped at the 4 the GOLDEN card reads (the base card takes the first 2 of
    them). The identity check keeps a second Apprentice's watcher from
    recording the same death twice."""
    if (dead.has_race("MECHANICAL") and len(own.dead_mechs) < 4
            and all(x is not dead for x in own.dead_mechs)):
        own.dead_mechs.append(dead)


def _kangor(count: int):
    """Kangor's Apprentice - "Deathrattle: Summon plain copies of your first
    2 Mechs that died this combat." (its golden card, TB_BaconUps_087, prints
    "first 4"). A plain copy is the printed card: printed attack and health
    (base_atk / base_hp) with no gained deathrattles. Printed KEYWORDS are not
    recoverable from the dying minion - flags are taken as they stood at its
    death, which under-counts a spent Divine Shield; the safe direction."""
    def fn(m, own, enemy, rng):
        for dead in own.dead_mechs[:count]:
            if len(own.ms) >= MAX_BOARD:
                break
            c = dead.clone()
            c.atk = c.base_atk
            c.hp = c.base_hp
            c.max_hp = c.base_hp
            c.gained = ()
            c.killer = None
            _summon(own, len(own.ms), c, enemy, rng)
    return fn


def _leeroy(m, own, enemy, rng):
    """Leeroy the Reckless - "Deathrattle: Destroy the minion that killed
    this." (the golden card prints the same effect). Destroy goes through
    Divine Shield, so the killer's hp is set to 0 directly; its own
    deathrattles still run in the normal death loop."""
    k = m.killer
    if k is not None and k.hp > 0:
        k.hp = 0


_PHALANX_TRIBES = tuple(sorted(TRIBES - {"ALL"}))


def _phalanx(atk: int, hp: int):
    """Motley Phalanx - "Deathrattle: Give a friendly minion of each type
    +2/+2 permanently." (golden +4/+4). One random friendly per tribe; an
    ALL-tribe minion can be picked once per tribe, as in the real game."""
    def fn(m, own, enemy, rng):
        for race in _PHALANX_TRIBES:
            cands = [x for x in own.ms if x.hp > 0 and x.has_race(race)]
            if cands:
                _buff(cands[rng.randrange(len(cands))], atk, hp)
    return fn


def _deathstrider(times: int):
    """After a friendly RALLY minion attacks, trigger the left-most friendly
    Deathrattle - without killing the minion it belongs to."""
    def fn(m, attacker, own, enemy, rng):
        if not attacker.rally:
            return
        for x in own.ms:
            if x.hp > 0 and (x.summon or x.dr_buff or x.od or x.gained):
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
            if _is_beetle(x):
                _buff(x, atk, hp)
    return fn


def _beetles_now(atk: int, hp: int):
    """'Your Beetles have +X/+Y this game' granted by a DEATH INSIDE the fight
    (Turquoise Skitterer): buff every Beetle on the board now and seed the
    side counter so Beetles born later in this fight carry it too. A Skitterer
    that died in an EARLIER combat already shows on the captured Beetles'
    stats, but its share of the counter for fight-born Beetles is invisible -
    same floor/ceiling split as Forest Rover, so the card stays UNMODELLED."""
    def fn(m, own, enemy, rng):
        own.beetle_a += atk
        own.beetle_h += hp
        for x in own.ms:
            if _is_beetle(x):
                _buff(x, atk, hp)
    return fn


def _deflect(atk: int):
    """Deflect-o-Bot - 'Whenever you summon a Mech during combat, gain
    +2 Attack and Divine Shield.' The golden card prints +4."""
    def fn(m, tok, own, enemy, rng):
        if tok.has_race("MECHANICAL"):
            m.atk += atk
            m.ds += 1
    return fn


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
    # Goldrinn - worst mean error of any card in the logs. "Deathrattle:
    # Your Beasts have +8/+8 until next turn."; golden card prints +16/+16.
    _reg("BGS_018",
         {"deathrattle_buff": {"atk": 8, "hp": 8, "race": "BEAST"}},
         {"deathrattle_buff": {"atk": 16, "hp": 16, "race": "BEAST"}},
         gid="TB_BaconUps_085")
    _reg("BG36_202",  # Tasty Lobster (printed value; its upgrade is not logged)
         {"deathrattle_buff": {"atk": 1, "hp": 1, "race": "BEAST", "count": 2}},
         {"deathrattle_buff": {"atk": 2, "hp": 2, "race": "BEAST", "count": 2}})
    _reg("BG28_309",  # Mummifier
         {"deathrattle_buff": {"keywords": ["reborn"], "race": "UNDEAD",
                               "count": 1}},
         {"deathrattle_buff": {"keywords": ["reborn"], "race": "UNDEAD",
                               "count": 2}})
    _reg("BG25_008", {"on_death": _eternal_knight})  # Eternal Knight
    _reg("BG25_022",  # Scarlet Skull
         {"deathrattle_buff": {"atk": 1, "hp": 2, "race": "UNDEAD",
                               "count": 1}},
         {"deathrattle_buff": {"atk": 2, "hp": 4, "race": "UNDEAD",
                               "count": 1}})
    # Showy Cyclist - "Deathrattle: Give your Naga +2/+2. (Improved by every
    # 4 spells you've cast this game!)" (golden prints +4/+4). The spell count
    # is a hidden this-game counter, so the printed number is a FLOOR - the
    # Forest Rover pattern - and BG31_925 stays in UNMODELLED for the
    # invisible improvement.
    _reg("BG31_925",
         {"deathrattle_buff": {"atk": 2, "hp": 2, "race": "NAGA"}},
         {"deathrattle_buff": {"atk": 4, "hp": 4, "race": "NAGA"}})
    # Motley Phalanx - one random friendly of each type, +2/+2 (golden +4/+4).
    _reg("BG27_080", {"on_death": _phalanx(2, 2)},
         {"on_death": _phalanx(4, 4)})
    # Plaguerunner - "Deathrattle: Your Undead have +2 Attack this game,
    # wherever they are. (+4 if triggered outside combat!)". A death INSIDE the
    # fight is the only one this sim sees, so it takes the in-combat +2; the
    # golden card prints +4 (its own +8 is likewise the outside-combat number).
    _reg("BG34_690", {"on_death": _dr_race_atk("UNDEAD", 2)},
         {"on_death": _dr_race_atk("UNDEAD", 4)})
    # --- imperative deathrattles (summons, destroys, nested tokens) ---------
    # Sewer Lord - two Rats that each rattle a Taunt Turtle; golden values are
    # the golden card's own ("two Golden Sewer Rats ... 4/6 Turtles").
    _reg("BG35_604", {"on_death": _sewer_lord(False)},
         {"on_death": _sewer_lord(True)})
    # Eternal Summoner - knight at printed stats + this fight's knight deaths
    # (floor; see _eternal_summoner). Golden card: "Summon a Golden Eternal
    # Knight."
    _reg("BG25_009", {"on_death": _eternal_summoner(False)},
         {"on_death": _eternal_summoner(True)})
    # Kangor's Apprentice - plain copies of the first 2 Mechs that died this
    # combat; its golden lives under TB_BaconUps_087 and prints "first 4".
    _reg("BGS_012",
         {"on_friendly_death": _kangor_watch, "on_death": _kangor(2)},
         {"on_friendly_death": _kangor_watch, "on_death": _kangor(4)},
         gid="TB_BaconUps_087")
    # Leeroy the Reckless - destroy the killer (golden card: same text).
    _reg("BG23_318", {"on_death": _leeroy})
    # Turquoise Skitterer - "Your Beetles have +5/+5 this game" fired by the
    # death itself (golden +10/+10); the printed Beetle summon ("a" / "two"
    # 2/2) comes from the derived script and survives the per-key merge.
    _reg("BG31_809", {"on_death": _beetles_now(5, 5)},
         {"on_death": _beetles_now(10, 10)})
    # Sly Raptor - "Summon a random Beast. Set its stats to 6/6." (golden
    # 12/12). The stats are printed; the IDENTITY is a random pull whose own
    # text we cannot know, so a vanilla Beast is the floor and BG25_806 stays
    # in UNMODELLED. The golden entry carries the golden card's own numbers,
    # hence the marker that stops _from_row re-doubling them.
    _reg("BG25_806",
         {"summon": [1, 6, 6, False, False, ["BEAST"], "Beast"]},
         {"summon": [1, 12, 12, False, False, ["BEAST"], "Beast"],
          "golden": True})
    # Auto Assembler - summons Ancestral Automaton at its PRINTED 3/4 (golden
    # card: a Golden one, 6/8). The Automaton's real stats grow with a hidden
    # this-game summon counter, so printed stats are the floor and BG32_172
    # stays in UNMODELLED beside BG_TTN_401 itself.
    _reg("BG32_172",
         {"summon": [1, 3, 4, False, False, ["MECHANICAL"], "Automaton"]},
         {"summon": [1, 6, 8, False, False, ["MECHANICAL"], "Automaton"],
          "golden": True})
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
    # --- friendly-death watcher --------------------------------------------
    # Fish of N'Zoth (a hero-power token, so its golden is TB_BaconUps_307,
    # not <id>_G - registered by its own id, with its own printed text).
    SCRIPTS["TB_BaconShop_HP_105t"] = {"on_friendly_death": _fish(1)}
    SCRIPTS["TB_BaconUps_307"] = {"on_friendly_death": _fish(2), "golden": True}
    # --- summon watcher / overkill -----------------------------------------
    # Deflect-o-Bot - "Whenever you summon a Mech during combat, gain
    # +2 Attack and Divine Shield."; the golden card prints +4.
    _reg("BGS_071", {"on_summon": _deflect(2)},
         {"on_summon": _deflect(4)}, gid="TB_BaconUps_123")
    # Wildfire Elemental - "After this attacks and kills a minion, deal
    # excess damage to an adjacent enemy."; golden: "to both adjacent enemies".
    _reg("BGS_126", {"overkill": True},
         {"overkill": "both"}, gid="TB_BaconUps_166")
    # --- 'this game' counters seeded at the start of the fight --------------
    # Forest Rover - "Battlecry: Your Beetles have +2/+1 this game" (golden
    # +4/+2). The Battlecry itself resolved in the tavern and is already in the
    # snapshot; only Beetles summoned DURING the fight are missing it. The
    # deathrattle Beetle comes from the derived script and is kept by the
    # per-key merge in merged_scripts().
    _reg("BG31_801", {"start_of_combat": _beetles_this_game(2, 1)},
         {"start_of_combat": _beetles_this_game(4, 2), "golden": True})
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
    # Blood Gems PLAYED ON BOARD MINIONS during the fight (gem size is a
    # hidden player enchantment we cannot read from the snapshot).
    "BG20_104", "BG33_886", "BG33_883", "BG33_430",
    # Summons that depend on hand contents or a random pull. BG25_009
    # (Eternal Summoner) and BG25_806 (Sly Raptor) stay here even though a
    # FLOOR is now scripted: the Summoner's knight misses the game-long
    # knight-death count and the Raptor's random Beast has text of its own.
    "BG31_835", "BG34_140", "BG25_009", "BG25_806",
    # Hidden this-game counters we cannot read from a combat snapshot.
    # BG31_801 (Forest Rover) stays here on purpose even though it is now
    # scripted: only the Rovers still ON the board can seed the Beetle
    # counter, so a Rover played and sold earlier is still unmodelled. The
    # same floor-plus-widening applies to BG31_809 (Turquoise Skitterer,
    # earlier deaths' Beetle counter share), BG31_925 (Showy Cyclist, spells
    # cast this game) and BG32_172 (Auto Assembler, whose Automaton token is
    # summoned at printed stats while its real stats grow with a hidden
    # summon counter, like BG_TTN_401 itself).
    "BG31_801", "BG_TTN_401", "BG25_011", "BG36_351",
    "BG31_809", "BG31_925", "BG32_172",
    # Spell casts and self-buffs that land on the combat board.
    "BG36_241", "BG34_925", "BG34_320", "BG35_814",
})
# Removed from UNMODELLED (their text names no effect on THIS fight's board,
# so widening the odds for them claimed less certainty than the sim earned):
#   BG20_101 Roadboar          "Rally: Get a Blood Gem" - to hand
#   BG34_682 Razorfen Flapper  "Deathrattle: Get a Blood Gem Barrage" - hand
#   BG31_320 Crater Miner      "Choose One - Get 2 Blood Gems; or ..." - hand,
#                              and it resolves when played (tavern)
#   BG34_684 Trench Fighter    "At the end of your turn ..." - tavern trigger
#   BG34_319 Highkeeper Ra     "... Get a random Tier 6 minion" - to hand
#   BG26_148 Scrap Scraper     "Deathrattle: Get a random Magnetic Mech" - hand
#   BG36_204 Headhunter Gryphon "Rally: Get a random Beast" - to hand
#   BG36_242 Bronze Timewalker "Rally: Get a random Chromadrake" - to hand
#   BG33_822 Bigwig Bandit     "Rally: Get a random Bounty" - to hand
#   BG36_331 Bramble Tunneler  "Rally: Get a random Choose One card" - hand
#   BG29_300 Winterfinner      "... give a minion in your hand +2/+1" - hand
#   BG33_924 Blue Whelp        "Tavern spells give an extra +1 Health" - tavern
#   BG26_174 Soul Rewinder     hero-damage rewind - never changes win/tie/loss
#   BG32_873 Ashen Corruptor   "give minions in the Tavern +1/+1" - tavern


def merged_scripts(data: dict | None = None) -> dict:
    """Derived scripts with the manual registry laid over them PER KEY.

    A hand-written hook must ADD to what the card's own text already derived,
    never silently erase it: replacing whole entries had dropped Ravaging
    Scorpid's printed "Deathrattle: Summon a 2/2 Beetle" the moment its Rally
    watcher was hand-written, and would drop Forest Rover's Beetle too.
    """
    data = data if data is not None else load_scripts()
    reg = dict(data.get("scripts") or {})
    for cid, entry in SCRIPTS.items():
        base = reg.get(cid)
        reg[cid] = {**base, **entry} if base else dict(entry)
    return reg


def _count_unmodelled(rows_a: list, rows_b: list) -> int:
    seen = set()
    for r in rows_a + rows_b:
        cid = _strip_golden(r.get("cardId") or "")
        if cid in UNMODELLED:
            seen.add(cid)
    return len(seen)


# ---------------------------------------------------------------- Monte Carlo

def _hero_facts(hero: dict | None) -> tuple:
    """(tavern tier, remaining life) from one snapshot hero row, each None
    when the log did not prove it. Remaining life = health - damage + armor;
    a value <= 0 is a ghost fight's dead owner, honestly unusable as a kill
    target, so it comes back None."""
    if not hero:
        return None, None
    tier = hero.get("tier") or 0
    tier = tier if 1 <= tier <= 7 else None
    hp = (hero.get("health") or 0) - (hero.get("damage") or 0) + (hero.get("armor") or 0)
    return tier, (hp if hp > 0 else None)


def _band(vals: list, extra: int) -> dict | None:
    """mean / 25th / 75th percentile of one damage sample, plus the winner's
    hero tier when known (nearest-rank quantiles; vals is unsorted)."""
    if not vals:
        return None
    vals = sorted(vals)
    k = len(vals)
    return {
        "mean": round(sum(vals) / k + extra, 2),
        "q25": vals[(k - 1) // 4] + extra,
        "q75": vals[(3 * (k - 1)) // 4] + extra,
    }


def simulate(
    board_a: list, board_b: list, n: int = 3000, seed=None,
    scripts: dict | None = None, calibrate: bool = True,
    heroes: dict | None = None,
) -> dict:
    """Monte Carlo the fight n times.

    board_a / board_b: lists of sim/boards.py minion rows (friendly = a).
    scripts: explicit registry (cardId -> entry) to use instead of the derived
    one - pass {} for a fully scriptless, offline run. When None, derived
    scripts (cached cards.json) merged under manual SCRIPTS are used.
    calibrate: shrink the result toward a neutral prior so the sim never
    reports a certainty its unmodelled cards cannot support. The raw rollout
    fractions are still returned as raw_win / raw_tie / raw_loss.
    heroes: the snapshot's heroes dict ({"friendly": {tier, health, armor,
    damage}, "enemy": {...}}) - unlocks true face damage and lethal/kill,
    see the module docstring.
    Returns fractions plus avg hero damage on wins/losses (avg_damage /
    avg_damage_taken stay minion-tier-only for compatibility - the caller
    adds the hero tier; dmg_dealt / dmg_taken already include it when heroes
    is given).
    """
    if scripts is None:
        data = load_scripts()
        reg = merged_scripts(data)
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
    dealt: list[int] = []   # minion tier-sum per WINNING rollout
    taken: list[int] = []   # minion tier-sum per LOSING rollout
    for _ in range(n):
        res, dmg = fight(ta, tb, rng)
        if res > 0:
            w += 1
            dealt.append(dmg)
        elif res < 0:
            loss += 1
            taken.append(dmg)
        else:
            t += 1
    rw, rt, rl = w / n, t / n, loss / n
    unmod = _count_unmodelled(board_a, board_b) if calibrate else 0
    eps = (
        min(EPS_MAX, EPS_BASE + EPS_PER_UNMODELLED * unmod) if calibrate else 0.0
    )
    heroes = heroes or {}
    tier_a, hp_a = _hero_facts(heroes.get("friendly"))
    tier_b, hp_b = _hero_facts(heroes.get("enemy"))
    # Real BG face damage = winner's hero tavern tier + survivors' tiers.
    # lethal ("we die") needs THEIR tier and OUR life; kill the mirror. The
    # eps mixture matches win/loss: with weight eps the fight is scored from
    # the neutral prior, under which a loss (mass PRIOR[2]) is taken to be
    # lethal half the time - so lethal can never print 0% or 100%, and by
    # construction lethal <= loss and kill <= win as shown.
    lethal = kill = raw_lethal = raw_kill = None
    if tier_b is not None and hp_a is not None:
        rlth = sum(1 for d in taken if d + tier_b >= hp_a) / n
        raw_lethal = round(rlth, 4)
        lethal = round((1 - eps) * rlth + eps * PRIOR[2] * 0.5, 4)
    if tier_a is not None and hp_b is not None:
        rk = sum(1 for d in dealt if d + tier_a >= hp_b) / n
        raw_kill = round(rk, 4)
        kill = round((1 - eps) * rk + eps * PRIOR[0] * 0.5, 4)
    return {
        "win": round((1 - eps) * rw + eps * PRIOR[0], 4),
        "tie": round((1 - eps) * rt + eps * PRIOR[1], 4),
        "loss": round((1 - eps) * rl + eps * PRIOR[2], 4),
        "raw_win": round(rw, 4),
        "raw_tie": round(rt, 4),
        "raw_loss": round(rl, 4),
        "eps": round(eps, 4),
        "unmodelled": unmod,
        "avg_damage": round(sum(dealt) / w, 2) if w else 0.0,
        "avg_damage_taken": round(sum(taken) / loss, 2) if loss else 0.0,
        "dmg_dealt": _band(dealt, tier_a or 0),
        "dmg_taken": _band(taken, tier_b or 0),
        "lethal": lethal,
        "kill": kill,
        "raw_lethal": raw_lethal,
        "raw_kill": raw_kill,
        "n": n,
    }


def simulate_combat(combat: dict, n: int = 3000, seed=None,
                    calibrate: bool = True) -> dict:
    """Convenience: run simulate() straight off a sim/boards.py combat dict."""
    b = combat.get("boards_pre_attack") or {"friendly": [], "enemy": []}
    return simulate(b["friendly"], b["enemy"], n=n, seed=seed,
                    calibrate=calibrate, heroes=b.get("heroes"))


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

    # 13. Deathrattle side-wide race grant (Plaguerunner): every Undead on the
    #     board AND every Undead summoned afterwards, no one else.
    reg = {"P": SCRIPTS["BG34_690"], "PG": SCRIPTS["BG34_690_G"],
           "S": {"summon": [1, 1, 1, False, False, ["UNDEAD"], "Tok"]}}
    races = {"U": ["UNDEAD"], "N": [], "S": ["UNDEAD"]}
    side = Side([
        _from_row({"cardId": "P", "atk": 4, "health": 2, "damage": 2}, reg, {}),
        _from_row({"cardId": "S", "atk": 1, "health": 1, "damage": 1}, reg, {},
                  races),
        _from_row({"cardId": "U", "atk": 2, "health": 2}, reg, {}, races),
        _from_row({"cardId": "N", "atk": 2, "health": 2}, reg, {}, races),
    ])
    _resolve_deaths(side, Side([]), random.Random(5))
    tok = [m for m in side.ms if m.cid.endswith("_tok")]
    undead = [m for m in side.ms if m.cid == "U"][0]
    plain = [m for m in side.ms if m.cid == "N"][0]
    gside = Side([
        _from_row({"cardId": "PG", "atk": 8, "health": 4, "damage": 4}, reg, {}),
        _from_row({"cardId": "U", "atk": 2, "health": 2}, reg, {}, races),
    ])
    _resolve_deaths(gside, Side([]), random.Random(5))
    check(
        "deathrattle race grant: Plaguerunner +2 to Undead here and later",
        undead.atk == 4 and plain.atk == 2 and len(tok) == 1
        and tok[0].atk == 3 and side.undead_atk == 2
        and gside.ms[0].atk == 6,
        f"board Undead {undead.atk} (expected 4), non-Undead {plain.atk} "
        f"(expected 2), Undead token summoned after the death "
        f"{tok[0].atk if tok else None} (expected 3), golden board Undead "
        f"{gside.ms[0].atk} (expected 6)",
    )

    # 13b. A Reborn Undead copy carries the same side-wide grant.
    reg2 = {"P": SCRIPTS["BG34_690"]}
    side = Side([
        _from_row({"cardId": "P", "atk": 4, "health": 2, "damage": 2}, reg2, {}),
        _from_row({"cardId": "U", "atk": 9, "health": 1, "damage": 1,
                   "reborn": 1}, reg2, {}, {"U": ["UNDEAD"]}, {"U": [3, 5]}),
    ])
    _resolve_deaths(side, Side([]), random.Random(5))
    rb = [m for m in side.ms if m.cid == "U"][0]
    check(
        "reborn Undead copy gets the side-wide grant (base 3 +2)",
        rb.atk == 5 and rb.hp == 1,
        f"reborn copy {rb.atk}/{rb.hp} (expected 5/1: printed 3 plus the +2)",
    )

    # 14. Friendly-death watcher (Fish of N'Zoth): gains a dead friend's
    #     deathrattle, fires it on its own death, ignores a vanilla death.
    reg = {"F": SCRIPTS["TB_BaconShop_HP_105t"],
           "FG": SCRIPTS["TB_BaconUps_307"],
           "D": {"summon": [1, 1, 1, False, False, (), "Tok"]}}

    def fish_run(fish_cid):
        s = Side([
            _from_row({"cardId": fish_cid, "atk": 2, "health": 2}, reg, {}),
            _from_row({"cardId": "V", "atk": 1, "health": 1, "damage": 1},
                      reg, {}),
            _from_row({"cardId": "D", "atk": 1, "health": 1, "damage": 1},
                      reg, {}),
        ])
        _resolve_deaths(s, Side([]), random.Random(6))
        f = [m for m in s.ms if m.cid == fish_cid][0]
        after_friend = sum(1 for m in s.ms if m.cid.endswith("_tok"))
        f.hp = 0
        _resolve_deaths(s, Side([]), random.Random(6))
        return len(f.gained), after_friend, sum(
            1 for m in s.ms if m.cid.endswith("_tok"))

    g1, t1, t1b = fish_run("F")
    g2, t2, t2b = fish_run("FG")
    solo = Side([_from_row({"cardId": "F", "atk": 2, "health": 2}, reg, {})])
    solo.ms[0].hp = 0
    _resolve_deaths(solo, Side([]), random.Random(6))
    check(
        "on_friendly_death: Fish of N'Zoth gains and replays a deathrattle",
        (g1, t1, t1b) == (1, 1, 2) and (g2, t2, t2b) == (2, 1, 3)
        and not solo.ms,
        f"base gained {g1} (expected 1), tokens {t1}->{t1b} (expected 1->2); "
        f"golden gained {g2} (expected 2), tokens {t2}->{t2b} (expected 1->3); "
        f"a vanilla death granted nothing, a lone Fish summoned nothing",
    )

    # 14b. The gained stack must never leak out of a rollout into the template.
    fish_row = {"cardId": "F", "atk": 2, "health": 20}
    dr_row = {"cardId": "D", "atk": 1, "health": 1}
    ta = [_from_row(fish_row, reg, {}), _from_row(dr_row, reg, {})]
    tb = [_from_row(_row(3, 3), {}, {}) for _ in range(2)]
    rng = random.Random(12)
    trk = {}
    for _ in range(50):
        fight(ta, tb, rng, trk)
    r1 = simulate([fish_row, dr_row], [_row(3, 3)], n=60, seed=4, scripts=reg,
                  calibrate=False)
    r2 = simulate([fish_row, dr_row], [_row(3, 3)], n=60, seed=4, scripts=reg,
                  calibrate=False)
    check(
        "gained deathrattles never leak across rollouts",
        ta[0].gained == () and trk.get("max", 0) <= 7 and r1 == r2,
        f"template stack after 50 fights {len(ta[0].gained)} (expected 0), "
        f"max board {trk.get('max', 0)}, two identical seeded runs equal "
        f"{r1 == r2}",
    )

    # 15. 'This game' Beetle counter (Forest Rover): seeds the counter for
    #     Beetles born in the fight and touches NOTHING already on the board -
    #     the Battlecry is already inside the captured stats.
    fr = dict(SCRIPTS["BG31_801"])
    fr["summon"] = [1, 2, 2, False, False, ["BEAST"], "Beetle"]
    frg = dict(SCRIPTS["BG31_801_G"])
    frg["summon"] = [2, 2, 2, False, False, ["BEAST"], "Beetle"]
    reg = {"FR": fr, "FRG": frg}

    def rover_run(cid):
        s = Side([
            _from_row({"cardId": cid, "atk": 1, "health": 1, "damage": 1},
                      reg, {}),
            _from_row({"cardId": "OLD", "atk": 2, "health": 2}, reg, {}),
        ])
        other = Side([])
        rr = random.Random(2)
        for m in list(s.ms):
            if m.soc is not None:
                m.soc(m, s, other, rr)
        untouched = (s.ms[1].atk, s.ms[1].hp)
        _resolve_deaths(s, other, rr)
        beetles = [m for m in s.ms if m.tname == "Beetle"]
        return (s.beetle_a, s.beetle_h), untouched, [(b.atk, b.hp)
                                                     for b in beetles]

    c1, u1, b1 = rover_run("FR")
    c2, u2, b2 = rover_run("FRG")
    check(
        "this-game Beetle counter: new Beetles buffed, board left alone",
        c1 == (2, 1) and u1 == (2, 2) and b1 == [(4, 3)]
        and c2 == (4, 2) and u2 == (2, 2) and b2 == [(6, 4), (6, 4)],
        f"base counter {c1} beetles {b1} (expected (2,1) [(4,3)]), golden "
        f"counter {c2} beetles {b2} (expected (4,2) two (6,4)); the minion "
        f"already on the board stayed {u1} / {u2} (expected (2,2))",
    )

    # 16. A golden script is read off the GOLDEN card's own text. Six of the
    #     eight golden deathrattle-summoners in the live pool double the COUNT
    #     and keep the printed token size, so doubling the token was wrong.
    fake = [
        {"id": "T_B", "dbfId": 1, "name": "Tester", "type": "MINION",
         "techLevel": 2, "isBattlegroundsPoolMinion": True, "attack": 1,
         "health": 1, "races": ["BEAST"], "mechanics": ["DEATHRATTLE"],
         "text": "<b>Deathrattle:</b> Summon a 2/2 Beetle."},
        {"id": "T_B_G", "dbfId": 2, "name": "Tester", "type": "MINION",
         "attack": 2, "health": 2, "races": ["BEAST"],
         "battlegroundsNormalDbfId": 1, "mechanics": ["DEATHRATTLE"],
         "text": "<b>Deathrattle:</b> Summon two 2/2 Beetles."},
        {"id": "T_S", "dbfId": 3, "name": "Silent", "type": "MINION",
         "techLevel": 3, "isBattlegroundsPoolMinion": True, "attack": 1,
         "health": 1, "races": [], "mechanics": ["DEATHRATTLE"],
         "text": "<b>Deathrattle:</b> Summon a 1/1 Imp."},
        {"id": "T_S_G", "dbfId": 4, "name": "Silent", "type": "MINION",
         "attack": 2, "health": 2, "races": [],
         "battlegroundsNormalDbfId": 3, "mechanics": ["DEATHRATTLE"]},
    ]
    d = _derive(fake)
    gs = d["scripts"]["T_B_G"]["summon"]
    fb = d["scripts"]["T_S_G"]["summon"]
    check(
        "golden scripts come from the golden card's own text",
        gs[:3] == [2, 2, 2] and fb[:3] == [1, 2, 2]
        and d["tiers"]["T_B_G"] == 2 and d["stats"]["T_B_G"] == [2, 2],
        f"'Summon two 2/2 Beetles' -> {gs[:3]} (expected [2, 2, 2], NOT "
        f"[1, 4, 4]); a textless golden still falls back to the doubled "
        f"token {fb[:3]} (expected [1, 2, 2])",
    )

    # 16b. Count words above five parse. Cadaver Caretaker's golden prints
    # "Summon six 1/1 Skeletons"; before "six" entered _WORD_N the derivation
    # missed and the doubled-base fallback guessed [3,2,2].
    six = _derive([
        {"id": "T_C", "dbfId": 5, "name": "Caretaker", "type": "MINION",
         "techLevel": 3, "isBattlegroundsPoolMinion": True, "attack": 2,
         "health": 2, "races": ["UNDEAD"], "mechanics": ["DEATHRATTLE"],
         "text": "<b>Deathrattle:</b> Summon three 1/1 Skeletons."},
        {"id": "T_C_G", "dbfId": 6, "name": "Caretaker", "type": "MINION",
         "attack": 4, "health": 4, "races": ["UNDEAD"],
         "battlegroundsNormalDbfId": 5, "mechanics": ["DEATHRATTLE"],
         "text": "<b>Deathrattle:</b> Summon six 1/1 Skeletons."},
    ])["scripts"]["T_C_G"]["summon"]
    check(
        "count words above five derive from the printed text",
        six[:3] == [6, 1, 1],
        f"'Summon six 1/1 Skeletons' -> {six[:3]} (expected [6, 1, 1], "
        f"NOT the doubled-base [3, 2, 2])",
    )

    # 17. A manual entry adds to the derived one instead of erasing it.
    fake_data = {"scripts": {
        "BG36_209": {"summon": [1, 2, 2, False, False, ["BEAST"], "Beetle"]},
        "BG31_801": {"summon": [1, 2, 2, False, False, ["BEAST"], "Beetle"]},
    }}
    merged = merged_scripts(fake_data)
    check(
        "manual scripts merge over derived, never replace them",
        "summon" in merged["BG36_209"]
        and "on_friendly_attack" in merged["BG36_209"]
        and "summon" in merged["BG31_801"]
        and "start_of_combat" in merged["BG31_801"],
        "Ravaging Scorpid keeps its Beetle deathrattle beside its Rally hook, "
        "Forest Rover keeps its Beetle beside the this-game counter",
    )

    # 18. Cleave derives from BOTH printed wordings - Blade Collector says
    #     "the enemies next to", the older cards say "the minions next to".
    fake_cleave = [
        {"id": "T_C1", "dbfId": 10, "name": "Collector", "type": "MINION",
         "techLevel": 4, "isBattlegroundsPoolMinion": True, "attack": 5,
         "health": 4, "races": [], "mechanics": [],
         "text": "Also damages the enemies next to whomever this attacks."},
        {"id": "T_C2", "dbfId": 11, "name": "Hydra", "type": "MINION",
         "techLevel": 4, "isBattlegroundsPoolMinion": True, "attack": 2,
         "health": 4, "races": ["BEAST"], "mechanics": [],
         "text": "Also damages the minions next to whomever this attacks."},
    ]
    dc = _derive(fake_cleave)["scripts"]
    check(
        "cleave regex matches 'enemies next to' and 'minions next to'",
        dc.get("T_C1", {}).get("cleave") and dc.get("T_C2", {}).get("cleave"),
        f"Collector wording -> {dc.get('T_C1')}, Hydra wording -> "
        f"{dc.get('T_C2')} (both expected cleave)",
    )

    # 19. Pre-BG25 goldens resolve under their real TB_BaconUps_* ids, with
    #     the GOLDEN card's own numbers (Deflect golden gains +4, not +2).
    reg = {"DG": SCRIPTS["TB_BaconUps_123"],
           "S": {"summon": [1, 1, 1, False, False, ["MECHANICAL"], "Bot"]}}
    side = Side([
        _from_row({"cardId": "DG", "atk": 6, "health": 4, "golden": True},
                  reg, {}),
        _from_row({"cardId": "S", "atk": 1, "health": 1, "damage": 1},
                  reg, {}),
    ])
    _resolve_deaths(side, Side([]), random.Random(9))
    dbot = side.ms[0]
    ids_ok = all(k in SCRIPTS for k in
                 ("TB_BaconUps_085", "TB_BaconUps_123", "TB_BaconUps_166"))
    g085 = SCRIPTS["TB_BaconUps_085"].get("deathrattle_buff", {})
    check(
        "TB_BaconUps golden ids resolve with the golden card's numbers",
        ids_ok and dbot.atk == 10 and dbot.ds == 1
        and g085.get("atk") == 16 and g085.get("hp") == 16,
        f"ids registered {ids_ok}; golden Deflect after 1 Mech summon "
        f"{dbot.atk} atk / {dbot.ds} ds (expected 10/1); golden Goldrinn "
        f"buff {g085} (expected 16/16)",
    )

    # 20. Overkill: base Wildfire splashes ONE neighbour, the golden card
    #     ("to both adjacent enemies") splashes both.
    def wildfire_run(cid, sc):
        aside = Side([_from_row({"cardId": cid, "atk": 10, "health": 99},
                                {cid: sc}, {})])
        dside = Side([_from_row(_row(0, 9), {}, {}),
                      _from_row(_row(0, 2), {}, {}),
                      _from_row(_row(0, 9), {}, {})])
        # force the middle 0/2 minion to be the defender: kill = 8 excess
        dside.ms[0].stealth = True
        dside.ms[2].stealth = True
        _attack(aside.ms[0], aside, dside, random.Random(10))
        return sorted(m.hp for m in dside.ms)

    base_hp = wildfire_run("WF", SCRIPTS["BGS_126"])
    gold_hp = wildfire_run("WFG", SCRIPTS["TB_BaconUps_166"])
    check(
        "overkill: base splashes one neighbour, golden both",
        base_hp == [1, 9] and gold_hp == [1, 1],
        f"survivor hp after base overkill {base_hp} (expected [1, 9]), "
        f"after golden {gold_hp} (expected [1, 1])",
    )

    # 21. Kangor's Apprentice: plain copies of the first N Mechs that died -
    #     printed stats, buffs stripped, non-Mech deaths ignored; base takes
    #     2, the golden (TB_BaconUps_087) takes 4.
    kreg = {"K": SCRIPTS["BGS_012"], "KG": SCRIPTS["TB_BaconUps_087"]}
    kraces = {"M1": ["MECHANICAL"], "M2": ["MECHANICAL"],
              "M3": ["MECHANICAL"], "M4": ["MECHANICAL"]}
    kstats = {"M1": [2, 3], "M2": [4, 5], "M3": [1, 1], "M4": [1, 1]}

    def kangor_run(cid):
        s = Side(
            [_from_row({"cardId": cid, "atk": 3, "health": 6}, kreg, {})]
            + [_from_row({"cardId": f"M{i}", "atk": 10, "health": 10,
                          "damage": 10}, kreg, {}, kraces, kstats)
               for i in (1, 2, 3, 4)]
            + [_from_row({"cardId": "N", "atk": 5, "health": 5, "damage": 5},
                         kreg, {})]
        )
        _resolve_deaths(s, Side([]), random.Random(13))
        recorded = len(s.dead_mechs)
        s.ms[0].hp = 0
        _resolve_deaths(s, Side([]), random.Random(13))
        return recorded, [(m.cid, m.atk, m.hp) for m in s.ms]

    rec_b, copies_b = kangor_run("K")
    rec_g, copies_g = kangor_run("KG")
    check(
        "Kangor's Apprentice: plain copies of the first dead Mechs",
        rec_b == 4 and copies_b == [("M1", 2, 3), ("M2", 4, 5)]
        and copies_g == [("M1", 2, 3), ("M2", 4, 5), ("M3", 1, 1),
                         ("M4", 1, 1)],
        f"memory held {rec_b} Mechs (expected 4, non-Mech skipped); base "
        f"summoned {copies_b} (expected printed M1 2/3 and M2 4/5, buffed "
        f"10/10 stripped); golden summoned {len(copies_g)} (expected 4)",
    )

    # 22. Sewer Lord: nested summon - Rats that rattle Taunt Turtles, golden
    #     values off the golden card's own text.
    def sewer_run(cid):
        s = Side([_from_row({"cardId": cid, "atk": 4, "health": 6,
                             "damage": 6}, {cid: SCRIPTS[cid]}, {})])
        _resolve_deaths(s, Side([]), random.Random(14))
        rats = [(m.atk, m.hp) for m in s.ms]
        for m in s.ms:
            m.hp = 0
        _resolve_deaths(s, Side([]), random.Random(14))
        return rats, [(m.atk, m.hp, m.taunt, m.tname) for m in s.ms]

    rats_b, turt_b = sewer_run("BG35_604")
    rats_g, turt_g = sewer_run("BG35_604_G")
    check(
        "Sewer Lord: two Rats, each rattling a Taunt Turtle",
        rats_b == [(3, 2), (3, 2)]
        and turt_b == [(2, 3, True, "Turtle"), (2, 3, True, "Turtle")]
        and rats_g == [(6, 4), (6, 4)]
        and turt_g == [(4, 6, True, "Turtle"), (4, 6, True, "Turtle")],
        f"base rats {rats_b} -> turtles {turt_b} (expected two 3/2 -> two "
        f"2/3 Taunt); golden rats {rats_g} -> turtles {turt_g} (expected "
        f"two 6/4 -> two 4/6 Taunt)",
    )

    # 23. Eternal Summoner floor: the knight lands at printed stats plus this
    #     fight's knight deaths; the golden summoner makes a Golden knight.
    ereg = {"EK": SCRIPTS["BG25_008"], "ES": SCRIPTS["BG25_009"],
            "ESG": SCRIPTS["BG25_009_G"]}
    s = Side([
        _from_row({"cardId": "BG25_008", "atk": 4, "health": 2, "damage": 2},
                  {"BG25_008": SCRIPTS["BG25_008"]}, {}),
        _from_row({"cardId": "ES", "atk": 8, "health": 1, "damage": 1},
                  ereg, {}),
    ])
    _resolve_deaths(s, Side([]), random.Random(15))
    knight = s.ms[0]
    sg = Side([_from_row({"cardId": "ESG", "atk": 16, "health": 2,
                          "damage": 2}, ereg, {})])
    _resolve_deaths(sg, Side([]), random.Random(15))
    gknight = sg.ms[0]
    check(
        "Eternal Summoner: knight floor counts this fight's knight deaths",
        (knight.cid, knight.atk, knight.hp) == ("BG25_008", 8, 4)
        and s.knight_deaths == 1
        and (gknight.cid, gknight.atk, gknight.hp) == ("BG25_008_G", 8, 4),
        f"after one knight death the summoned knight is {knight.atk}/"
        f"{knight.hp} (expected 8/4: printed 4/2 + 4/2), knight_deaths "
        f"{s.knight_deaths} (expected 1); golden summoner made "
        f"{gknight.cid} {gknight.atk}/{gknight.hp} (expected 8/4)",
    )

    # 24. Leeroy the Reckless: the minion that lands the killing hit is
    #     destroyed, straight through its remaining health.
    lreg = {"L": SCRIPTS["BG23_318"]}
    aside = Side([_from_row({"cardId": "A", "atk": 3, "health": 20}, {}, {})])
    dside = Side([_from_row({"cardId": "L", "atk": 6, "health": 2},
                            lreg, {})])
    _attack(aside.ms[0], aside, dside, random.Random(16))
    check(
        "Leeroy: destroys the minion that killed it",
        not dside.ms and not aside.ms,
        f"boards after the trade: attacker side {len(aside.ms)} (expected 0 -"
        f" 17 hp left but destroyed), Leeroy side {len(dside.ms)} (expected 0)",
    )

    # 25. Turquoise Skitterer: board Beetles (captured rows, cid BG28_603t)
    #     and the freshly rattled token all get the this-game +5/+5, and the
    #     side counter is seeded for Beetles born later.
    ts = dict(SCRIPTS["BG31_809"])
    ts["summon"] = [1, 2, 2, False, False, ["BEAST"], "Beetle"]
    tsg = dict(SCRIPTS["BG31_809_G"])
    tsg["summon"] = [2, 2, 2, False, False, ["BEAST"], "Beetle"]
    tsg["golden"] = True
    treg = {"TS": ts, "TSG": tsg}

    def skitter_run(cid):
        s = Side([
            _from_row({"cardId": cid, "atk": 5, "health": 5, "damage": 5},
                      treg, {}),
            _from_row({"cardId": "BG28_603t", "atk": 2, "health": 2},
                      treg, {}),
        ])
        _resolve_deaths(s, Side([]), random.Random(17))
        return (s.beetle_a, s.beetle_h), sorted(
            (m.atk, m.hp) for m in s.ms)

    cnt_b, bees_b = skitter_run("TS")
    cnt_g, bees_g = skitter_run("TSG")
    check(
        "Turquoise Skitterer: +5/+5 to every Beetle, counter seeded",
        cnt_b == (5, 5) and bees_b == [(7, 7), (7, 7)]
        and cnt_g == (10, 10) and bees_g == [(12, 12), (12, 12), (12, 12)],
        f"base counter {cnt_b} beetles {bees_b} (expected (5,5) and two 7/7:"
        f" the captured 2/2 row and the 2/2 token); golden counter {cnt_g} "
        f"beetles {bees_g} (expected (10,10) and three 12/12)",
    )

    # 26. Motley Phalanx picks one friendly per type; Scarlet Skull gives one
    #     friendly Undead +1/+2.
    preg = {"P": SCRIPTS["BG27_080"], "SS": SCRIPTS["BG25_022"]}
    praces = {"B": ["BEAST"], "M": ["MECHANICAL"], "U": ["UNDEAD"]}
    s = Side([
        _from_row({"cardId": "P", "atk": 2, "health": 2, "damage": 2},
                  preg, {}),
        _from_row({"cardId": "B", "atk": 1, "health": 1}, preg, {}, praces),
        _from_row({"cardId": "M", "atk": 1, "health": 1}, preg, {}, praces),
        _from_row({"cardId": "N", "atk": 1, "health": 1}, preg, {}),
    ])
    _resolve_deaths(s, Side([]), random.Random(18))
    beast, mech, plain = s.ms[0], s.ms[1], s.ms[2]
    s2 = Side([
        _from_row({"cardId": "SS", "atk": 2, "health": 1, "damage": 1},
                  preg, {}),
        _from_row({"cardId": "U", "atk": 2, "health": 2}, preg, {}, praces),
        _from_row({"cardId": "N", "atk": 2, "health": 2}, preg, {}),
    ])
    _resolve_deaths(s2, Side([]), random.Random(18))
    undead = [m for m in s2.ms if m.cid == "U"][0]
    plain2 = [m for m in s2.ms if m.cid == "N"][0]
    check(
        "Motley Phalanx buffs one friendly per type; Scarlet Skull +1/+2",
        (beast.atk, beast.hp) == (3, 3) and (mech.atk, mech.hp) == (3, 3)
        and (plain.atk, plain.hp) == (1, 1)
        and (undead.atk, undead.hp) == (3, 4)
        and (plain2.atk, plain2.hp) == (2, 2),
        f"beast {beast.atk}/{beast.hp}, mech {mech.atk}/{mech.hp} (both "
        f"expected 3/3), tribeless {plain.atk}/{plain.hp} (expected 1/1); "
        f"undead {undead.atk}/{undead.hp} (expected 3/4), non-undead "
        f"{plain2.atk}/{plain2.hp} (expected 2/2)",
    )

    # 27. Face-damage bands and lethal/kill: hero tier rides the band, lethal
    #     and kill are eps-widened (never 0%/100%) and can never exceed the
    #     shown loss / win.
    hs = {"friendly": {"tier": 6, "health": 30, "armor": 0, "damage": 20},
          "enemy": {"tier": 5, "health": 12, "armor": 3, "damage": 10}}
    r = simulate([_row(50, 50)], [_row(1, 1)], n=300, seed=19, heroes=hs)
    # a lone TEST minion is tier 1, so every winning rollout deals 1 + 6 = 7
    band_ok = r["dmg_dealt"] == {"mean": 7.0, "q25": 7, "q75": 7}
    kill_ok = (r["raw_kill"] == 1.0 and 0.9 < r["kill"] < 1.0
               and r["kill"] <= r["win"])
    lethal_ok = (r["raw_lethal"] == 0.0 and 0.0 < r["lethal"] <= r["loss"])
    check(
        "face damage carries the hero tier; lethal/kill never claim certainty",
        band_ok and kill_ok and lethal_ok and r["dmg_taken"] is None,
        f"dmg_dealt {r['dmg_dealt']} (expected mean 7 = tier-1 minion + tier-6"
        f" hero), kill {r['kill']} of win {r['win']} (raw 1.0), lethal "
        f"{r['lethal']} of loss {r['loss']} (raw 0.0), dmg_taken "
        f"{r['dmg_taken']} (expected None - no losing rollouts)",
    )

    # 28. Without hero facts (or against a ghost's 0 remaining health) the
    #     sim says None instead of inventing a lethal number.
    r = simulate([_row(10, 10)], [_row(1, 1)], n=200, seed=20)
    ghost = {"friendly": {"tier": 4, "health": 25, "armor": 0, "damage": 5},
             "enemy": {"tier": 5, "health": 30, "armor": 0, "damage": 30}}
    rg = simulate([_row(10, 10)], [_row(1, 1)], n=200, seed=20, heroes=ghost)
    check(
        "no hero facts -> lethal/kill None; ghost enemy -> kill None",
        r["lethal"] is None and r["kill"] is None
        and rg["kill"] is None and rg["lethal"] is not None
        and rg["dmg_dealt"]["mean"] > r["dmg_dealt"]["mean"],
        f"bare lethal/kill {r['lethal']}/{r['kill']} (expected None/None); "
        f"ghost kill {rg['kill']} (expected None), lethal {rg['lethal']} "
        f"(their tier is real, our life is real); band with hero tier "
        f"{rg['dmg_dealt']['mean']} > bare {r['dmg_dealt']['mean']}",
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
