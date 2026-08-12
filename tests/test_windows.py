#!/usr/bin/env python3
"""Window-lifecycle regression: replay a real Power.log through the Router.

The overlay's whole design claim is that each window has an independent
lifecycle keyed to the screen. This harness proves it against a real log
instead of against belief:

  1. an INDEPENDENT pass over the log establishes ground truth - how many
     times the local player's shop was refreshed, how many fights the
     PowerTaskList copy (the screen) actually started and ended, and how many
     choose-one dialogs of each kind appeared;
  2. a second pass drives the real Reader -> Router -> real window objects
     (headless: no drawing, no mapping), recording every event and every
     window open/close with the log line it happened on;
  3. the two are compared and printed;
  4. the COUNTERS parser is replayed over the same log on its own, because its
     numbers come from the log directly rather than through the reader;
  5. every window is actually PAINTED with real payloads, and the default
     stack is checked for overlapping bands.

Usage:
    python tests/test_windows.py [<Power.log> ...]

With no arguments it uses the newest Power.log under the Hearthstone install.
With no Power.log available at all it SKIPS (exit 0) - a real log is player
data and is deliberately not in the repository.
"""

from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg          # noqa: E402
import overlay                  # noqa: E402
import ui                       # noqa: E402
from ui.base import WindowManager   # noqa: E402
from ui.counters import CounterState   # noqa: E402

# Windows remember their place - and the session window remembers the sitting -
# in .overlay.json. A test must never write the player's real one, so every
# manager built here is pointed at a throwaway file.
POS_FILE = Path(tempfile.gettempdir()) / "bgtracker-test-overlay.json"

# Three bands are shared on purpose (see ui/__init__.py): the session panel
# steps aside for the hero draft, the leaderboard steps aside for a trinket
# dialog, and the minion browser is a slim bar that only covers the left column
# when the player clicks it open.
SHARED_BANDS = {frozenset(("session", "heropick")),
                frozenset(("trinkets", "players"))}

HERO_HAND_RE = re.compile(
    r"FULL_ENTITY - Updating \[entityName=.*? id=\d+ zone=HAND .*?"
    r"cardId=\w*HERO_\d+\w* player=(?P<player>\d+)\]")
REROLL_RE = re.compile(r"BLOCK_START .*cardId=TB_BaconShop_8p_Reroll_Button "
                       r"player=(?P<player>\d+)")
COMBAT_VALUE_RE = re.compile(r"tag=BACON_CURRENT_COMBAT_PLAYER_ID value=(\d+)")


def ground_truth(path: Path):
    """Measure the log directly - no window code in this function.

    The local player id is learned the way everything else in this project
    learns it: only OUR hero options are revealed into zone=HAND, so the
    player id on those lines is us (ids change every game, so it is relearned
    on every draft).
    """
    local = None
    rolls, combat_starts, combat_ends, drafts = [], [], [], []
    last_roll_ts = None
    ptl_phase = "recruit"
    choice_lines = {"hero": [], "trinket": [], "heropower": [], "discover": []}
    reader = bg.ChoiceReader()
    heroes = bg.hero_universe()
    trinkets = bg.trinket_universe()
    powers = bg.hero_power_universe()
    i = 0

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            blk = reader.feed(line)
            if blk:
                kind = ui.classify_choice([c for _, _, c in blk], heroes=heroes,
                                          trinkets=trinkets, hero_powers=powers)
                choice_lines[kind].append(i)
            if "zone=HAND" in line and "HERO_" in line and "FULL_ENTITY" in line:
                m = HERO_HAND_RE.search(line)
                if m:
                    if m.group("player") != local:
                        drafts.append(i)
                    local = m.group("player")
            if ("Reroll_Button" in line and "BLOCK_START" in line
                    and "PowerTaskList" in line and ptl_phase == "combat"):
                m = REROLL_RE.search(line)
                if m and m.group("player") == local:
                    # Some fights never write their end marker (4 of 69 in one
                    # real log). The screen HAS returned to the tavern - our
                    # own shop cannot refresh anywhere else - so ground truth
                    # counts this as the fight ending, exactly as a player
                    # would see it.
                    ptl_phase = "recruit"
                    combat_ends.append(i)
            if "Reroll_Button" in line and "BLOCK_START" in line and "GameState" in line:
                m = REROLL_RE.search(line)
                if m and m.group("player") == local:
                    # ONE refresh fires a Refresh trigger block per slot it
                    # replaces (measured: 136 blocks for 36 refreshes). The
                    # refresh MOMENT is the timestamp, so group on that.
                    ts = bg.TS_RE.match(line)
                    ts = ts.group(1) if ts else str(i)
                    if ts != last_roll_ts:
                        last_roll_ts = ts
                        rolls.append(i)
            if "PowerTaskList" in line and "BACON_CURRENT_COMBAT_PLAYER_ID" in line:
                m = COMBAT_VALUE_RE.search(line)
                if m:
                    ph = "combat" if int(m.group(1)) else "recruit"
                    if ph != ptl_phase:
                        ptl_phase = ph
                        (combat_starts if ph == "combat" else combat_ends).append(i)
    return {"rolls": rolls, "combat_starts": combat_starts,
            "combat_ends": combat_ends, "drafts": drafts,
            "choices": choice_lines, "lines": i}


class Sink:
    """Stands in for the live queue: dispatches straight into the Router and
    records what happened, tagged with the log line it happened on."""

    def __init__(self, router, manager=None):
        self.router = router
        self.manager = manager
        self.by_key = {w.KEY: w for w in router.windows}
        self.reader = None
        self.events = []            # (lineno, name)
        self.opens = []             # (lineno, window key)
        self.closes = []            # (lineno, window key)
        self.fights = []            # one dict per fight the SCREEN showed
        self.sample = {}            # one real payload per event, for the
                                    # render pass below
        self.drafts = []            # (session was open, session yielded) per
                                    # hero offer - the shared band, proven

    def line(self):
        o = getattr(self.reader, "odds", None)
        return o._lineno if o is not None else -1

    def put(self, item):
        name, payload = item
        ln = self.line()
        self.events.append((ln, name))
        if name not in self.sample and payload is not None:
            self.sample[name] = payload
        combat = self.by_key["combat"]
        # A fight ends either by the screen returning to the tavern, or - for
        # the last fight of a game - by the next game starting. Sample the
        # odds BEFORE the close, i.e. at the last instant of the fight.
        if name in ("combat_over", "game") and combat.is_open and self.fights:
            self.fights[-1]["at_close"] = combat._current() is not None
            self.fights[-1]["closed"] = True
            self.fights[-1]["by"] = name
        before = {w.KEY: w.is_open for w in self.router.windows}
        if name == "game" and self.manager is not None:
            self.manager.reset_all()      # exactly what App._poll does live
        self.router.dispatch(name, payload)
        if name == "hero":
            # heropick and session share the left column's top band. The draft
            # must own it alone while it is up.
            self.drafts.append((self.by_key["heropick"].is_open,
                                self.by_key["session"].is_open))
        if name == "combat" and combat.is_open:
            self.fights.append({"seq": combat.seq, "closed": False, "by": None,
                                "at_open": combat._current() is not None,
                                "at_close": None, "odds": False})
        if name == "odds" and self.fights and combat.is_open \
                and payload.get("seq") == combat.seq:
            self.fights[-1]["odds"] = True
        if name == "combat" and self.fights and combat._current() is not None:
            self.fights[-1]["odds"] = True
        for w in self.router.windows:
            if w.is_open and not before[w.KEY]:
                self.opens.append((ln, w.KEY))
            elif before[w.KEY] and not w.is_open:
                self.closes.append((ln, w.KEY))


def matched(events, marks, stops):
    """How many `marks` are followed by an `event` before the next mark, and
    (looser) before the next `stop`."""
    strict = loose = 0
    ev = sorted(events)
    for idx, m in enumerate(marks):
        nxt_mark = marks[idx + 1] if idx + 1 < len(marks) else float("inf")
        nxt_stop = next((s for s in stops if s > m), float("inf"))
        hit = next((e for e in ev if e > m), None)
        if hit is None:
            continue
        if hit < nxt_mark:
            strict += 1
        if hit < nxt_stop:
            loose += 1
    return strict, loose


def replay(path: Path):
    manager = WindowManager(ui.WINDOWS, headless=True, pos_file=POS_FILE)
    router = overlay.Router(manager.windows)
    sink = Sink(router, manager)
    reader = overlay.Reader(sink, "100", "last-patch", demo=path, pace=False)
    sink.reader = reader
    t0 = time.time()
    reader.run()
    time.sleep(2.5)             # let the last sim threads land
    return manager, router, sink, time.time() - t0


def check(path: Path) -> bool:
    print(f"\n=== {path}")
    gt = ground_truth(path)
    print(f"  ground truth: {gt['lines']:,} lines, {len(gt['drafts'])} hero drafts, "
          f"{len(gt['rolls'])} shop refreshes (local player), "
          f"{len(gt['combat_starts'])} screen combat starts, "
          f"{len(gt['combat_ends'])} ends")
    print("  choose-one blocks: " + ", ".join(
        f"{k}={len(v)}" for k, v in gt["choices"].items()))

    manager, router, sink, secs = replay(path)
    win = {w.KEY: w for w in manager.windows}
    ev = {}
    for _, name in sink.events:
        ev[name] = ev.get(name, 0) + 1
    print(f"  replayed in {secs:.0f}s; events: "
          + ", ".join(f"{k}={v}" for k, v in sorted(ev.items())))
    print("  windows: " + ", ".join(
        f"{k}(open {w.opens}/close {w.closes}/err {w.errors})"
        for k, w in win.items()))

    ok = True

    # 1. the tavern is rebuilt on every roll ------------------------------
    tav = [ln for ln, n in sink.events if n == "tavern"]
    strict, loose = matched(tav, gt["rolls"], gt["combat_starts"])
    # The claim under test is "a refresh always rebuilds the tavern", i.e.
    # every refresh gets its own rebuild before the next one. The looser
    # "before the fight starts" figure is reported but NOT asserted: a refresh
    # in the last instant of a recruit phase (measured: 115 and 154 log lines
    # before the fight) is rebuilt once the screen is back in a tavern, which
    # is right - the tavern window is already hidden by then.
    print(f"  TAVERN: {len(gt['rolls'])} refreshes -> {len(tav)} rebuilds; "
          f"{strict} rebuilt before the next refresh, "
          f"{loose} of those before the next fight started")
    if strict < len(gt["rolls"]):
        print("    FAIL: a refresh went without a rebuild")
        ok = False
    if len(tav) < len(gt["rolls"]):
        print("    FAIL: fewer rebuilds than refreshes")
        ok = False

    # 2. combat opens and closes exactly once per fight -------------------
    c_open = [ln for ln, k in sink.opens if k == "combat"]
    c_close = [ln for ln, k in sink.closes if k == "combat"]
    with_odds = [f for f in sink.fights if f["odds"]]
    # Only a fight the screen actually finished can be judged at its close;
    # the last fight of a game ends with the game.
    judged = [f for f in sink.fights if f["odds"] and f["closed"]]
    held = [f for f in judged if f["at_close"]]
    ended_by_game = [f for f in judged if f["by"] == "game"]
    print(f"  COMBAT: {len(gt['combat_starts'])} screen fights -> "
          f"{len(c_open)} opens / {len(c_close)} closes; "
          f"odds computed for {len(with_odds)}, still shown at the closing "
          f"instant {len(held)}/{len(judged)} "
          f"({len(ended_by_game)} of those ended by the next game, "
          f"{len(sink.fights) - len(judged) - len([f for f in sink.fights if not f['odds']])}"
          f" left open at end of log)")
    if len(c_open) != len(gt["combat_starts"]):
        print("    FAIL: combat window did not open once per fight")
        ok = False
    if len(c_close) != len(gt["combat_ends"]):
        print("    FAIL: combat window did not close once per fight")
        ok = False
    if len(held) != len(judged):
        print("    FAIL: odds vanished mid-fight")
        ok = False

    # 3. each pick window fires only for its own kind ---------------------
    pairs = [("heropick", "hero", "hero"), ("trinkets", "trinket", "trinket"),
             ("heropower", "heropower", "heropower"),
             ("discover", "discover", "discover")]
    for key, event, kind in pairs:
        got = ev.get(event, 0)
        expect = len(gt["drafts"]) if key == "heropick" else len(gt["choices"][kind])
        print(f"  {key.upper()}: {expect} {kind} moments in the log -> "
              f"{got} events, {win[key].opens} opens")
        if win[key].opens > got:
            print("    FAIL: opened more often than it was told to")
            ok = False

    # 4. the shared left band belongs to one window at a time ---------------
    clashes = [d for d in sink.drafts if d[0] and d[1]]
    print(f"  SESSION: {len(sink.drafts)} drafts -> stepped aside for all but "
          f"{len(clashes)}; back up {win['session'].opens - 1} times after the "
          f"draft ended")
    if clashes:
        print("    FAIL: session sat under the hero draft")
        ok = False

    # 5. the counters the game writes about YOU ----------------------------
    ok = counters_check(path) and ok

    # structural: no window ever saw an event it did not declare
    for w in manager.windows:
        seen = {n for n, ws in router.by_event.items() if w in ws}
        if not seen <= set(w.EVENTS):
            print(f"    FAIL: {w.KEY} received something it never declared")
            ok = False
        if w.errors:
            print(f"    FAIL: {w.KEY} raised {w.errors} times")
            ok = False
    manager.root.destroy()
    return render_check(sink.sample) and ok


def counters_check(path: Path) -> bool:
    """Replay the log through the COUNTERS parser alone.

    The strip does not come through the reader: every number on it is a tag
    Hearthstone writes about the local player, so it is proved the same way -
    by replaying the real log and counting how often each counter was actually
    stated. A counter that never moves is a counter that is not wired.
    """
    state = CounterState()
    seen = {"turn": 0, "gold": 0, "tier": 0, "upgrade": 0, "extra": 0,
            "buffs": 0, "free_rolls": 0, "triples": 0, "trinket": 0}
    last = {k: None for k in seen}
    restarts, last_turn = 0, 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not state.feed(line):
                continue
            now = {"turn": state.bg_turn, "gold": state.gold, "tier": state.tier,
                   "upgrade": state.next_cost, "extra": state.extra_next,
                   "buffs": (state.elem_atk, state.elem_hp, state.gem_atk,
                             state.gem_hp),
                   "free_rolls": state.free_rolls, "triples": state.triples,
                   "trinket": tuple(sorted(state.trinket_in.items()))}
            for k, v in now.items():
                if v != last[k] and v not in (None, 0, (0, 0, 0, 0), ()):
                    seen[k] += 1
                last[k] = v
            turn = state.bg_turn
            if turn:
                if turn < last_turn:
                    restarts += 1               # the turn counter went back: a
                last_turn = turn                # new game
    print("  COUNTERS: " + ", ".join(f"{k}={v}" for k, v in seen.items())
          + f" (changes; {restarts + 1} games)")
    ok = True
    if not seen["turn"] or not seen["gold"] or not seen["tier"]:
        print("    FAIL: the strip's three permanent counters never moved")
        ok = False
    if not seen["upgrade"]:
        print("    FAIL: the live tavern-up price never resolved")
        ok = False
    # A blank state must draw nothing rather than a screen full of zeroes.
    if CounterState().known():
        print("    FAIL: an empty counter state claims it has numbers")
        ok = False
    return ok


def layout_check() -> bool:
    """No two windows cover each other in the default stack.

    Each window claims RESERVE pixels from its own DY down one edge of the game
    window. Overlap is a layout bug that no amount of runtime logic can fix, so
    it is checked as geometry - on the real class attributes, at their real
    widths, inside a real 1920x1080 game rect.
    """
    print("\n=== layout (1920x1080 game window)")
    ok = True
    for col in ("right", "left"):
        ws = sorted((w for w in ui.WINDOWS if w.COLUMN == col), key=lambda w: w.DY)
        print(f"  {col}: " + " ".join(
            f"{w.KEY}[{w.DY}-{w.DY + w.RESERVE}]" for w in ws))
        for a, b in zip(ws, ws[1:]):
            if a.DY + a.RESERVE > b.DY:
                if frozenset((a.KEY, b.KEY)) in SHARED_BANDS:
                    continue          # documented, and only one is ever open
                print(f"    FAIL: {a.KEY} overlaps {b.KEY}")
                ok = False
        tallest = max(w.DY + w.MAX_H for w in ws)
        if tallest > 1080 - 8:
            print(f"    FAIL: {col} column reaches {tallest}px, past the window")
            ok = False
    return ok


def render_check(sample):
    """Actually PAINT every window with real payloads from the replay.

    The headless pass proves the lifecycle; it never calls draw(). A crash in
    draw() is the failure that once left the overlay "visible" per heartbeat
    while it had silently stopped repainting, so every window gets its canvas
    built here and counted. Nothing is mapped to the screen: the manager's
    focus poll is never started, so game_front stays False.
    """
    manager = WindowManager(ui.WINDOWS, names_fn=bg.card_names,
                            pos_file=POS_FILE)
    router = overlay.Router(manager.windows)
    for name, payload in sample.items():
        router.dispatch(name, payload)
    ok = True
    parts = []
    for w in manager.windows:
        # Did this log actually give this window something to draw? If the
        # sample left it open, its own trigger fired and it has content.
        fed = w.is_open
        if not w.is_open:
            w.show()          # force a paint even for windows nothing opened
        items = len(w.canvas.find_all())
        # Each window's height is capped to its reserved band so it can never
        # spill onto its neighbour. Check the cap is not actually clipping
        # anything: nothing drawn may sit below the panel's own bottom edge.
        box = w.canvas.bbox("all")
        spill = max(0, (box[3] if box else 0) - w._h)
        parts.append(f"{w.KEY}={items}"
                     + (f" CLIPPED by {spill}px" if spill > 2 else "")
                     + ("" if fed else " (empty state)"))
        if items < (5 if fed else 1) or w.errors or spill > 2:
            ok = False
    print("  RENDER: " + ", ".join(parts))
    if not ok:
        print("    FAIL: a window painted nothing or raised while drawing")
    manager.root.destroy()
    return ok


def main(argv):
    logs = [Path(a) for a in argv[1:]]
    if not logs:
        newest = bg.newest_power_log()
        if not newest:
            print("SKIP: no Power.log on this machine")
            return 0
        logs = [newest]
    POS_FILE.unlink(missing_ok=True)      # never resume a previous run's state
    ok = layout_check()
    ok = all([check(p) for p in logs]) and ok
    POS_FILE.unlink(missing_ok=True)
    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
