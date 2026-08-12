#!/usr/bin/env python3
"""bgtracker overlay - the launcher.

Three things live here and nothing else: the Reader that turns Power.log into
events, the Router that hands each event to the windows that asked for it, and
the App that owns the Tk loop. Every pixel is drawn by a window in ui/ - see
ui/__init__.py for the plugin contract and the event table.

    python overlay.py                  # live
    python overlay.py --demo <log>     # replay a log through the windows

Run Hearthstone in BORDERLESS WINDOWED.

SETTINGS PRECEDENCE (settings.py owns the file, this file owns the flags):

    an explicit flag  >  settings.json  >  the built-in default

A flag wins for the run it was typed on and is NEVER written back to the file,
so `--duo` once does not silently make every later run a Duos run. That is why
every flag below defaults to None rather than to a value: None is how argparse
says "the user did not type this", and only a typed flag becomes an override.

THE ONE RULE THE READER OBEYS
-----------------------------
Power.log writes everything twice. ``GameState.DebugPrintPower()`` writes an
ENTIRE fight - and often the next shop - in one burst, seconds ahead of the
screen. ``PowerTaskList.DebugPrintPower()`` replays it in sync with the
animation. So:

  * GameState is read for DATA only (the shop's contents, both warbands).
  * Every show/hide/clear is keyed to PowerTaskList.

Keying lifecycle off GameState is exactly what made the odds show up one fight
late, disappear mid-fight, and leave a COMBAT header sitting over the tavern.
"""

import argparse
import queue
import re
import sys
import threading
import time
import traceback
from pathlib import Path

import bgtracker as bg
import settings as settings_store
import ui
import ui.base
import update
from version import VERSION
from sim import boards as sim_boards
from sim import engine as sim_engine
from ui.base import WindowManager
from ui.comps import COMP_MIN
from ui.settings import SettingsPanel

DRAGBUY = "TB_BaconShop_DragBuy"
GOLD_TAG = "BACON_PLAYER_EXTRA_GOLD_NEXT_TURN"
# The log states the player-id -> battletag mapping outright, e.g.
#   PlayerID=5, PlayerName=Player#12345
# and the extra-gold tag is written against that battletag entity.
PLAYERNAME_RE = re.compile(r"PlayerID=(\d+), PlayerName=(\S+)")
COMBAT_TAG = "BACON_CURRENT_COMBAT_PLAYER_ID"
# The tavern's own refresh, with the player it belongs to. Used as a
# screen-synced "we are in the shop" signal - see the recovery note in
# Reader.consume.
REFRESH_RE = re.compile(r"cardId=TB_BaconShop_8p_Reroll_Button player=(\d+)")


class OddsEngine:
    """Combat win/tie/loss odds from the log alone - BETA.

    Every raw Power.log line goes through sim/boards.py's GameLogParser. The
    moment the current combat's pre-attack snapshot exists (the server writes
    BOTH warbands to the log ~1.4s before the fight even animates - measured
    over 222 real combats, 100% recovery from round 5 on), sim/engine.py's
    Monte Carlo runs in a background thread and pushes one odds event.

    Every result is stamped with the fight's sequence number, so the combat
    window can tell "computed early for the fight about to animate" from
    "computed for a fight that has already been superseded". Staleness is that
    and only that: a result is stale when a NEWER combat has started.

    Honesty rules, in order:
    - a board that is not FULLY recovered (any minion without a cardId, or an
      empty side - rounds 1-2 can genuinely produce one) -> no event ever,
      never a guessed number;
    - a sim exception -> no event;
    - the label stays BETA: replayed against the 339-fight cached harness the
      sim called the winning side 85.8% of the time (MAE 13.2pp, Brier 0.072) -
      vanilla rules, derived deathrattle summons, and per-card scripts for the
      cards that measurably cost the most accuracy. The long tail of cards is
      still unscripted, so engine.simulate() widens its own odds in proportion
      to how many unscripted combat effects are on the two boards, and never
      returns a bare 0% or 100%. The numbers pushed here are those widened
      ones, which is what should be shown; the raw rollout fractions stay on
      the result as raw_win / raw_tie / raw_loss.
    """

    # ROLLOUTS. Measured over the 339 cached real combats, on the fights that
    # are actually CLOSE (sim win% between 35 and 65), which are the only ones
    # where a percentage point changes what the player does:
    #
    #        n     ms/fight   sd across re-runs   worst spread
    #     1000        134        1.57pp              9.12pp
    #     3000        409        0.80pp              3.94pp
    #    10000       1482        0.42pp              2.02pp
    #    30000       4416        0.26pp              1.17pp
    #
    # 3000 used to be the default on the theory that the sim had to finish
    # inside the ~0.7s minimum lead the log gives before the first attack. That
    # was the wrong deadline: the odds have the whole fight ANIMATION to appear
    # in, which is tens of seconds (see the timing note in sim/boards.py). So
    # the budget is far larger than one second and 10000 fits inside it easily.
    #
    # What it buys is not accuracy - 12x the rollouts moves winner accuracy
    # 86.14% -> 86.43% over all 339 combats, one fight - it is STABILITY. On a
    # coin-flip fight 3000 rollouts can show a number ~4pp away from where the
    # same board lands on a different roll of the dice; 10000 halves that. The
    # model itself is still off by ~14pp, so this is polish, not a fix.
    #
    # Not higher than 10000: 30000 costs 4.4s to shave the worst spread from
    # 2.02pp to 1.17pp, and a short fight can be over before that lands.
    def __init__(self, push, n=10000, threaded=True):
        self.push, self.n, self.threaded = push, n, threaded
        self.parser = sim_boards.GameLogParser()
        self._lineno = 0
        self._open = None       # the combat dict currently being streamed
        self._simmed = None
        self.seq = -1           # how many fights have STARTED in the log
        self.round = None
        # Warm the card-script cache off the hot path. load_scripts never
        # raises: it degrades to a stale cache, then to a scriptless sim.
        threading.Thread(target=sim_engine.load_scripts, daemon=True).start()

    def feed(self, line):
        self._lineno += 1
        self.parser.feed(line.rstrip("\n"), self._lineno)
        c = self.parser.combat
        if c is not None and c is not self._open:
            self._open = c            # a new fight opened in the GameState copy
            self.seq += 1
            self.round = c["round"]
        if c is None or c is self._simmed or c["boards_pre_attack"] is None:
            return
        self._simmed = c
        b = c["boards_pre_attack"]
        fr, en = b["friendly"], b["enemy"]
        if not fr or not en or not all(r["cardId"] for r in fr + en):
            return          # unproven board -> no number at all
        seq = self.seq
        if self.threaded:
            threading.Thread(target=self._run, args=(c, fr, en, seq),
                             daemon=True).start()
        else:
            self._run(c, fr, en, seq)

    def _run(self, c, fr, en, seq):
        try:
            r = sim_engine.simulate(fr, en, n=self.n,
                                    heroes=c["boards_pre_attack"].get("heroes"))
        except Exception:
            return          # a sim failure means no line, never a fake one
        # dmg/lethal/kill ride the same rollouts. Each is None whenever the
        # log did not state the facts it needs (hero tier or life unknown,
        # ghost opponent) - the window shows a dash for None, never a guess.
        self.push({"seq": seq, "round": c["round"], "win": r["win"],
                   "tie": r["tie"], "loss": r["loss"], "n": r["n"],
                   "dmg_dealt": r["dmg_dealt"], "dmg_taken": r["dmg_taken"],
                   "lethal": r["lethal"], "kill": r["kill"]})


class Reader(threading.Thread):
    """Tails the log off the UI thread and posts events onto a sink.

    The sink is anything with ``put((name, payload))`` - a queue.Queue in the
    live app, a direct dispatcher in the tests.
    """

    daemon = True

    def __init__(self, sink, mmr, period, demo=None, duo=False, pace=True,
                 on_memory=None):
        super().__init__()
        self.q, self.mmr, self.period, self.demo = sink, mmr, period, demo
        self.duo, self.pace, self.on_memory = duo, pace, on_memory
        self.odds = None        # exposed for tests

    def run(self):
        try:
            heroes = bg.hero_table(self.mmr, self.period, duo=self.duo)
            trinkets = bg.trinket_table(self.period, self.mmr)
            comps = bg.comp_table(self.period, self.mmr)
            cards = bg.card_table(self.mmr, self.period)
            # Recognition is card-database driven; stats only decorate it.
            hero_ids = bg.hero_universe()
            trinket_ids = bg.trinket_universe()
            power_ids = bg.hero_power_universe()
        except Exception as e:
            self.q.put(("status", f"loading failed: {e}"))
            return
        self.q.put(("status", f"top {self.mmr}% · {self.period}"))

        det = bg.OfferDetector(heroes, trinket_ids, hero_ids, names=bg.card_names())
        choice = bg.ChoiceReader()
        odds = OddsEngine(lambda p: self.q.put(("odds", p)))
        self.odds = odds
        # The live tail starts at end-of-file, but the sim's board parser needs
        # the WHOLE game so far (boards build up across the log). Backfill the
        # current log's existing content into the odds parser only - the offer
        # detector must NOT see history or it would re-emit every past offer.
        if not self.demo:
            try:
                cur = bg.newest_power_log()
                if cur:
                    with open(cur, "r", encoding="utf-8", errors="ignore") as bf:
                        for _line in bf:
                            odds.feed(_line)
            except Exception:
                pass                    # backfill is best-effort
        memory = None
        if bg.MemoryTribes.available() and not self.demo:
            memory = bg.MemoryTribes()
            memory.start()
            if self.on_memory is not None:
                self.on_memory(memory)   # so quitting can kill the helper
        lobby = bg.LobbyTracker(memory)
        hero_open = False

        # ------------------------------------------------- per-game state
        shop_ts = None
        shop_ents = {}              # entity id -> (pos, name, card): the tavern
        pending_shop = [False]      # a settled tavern waiting for the SCREEN
        pending_choice = [None]     # a pick dialog waiting for the tavern
        names_map = bg.card_names()
        gs_phase = ["recruit"]      # GameState copy: data capture only
        ui_phase = ["recruit"]      # PowerTaskList copy: what the SCREEN shows
        rolls = [0]                 # how many times the tavern has been rebuilt
        board = []
        lean, lean_freq = None, {}
        me_name, last_gold, id_names = None, None, {}
        synergy = {}
        viable_tribes = set()
        try:
            name_tribes = {m["name"]: set(m["races"]) for m in bg.bg_pool()}
        except Exception:
            name_tribes = {}

        # ------------------------------------------------------ hero draft
        def emit_hero(ev, event="hero"):
            nonlocal hero_open
            if not ev or ev[0] != "hero choice":
                return None
            rows = []
            tribes = lobby.tribes
            for name, card, pos in ev[1]:
                st = heroes.get(bg.normalize(card, heroes))
                a = bg.lobby_adjust(st, tribes) if tribes else None
                rows.append({
                    "name": name,
                    "card": card,        # cardId, for reliable art lookup
                    "pos": pos,          # on-screen slot, so a badge can land
                    "avg": st["avg"] if st else None,
                    "adj": a,
                    "pick": st["pick"] if st else None,
                    "n": st["n"] if st else 0,
                })
            rows.sort(key=lambda r: (r["avg"] is None,
                                     r["adj"] if r["adj"] is not None else (r["avg"] or 0)))
            hero_open = True
            self.q.put((event, {"rows": rows,
                                "tuned": any(r["adj"] is not None for r in rows)}))
            return "hero choice"

        def push_lobby():
            tribes = lobby.tribes
            # The single best build for EACH tribe that is actually in - and a
            # tribe whose best comp has a thin sample still gets its row,
            # marked thin, instead of silently vanishing.
            playable = [c for c in comps
                        if c["tribe"] is None or c["tribe"] in tribes]
            best_per = {}
            for c in sorted(playable, key=lambda c: bg.comp_sort_key(c, COMP_MIN)):
                best_per.setdefault(c["tribe"] or "any", c)
            top = sorted(best_per.values(),
                         key=lambda c: bg.comp_sort_key(c, COMP_MIN))[:6]
            rebuild_synergy()
            self.q.put(("lobby", {"seen": set(tribes), "exact": lobby.exact,
                                  "comps": top, "all": comps}))

        # ------------------------------------------------------- your board
        def recompute_lean():
            # Which viable comp is his CURRENT BOARD leaning into? The mean
            # frequency of his minions on that comp's real finished boards.
            nonlocal lean, lean_freq
            ranked = []
            tribes = lobby.tribes
            for c in comps:
                if (c["tribe"] is None or c["tribe"] in tribes) and c["n"] >= COMP_MIN:
                    f = c.get("freq") or {}
                    hits = [bm for bm in board if f.get(bm, 0) > 0]
                    if not hits:
                        continue
                    # Score on the minions he ACTUALLY has, not diluted by an
                    # assumed board size - early boards otherwise never count.
                    ranked.append((sum(f[h] for h in hits) / len(board), len(hits),
                                   c["archetype"].replace("_", " "), f))
            ranked.sort(reverse=True)
            if ranked:
                _, hits, lean, lean_freq = ranked[0]
            else:
                hits, lean, lean_freq = 0, None, {}
            if lean is None and board:
                # Curated fallback: the baseline families carry no board
                # frequencies (freq={}, n=0), so the stats path above can never
                # match them. Overlap his board against each viable family's
                # cores AND tribe instead - labelled curated, no frequency
                # numbers invented (lean_freq stays empty, so no star bonus and
                # no 'yours' flag ride on it).
                best = None
                for c in comps:
                    if not c.get("baseline"):
                        continue
                    if c["tribe"] is not None and c["tribe"] not in tribes:
                        continue
                    cores = set(c.get("key_wide") or [])
                    ov = 0
                    for bm in board:
                        rs = name_tribes.get(bm) or set()
                        if bm in cores or (c["tribe"] is not None
                                           and (c["tribe"] in rs or "ALL" in rs)):
                            ov += 1
                    if ov >= 2 and (best is None or ov > best[0]):
                        best = (ov, c["archetype"].replace("_", " "))
                if best:
                    hits = best[0]
                    lean = f"{best[1]} (curated)"
            self.q.put(("board", {"size": len(board), "lean": lean, "hits": hits,
                                  "names": list(board)}))

        def board_from_memory():
            """Names of the minions on his board, straight from game memory."""
            if memory is None or not memory.board:
                return None
            names = bg.card_names()
            out = []
            for cid in memory.board:
                base = cid[:-2] if cid.endswith("_G") else cid
                out.append(names.get(base, base))
            return out

        # -------------------------------------------------- the other players
        # The leaderboard, and the last board each opponent was actually seen
        # holding. This is the ONE surface with no log source at all: during
        # recruit Power.log states nothing about another player's board, so
        # without the memory reader no event is ever emitted here and the
        # window simply never appears.
        #
        # WHEN a reading is worth believing - and this was settled by checking
        # captured boards against the log's own record of the same fights, not
        # by reasoning. Ungated, three of five captures were somebody's shop:
        # after a fight ends the client rebuilds the tavern in the same zone the
        # warband was in, and for a moment those minions carry no drag-buy token
        # for msync to exclude them by, while the beaten opponent's hero is
        # still standing there to attribute them to. Their sizes (4, 5, 5) were
        # shop sizes, and two of the cards were in that game's own shop.
        #
        # So capture ONLY while the fight is on the SCREEN. Nothing else in the
        # game puts an opponent's minions in that zone, and the PowerTaskList
        # copy is what says the screen is in a fight - the same rule every
        # window's lifecycle follows.
        #
        # Two rules keep the stamp honest:
        #   * within one fight, keep the FULLEST sighting. Minions only leave a
        #     warband as it is fought, so the biggest real reading of that fight
        #     is the closest to what they brought. Nothing is merged - a
        #     sighting is replaced whole or not at all, and a board that lost a
        #     minion before we first read it is short, never padded.
        #   * an unchanged board is never re-stamped, so the same warband cannot
        #     be re-filed under a later round and claim to have been seen more
        #     recently than it was.
        # A reading msync judged incoherent arrives here as an empty board and
        # is ignored - see the coherence rule in native/msync.
        seen_boards = {}            # hero cardId -> {"round": int, "board": [...]}
        last_players = [None]       # what we last pushed, to stay quiet when idle
        players_tick = [0.0]        # throttle: this runs off the line stream

        def flush_players():
            # Ticked from the line stream rather than from the GameState copy
            # alone: that copy writes the whole fight BEFORE it animates and is
            # then silent for the entire fight, which is exactly the window
            # this needs to read in (measured: gating on it captured nothing
            # across four minutes of live fights). Throttled, because the
            # stream is thousands of lines per burst and this reads and
            # rebuilds the whole leaderboard.
            now = time.monotonic()
            if now - players_tick[0] < 0.4:
                return
            players_tick[0] = now
            if memory is None or not memory.players:
                return
            names = bg.card_names()

            def named(cid):
                base = cid[:-2] if cid.endswith("_G") else cid
                nm = names.get(base, base)
                return nm + (" (golden)" if cid.endswith("_G") else "")

            rnd = odds.parser.turn or None
            # The round of the fight ON SCREEN, and only while it is on screen.
            # Not the round the log parser has reached: the GameState copy is
            # already past it, which filed one warband under two rounds.
            fight = odds.round if ui_phase[0] == "combat" else None
            rows = []
            for p in memory.players:
                card = p.get("card") or ""
                board = p.get("board") or []
                if board and fight is not None and not p.get("you"):
                    sig = [(m.get("card"), m.get("atk"), m.get("health"))
                           for m in board]
                    prev = seen_boards.get(card)
                    if prev is None:
                        keep = True
                    elif prev["round"] == fight:
                        keep = len(board) > len(prev["board"])
                    else:
                        keep = prev["sig"] != sig
                    if keep:
                        seen_boards[card] = {"round": fight, "sig": sig, "board": [
                            {"card": m.get("card"), "name": named(m.get("card") or ""),
                             "atk": m.get("atk"), "health": m.get("health")}
                            for m in board]}
                kept = seen_boards.get(card) or {}
                rows.append({
                    "place": p.get("place"), "card": card, "name": named(card),
                    "health": p.get("health"), "armor": p.get("armor"),
                    "tier": p.get("tier"), "you": bool(p.get("you")),
                    "board": kept.get("board") or [],
                    "seen_round": kept.get("round"),
                })
            rows.sort(key=lambda r: r["place"] or 99)
            payload = {"round": rnd, "rows": rows}
            if payload != last_players[0]:
                last_players[0] = payload
                self.q.put(("players", payload))

        def flush_board():
            # Board synergy needs the memory reader (native/msync). The log
            # can't give a reliable board: bought minions move via tag-changes
            # and one player id owns both the shop and the board.
            # RECRUIT ONLY: during a fight the game's PLAY zone is the combat
            # copy, and msync reads minions OUT of it as they die - consuming
            # that showed "YOUR BOARD (2)" mid-fight against a real board of 7
            # (live repro 2026-08-11). The last tavern board stays frozen until
            # the tavern is really back.
            if gs_phase[0] != "recruit" or ui_phase[0] != "recruit":
                return
            mem = board_from_memory()
            if mem is not None and mem != board:
                board[:] = mem
                recompute_lean()

        # ------------------------------------------------------ star tiers
        # Stars rank the buy-it-vs-skip-it DIFFERENTIAL (averagePlacement minus
        # averagePlacementOther), by quintile within each tavern tier. Raw
        # averages rated whole shops five stars: they measure who buys a card,
        # not whether it helps.
        tiers = bg.card_tiers()
        _by_tier = {}
        for cid, v in cards.items():
            if v.get("delta") is not None and v.get("n", 0) >= bg.MIN_SAMPLE:
                _by_tier.setdefault(tiers.get(cid, 0), []).append(v["delta"])
        # Top-heavy bands: five stars means top 8% of its tier, four means top
        # quarter. Even quintiles left half of every decent shop at five stars,
        # which recommends nothing.
        _cut = {}
        for t, vals in _by_tier.items():
            vals.sort()
            if len(vals) >= 10:
                _cut[t] = [vals[int(len(vals) * k)] for k in (0.08, 0.25, 0.50, 0.75)]

        def star(st, name, tier=0):
            """1..5 vs its own tier, +1 when it feeds the comp he's building.
            With no per-minion data at all, fall back to the curated baseline:
            a minion that is core to a lobby-viable comp family gets 3 stars
            (4 when it also feeds the build he's on), everything else 0 - a
            coarse but honest 'this one matters' signal instead of a dead UI."""
            delta = (st or {}).get("delta")
            cut = _cut.get(tier) or _cut.get(0)
            if delta is None or not cut:
                if not _cut:
                    if synergy.get(name):
                        return 4 if (lean and lean_freq.get(name, 0) >= 0.10) else 3
                    rs = name_tribes.get(name) or set()
                    if "ALL" in rs or rs & viable_tribes:
                        return 2
                return 0
            s = 5 if delta <= cut[0] else 4 if delta <= cut[1] else \
                3 if delta <= cut[2] else 2 if delta <= cut[3] else 1
            if lean and lean_freq.get(name, 0) >= 0.10:
                s = min(5, s + 1)
            return s

        def rebuild_synergy():
            # minion name -> the best lobby-viable comp that actually runs it.
            # Curated baseline families count too - their cores come from the
            # live card pool, which is exactly what the shop tags need.
            synergy.clear()
            viable_tribes.clear()
            tribes = lobby.tribes
            for c in comps:
                if ((c["tribe"] is None or c["tribe"] in tribes)
                        and (c.get("baseline") or c["n"] >= COMP_MIN)):
                    for nm in c.get("key_wide") or []:
                        synergy.setdefault(nm, c["archetype"].replace("_", " "))
                    if c.get("baseline") and c["tribe"] is not None:
                        viable_tribes.add(c["tribe"])

        def minion_row(pos, name, card):
            base = card[:-2] if card.endswith("_G") else card
            st = cards.get(base) or {}
            tier = tiers.get(base, 0)
            return {"pos": pos, "name": name, "card": card,
                    "avg": st.get("avg"), "n": st.get("n", 0),
                    "tier": tier, "stars": star(st, name, tier),
                    "comp": synergy.get(name),
                    "mine": lean is not None and lean_freq.get(name, 0) >= 0.10}

        # ---------------------------------------------------------- tavern
        def sample_shop():
            """Rebuild the tavern from the odds parser's ENTITY STATE.

            Line-shape captures missed REROLLS entirely: a rerolled minion is
            FULL_ENTITY-created in SETASIDE and only transits to PLAY via tag
            changes inside the refresh block (live repro 2026-08-11), so no
            single line ever says "this minion entered the shop", and the
            DragBuy tokens are re-used so drag counts are 0 on a reroll. The
            boards.py parser already tracks every entity's zone / position /
            controller - the shop is what sits in PLAY under Bob's controller
            (minions AND tavern spells; positions run 1..N across both).
            Returns True when the shop changed - which is exactly a roll, a
            buy, a sell or a tavern spell resolving.
            """
            p = odds.parser
            if p.ai_ctrl is None:
                return False
            ents = {}
            for e in p.entities.values():
                if (e.tags.get("ZONE") == "PLAY"
                        and e.num("CONTROLLER") == p.ai_ctrl
                        and e.tags.get("CARDTYPE") in ("MINION", "BATTLEGROUND_SPELL")
                        and e.num("ZONE_POSITION") >= 1 and e.card_id):
                    base = e.card_id[:-2] if e.card_id.endswith("_G") else e.card_id
                    nm = e.name or names_map.get(base, base)
                    ents[e.eid] = (e.num("ZONE_POSITION"), nm, e.card_id)
            if ents == shop_ents:
                return False
            shop_ents.clear()
            shop_ents.update(ents)
            return True

        def emit_shop():
            # Push the settled tavern - but only when the SCREEN is in the
            # tavern too. The GameState copy rolls the next shop while the
            # fight is still animating; pushing it early wiped the odds line
            # mid-combat (screen-verified 2026-08-11).
            if gs_phase[0] != "recruit" or not shop_ents:
                return
            if ui_phase[0] != "recruit":
                pending_shop[0] = True      # hold for the PTL recruit flip
                return
            pending_shop[0] = False
            rows = [minion_row(pos, n, c) for pos, n, c in sorted(shop_ents.values())]
            if len(rows) < 2:
                return
            rolls[0] += 1
            self.q.put(("tavern", {
                "rows": sorted(rows, key=lambda r: -r["stars"]),
                "slots": sorted(rows, key=lambda r: r["pos"]),
                "roll": rolls[0], "lean": lean}))

        # ----------------------------------------------------- choose-ones
        def deliver_choice(kind, blk):
            """One choose-one block -> exactly one window."""
            if kind == "trinket":
                rows = []
                for i, nm, cid in blk:
                    st = trinkets.get(bg.normalize(cid, trinkets))
                    rows.append({"name": nm, "card": cid, "pos": i + 1,
                                 "avg": st["avg"] if st else None, "adj": None,
                                 "pick": st["pick"] if st else None,
                                 "n": st["n"] if st else 0})
                rows.sort(key=lambda r: (r["avg"] is None, r["avg"] or 0))
                self.q.put(("trinket", {"rows": rows, "tuned": False,
                                        "roll": rolls[0]}))
            elif kind == "heropower":
                # No hero-power feed exists. Show a row per option and a number
                # only if a configured source happens to carry that cardId -
                # never the owning hero's average.
                rows = []
                for i, nm, cid in blk:
                    st = cards.get(cid) or {}
                    rows.append({"pos": i + 1, "name": nm, "card": cid,
                                 "avg": st.get("avg"), "n": st.get("n", 0)})
                self.q.put(("heropower", {"rows": rows, "roll": rolls[0]}))
            else:
                # Minion discover / Dark Gift. Score every option we CAN and
                # show the rest as no-data, instead of dropping the whole panel
                # when one option (a token, a brand-new card) has no stats.
                rows = [minion_row(i + 1, nm, cid) for i, nm, cid in blk]
                self.q.put(("discover", {"rows": rows, "roll": rolls[0]}))

        # ------------------------------------- the screen changing phase
        # Both helpers are the ONLY places a window is told the phase moved,
        # so the recovery path below behaves identically to the normal one.
        def screen_combat():
            ui_phase[0] = "combat"
            self.q.put(("tavern_gone", None))
            self.q.put(("picks_over", None))
            self.q.put(("combat", {"seq": odds.seq, "round": odds.round}))

        def screen_recruit():
            ui_phase[0] = "recruit"
            self.q.put(("combat_over", None))
            # The screen is back in the tavern: first the shop the GameState
            # copy rolled during the fight, then any buffered pick over it.
            if pending_shop[0]:
                emit_shop()
            if pending_choice[0] is not None:
                deliver_choice(*pending_choice[0])
                pending_choice[0] = None

        # ------------------------------------------------------- the stream
        def consume(line):
            nonlocal hero_open, shop_ts, me_name, last_gold
            odds.feed(line)              # combat boards -> BETA win/tie/loss
            flush_players()              # leaderboard (memory reader only)

            blk = choice.feed(line)
            if blk:
                kind = ui.classify_choice([c for _, _, c in blk], heroes=hero_ids,
                                          trinkets=trinket_ids, hero_powers=power_ids)
                if kind == "hero":
                    pass    # the draft belongs to the detector: it alone knows
                            # the true on-screen slot order after the shuffle
                elif ui_phase[0] == "recruit":
                    deliver_choice(kind, blk)
                else:
                    # Trinket and discover dialogs are both written to the log
                    # DURING the fight that precedes them. Hold them until the
                    # SCREEN is back in the tavern - showing them on sight put
                    # a pick panel over a running fight.
                    pending_choice[0] = (kind, blk)

            ev = det.feed(line)
            # Trinkets come from the choice block, which carries the true
            # on-screen order. The detector sees them in SETASIDE where every
            # option logs zonePos=0, so its order is meaningless.
            kind = emit_hero(ev) if ev and ev[0] == "hero choice" else None
            if det.refresh:                      # badges move to final slots
                emit_hero(det.refresh, "hero_slots")
                det.refresh = None
            if det.new_game:
                det.new_game = False
                lobby.reset()
                board.clear()
                shop_ents.clear()
                seen_boards.clear()      # last game's boards belong to last game
                last_players[0] = None
                rolls[0] = 0
                pending_shop[0] = False
                pending_choice[0] = None
                self.q.put(("game", None))
                push_lobby()
            if lobby.feed(line):
                push_lobby()
            # Shop minions on SCREEN means the hero was picked. PowerTaskList
            # only: the GameState copy deals the first shop before the draft
            # has finished animating.
            if hero_open and "PowerTaskList" in line and bg.RACE_RE.search(line):
                hero_open = False
                det._live = {}                   # hero picked: stop moving badges
                self.q.put(("hero_over", None))

            # This tag names the player currently fighting - and is set back to
            # ZERO when the fight ends, which is the return to the tavern. It
            # appears in BOTH copies: GameState drives our own bookkeeping,
            # PowerTaskList drives every window.
            if COMBAT_TAG in line:
                v = re.search(r"value=(\d+)", line)
                if v:
                    ph = "combat" if int(v.group(1)) else "recruit"
                    if ph != gs_phase[0]:
                        gs_phase[0] = ph
                        if ph == "combat":
                            shop_ents.clear()     # tavern is gone during a fight
                            pending_shop[0] = False
                    if "PowerTaskList" in line and ph != ui_phase[0]:
                        screen_combat() if ph == "combat" else screen_recruit()

            # RECOVERY - a fight whose end marker never arrives.
            # Measured on two real logs: 4 of 69 and 6 of 82 fights write their
            # start but never their value=0. The phase then stays "combat" for
            # the whole NEXT recruit phase: the tavern window never comes back,
            # the shop is never sampled, and the COMBAT header sits over the
            # shop. A tavern REFRESH belonging to OUR player in the
            # PowerTaskList copy can only happen with the shop on screen, so it
            # is a sound recruit signal - and it proved specific, firing on 4 of
            # 930 and 6 of 846 refreshes, i.e. only inside the broken fights.
            if (ui_phase[0] == "combat" and "Reroll_Button" in line
                    and "BLOCK_START" in line and det.player is not None):
                rm = REFRESH_RE.search(line)
                if rm and rm.group(1) == det.player:
                    if "PowerTaskList" in line:
                        gs_phase[0] = "recruit"   # the fight is long over
                        screen_recruit()
                    elif gs_phase[0] == "combat":
                        # Our own reroll cannot be written during our own
                        # fight, so the GameState copy is safe to unstick too:
                        # that is what lets the shop be sampled again.
                        gs_phase[0] = "recruit"

            # Tavern capture: sample the odds parser's entity state once per
            # GameState timestamp - by then the burst that just ended has
            # settled (mid-burst a reroll is half removals, half adds).
            tm = bg.TS_RE.match(line)
            if tm and "GameState" in line:
                ts = tm.group(1)
                if ts != shop_ts:
                    shop_ts = ts
                    if gs_phase[0] == "recruit" and sample_shop():
                        emit_shop()
                    flush_board()

            m = bg.ENTITY_RE.match(line)
            if m and m["card"] == DRAGBUY and det.player is None:
                det.player = m["player"]       # local player, for the gold read
            # Gold read: learn every player-id -> battletag mapping, then once
            # we know our own id (from the DragBuy token) watch our battletag's
            # extra-gold tag.
            pn = PLAYERNAME_RE.search(line)
            if pn:
                id_names[pn.group(1)] = pn.group(2)
            if det.player is not None:
                if me_name is None:
                    me_name = id_names.get(det.player)
                if me_name and GOLD_TAG in line and f"Entity={me_name} " in line:
                    gv = re.search(r"value=(\d+)", line)
                    if gv and int(gv.group(1)) != last_gold:
                        last_gold = int(gv.group(1))
                        self.q.put(("gold", last_gold))
            return kind

        if self.demo:
            pauses = 0
            with open(self.demo, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f):
                    kind = consume(line)
                    if not self.pace:
                        continue
                    if kind and pauses < 3:      # hold the first offers so a
                        pauses += 1              # human (or a screenshot) can look
                        time.sleep(6)
                    elif i % 200 == 0:
                        time.sleep(0.02)
            emit_hero(det.flush())
            self.q.put(("status", "replay finished"))
            return

        path = bg.newest_power_log()
        if not path:
            self.q.put(("status", "no Power.log - is Hearthstone installed?"))
            return
        for line in bg.follow(path):
            if line is None:
                emit_hero(det.flush())
                flush_board()      # catch msync updates between log bursts
                flush_players()
            else:
                consume(line)


class Router:
    """Delivers each event to the windows that declared it in EVENTS.

    That is the whole of it. The router holds no state, decides nothing, and
    knows no window by name - which is what keeps the surfaces independent.
    """

    def __init__(self, windows):
        self.windows = list(windows)
        self.by_event = {}
        for w in self.windows:
            for ev in w.EVENTS:
                self.by_event.setdefault(ev, []).append(w)
        self.counts = {}

    def dispatch(self, name, payload):
        self.counts[name] = self.counts.get(name, 0) + 1
        for w in self.by_event.get(name, ()):
            w.handle(name, payload)


class App:
    """Tk loop + reader thread + router. No drawing lives here."""

    def __init__(self, settings, demo=None, panel=True):
        self.q = queue.Queue()
        self.settings = settings
        self.panel = None
        # Scale FIRST, before a single window exists: a window built at the
        # right size never has to be repainted into it, and set_scale is a
        # no-op when the saved value is already in force.
        ui.base.set_scale(settings.get("ui_scale") or ui.base.auto_scale())
        ui.base.set_badge_scale(settings.get("badge_scale"))
        # A window switched off is NOT built. Hiding it would leave it eating
        # its events and holding a badge strip in the priority list that can
        # hide somebody else's badges - "off" has to mean absent.
        # QUIT_BUTTON is exempt from the toggle: every other surface is
        # click-through, so that window's gear and X are the only clicks the
        # overlay can take. The panel refuses to switch it off and heals a
        # hand-edited "off"; this filter is the boot-time half of the same
        # guarantee (the panel may be set to not open on start).
        classes = [c for c in ui.WINDOWS
                   if c.QUIT_BUTTON or settings.window_enabled(c.KEY)]
        self.manager = WindowManager(classes, names_fn=bg.card_names)
        self.router = Router(self.manager.windows)
        self.memory = None
        self.manager.on_quit = self._on_quit
        self.manager.on_windows_changed = self._rebuild_router
        self.manager.open_settings = self.open_settings
        self.reader = Reader(self.q, settings.get("mmr"), settings.get("time"),
                             demo=demo, duo=settings.get("duo"),
                             on_memory=self._on_memory)
        # The reference surface comes up straight away, so there is something
        # on screen ("waiting for a game") before the first log line arrives.
        # It is a window like any other, so it can be switched off.
        comps = self.manager.by_key.get("comps")
        if comps is not None:
            comps.show()
        if panel:
            self.open_settings()

    # -- the settings panel ------------------------------------------------

    def open_settings(self):
        """Build it once, then show the same one. Closing it only hides it."""
        try:
            if self.panel is None:
                self.panel = SettingsPanel(self, self.settings, self.manager)
            self.panel.show()
        except Exception:
            # A settings panel that fails to build must not take the overlay
            # down with it: the tool is fully usable without ever opening one.
            traceback.print_exc()

    def _rebuild_router(self):
        """The registry changed. The router indexes windows by event when it is
        built, so a window added or dropped behind its back would never be
        dispatched to (or would be dispatched to after being destroyed)."""
        self.router = Router(self.manager.windows)

    def set_window_enabled(self, key, on):
        cls = next((c for c in ui.WINDOWS if c.KEY == key), None)
        if cls is None:
            return
        if not on:
            self.manager.disable(key)
            return
        w = self.manager.enable(cls)
        # A window built mid-session has missed every event so far. The ones
        # that open on their own trigger will do so at the next one; the
        # reference surface is the only one that is simply always up.
        if key == "comps":
            w.show()

    def _on_memory(self, memory):
        self.memory = memory

    def _on_quit(self):
        if self.memory is not None:
            self.memory.stop()   # else msync outlives us and locks its binary

    def quit(self):
        self.manager.quit()

    def _poll(self):
        try:
            while True:
                name, payload = self.q.get_nowait()
                if name == "game":
                    self.manager.reset_all()
                self.router.dispatch(name, payload)
        except queue.Empty:
            pass
        self.manager.root.after(120, self._poll)

    def run(self):
        self.reader.start()
        self.manager.start()
        self.manager.root.after(120, self._poll)
        self.manager.root.mainloop()


def diag(settings=None):
    """Print what this build actually loaded, then exit.

    The failure mode a standalone build has and a source checkout does not is
    "it starts, and shows nothing": a packer collects overlay.py, misses the
    window modules, and the registry comes up short with no error anywhere.
    So print the registry from INSIDE the program - every window class, the
    module it really came from, and the events it asked for - plus the paths it
    will read and write. Anyone can run `bgtracker.exe --diag` and paste the
    output into a bug report.
    """
    import tkinter

    from paths import app_dir, bundle_dir, frozen
    print("bgtracker diag")
    print(f"  version     {VERSION}")
    print(f"  frozen      {frozen()}")
    print(f"  executable  {sys.executable}")
    print(f"  app dir     {app_dir()}        (writes: .cache, data, assets, "
          f".overlay.json, sources.json)")
    print(f"  bundle dir  {bundle_dir()}     (code)")
    print(f"  python      {sys.version.split()[0]}   tcl/tk "
          f"{tkinter.TkVersion}")
    try:
        from PIL import Image  # noqa: F401
        pil = "yes (card art can be drawn)"
    except Exception as e:
        pil = f"no ({e}) - the overlay draws colored dots instead"
    print(f"  pillow      {pil}")
    print(f"  msync       {'built' if bg.MSYNC_EXE.exists() else 'not built'}"
          f"  ({bg.MSYNC_EXE})")
    print(f"  sources     {'configured' if bg.SOURCES_FILE.exists() else 'none'}"
          f"  ({bg.SOURCES_FILE})")
    print(f"  updates     {'checked on start' if update.checks_enabled() else 'off'}"
          f"  ({update.manifest_url()})")

    print(f"  sim         {sim_boards.__name__} + {sim_engine.__name__} loaded "
          f"({len(sim_engine.SCRIPTS)} hand-written card scripts)")

    # The settings, with where each value came from - a bug report that says
    # "the panel is off" or "it keeps showing Duos" is answered by this block.
    settings = settings or settings_store.Settings.load()
    print(f"\nsettings    {settings.path} "
          f"({'present' if settings.path.exists() else 'not written yet, all defaults'})")
    print("\n".join(settings.describe()))
    for problem in settings.problems:
        print(f"  ! {problem}")

    print(f"\nui.WINDOWS registry: {len(ui.WINDOWS)} windows")
    for cls in ui.WINDOWS:
        state = "on" if settings.window_enabled(cls.KEY) else "OFF (not built)"
        print(f"  {cls.KEY:9} {cls.__name__:18} {cls.__module__:14} "
              f"{cls.COLUMN:5} y+{cls.DY:<4} {state:15} {','.join(cls.EVENTS)}")

    mgr = WindowManager(ui.WINDOWS, names_fn=lambda: {})
    router = Router(mgr.windows)
    print(f"\nconstructed: {len(mgr.windows)} windows, "
          f"{len(router.by_event)} distinct events routed")
    print("  " + " ".join(w.heartbeat() for w in mgr.windows))
    missing = [c.KEY for c in ui.WINDOWS if c.KEY not in mgr.by_key]
    print(f"  missing: {missing or 'none'}")
    mgr.root.destroy()
    return 0 if not missing and len(mgr.windows) == len(ui.WINDOWS) else 1


def _announce_update(u):
    """One line in the console the tool prints everything else to.

    Nothing pops up and nothing installs. The build is unsigned, so a folder
    the user extracted by hand is not something to swap out from under them
    without being asked - see update.py.
    """
    if u.available:
        print(f"\n{u}\n  what changed: {u.notes or u.url}\n"
              f"  nothing has been downloaded and nothing will be until you ask\n",
              flush=True)


def share_if_opted_in(settings):
    """Contribute this machine's games to the community feed - opt-in only.

    Three gates, in order: the saved opt-in (OFF by default, and nothing here
    runs while it is off), a feed address, and at most one share every twelve
    hours. Off the UI thread, and a failure is printed rather than raised: a
    feed that is down is not a reason for the overlay to behave differently.
    """
    if not settings.get("upload"):
        return None
    url = (settings.get("upload_url") or "").strip()
    if not url:
        return None
    last = settings.get("last_upload")
    if last and time.time() - last < 12 * 3600:
        return None

    def work():
        # Mining reads every Power.log the machine still has: measured at 53
        # seconds over 1.6 GB of them. It is off the UI thread and disk bound
        # rather than CPU bound, but that is still a minute of reading, so it
        # waits until the overlay and the game have finished starting.
        time.sleep(20)
        try:
            import collect
            collect.collect()
            res = collect.upload(url) or {}
            if res.get("sent"):
                settings.set("last_upload", time.time())
        except Exception as e:
            print(f"  ! sharing games failed: {type(e).__name__}: {e}",
                  file=sys.stderr)

    t = threading.Thread(target=work, name="share-games", daemon=True)
    t.start()
    return t


def main():
    ap = argparse.ArgumentParser(description="Anchored, per-concern Battlegrounds overlay.")
    # Every flag defaults to None: only a flag the user actually typed becomes
    # an override, and an override lasts for this run only (settings.py).
    ap.add_argument("--mmr", default=None, choices=list(settings_store.MMR_CHOICES),
                    help="MMR bracket to read numbers from (saved setting otherwise)")
    ap.add_argument("--time", default=None, choices=list(settings_store.TIME_CHOICES),
                    help="how far back the numbers go (saved setting otherwise)")
    ap.add_argument("--duo", action="store_true", default=None,
                    help="Duos hero stats (only heroes exist for Duos; comps, "
                         "trinkets and minions have no Duos feed)")
    ap.add_argument("--demo", help="replay a Power.log through the windows")
    ap.add_argument("--diag", action="store_true",
                    help="print the loaded windows and the paths in use, then exit")
    ap.add_argument("--no-update-check", action="store_true",
                    help="do not look for a new version on start")
    ap.add_argument("--no-panel", action="store_true",
                    help="do not open the settings panel on start")
    args = ap.parse_args()
    s = settings_store.Settings.load(overrides={
        "mmr": args.mmr, "time": args.time, "duo": args.duo})
    for problem in s.problems:
        print(f"  ! {problem}", file=sys.stderr)
    if args.diag:
        raise SystemExit(diag(s))
    # A 200-byte JSON fetch on a daemon thread, before anything is built: it
    # cannot stall the overlay, and a dead server, no network or a captive
    # portal all end in silence (update.py). It never installs anything.
    update.start_check(_announce_update, disabled=args.no_update_check)
    # A demo replays somebody's log through the windows; sharing games out of a
    # run whose whole point is that it is not live would be wrong.
    if not args.demo:
        share_if_opted_in(s)
    App(s, Path(args.demo) if args.demo else None,
        panel=bool(s.get("open_on_start")) and not args.no_panel).run()


if __name__ == "__main__":
    main()
