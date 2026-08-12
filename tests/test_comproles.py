#!/usr/bin/env python3
"""Comp core/add-on regression: the roles file, the computed difficulty, and
the COMPS window actually PAINTING the split on both of its paths.

The claim under test is the honest one the feature makes:

  1. data/comp_roles.json parses, and every family it names is a real
     COMP_FAMILIES archetype - a role for a family that does not exist would
     never be reachable and would rot silently;
  2. difficulty is COMPUTED from the live pool (tier / pieces / locked per
     bgtracker.comp_difficulty) and lands in the promised range - never an
     authored grade;
  3. the CURATED path (a fresh install, zero stats configured) draws the
     CORE / ADD-ONS split with the filled marker on core rows;
  4. the STATS path (a real aggregator feed) draws the same split, with the
     board frequencies still on the rows;
  5. a comp no roles entry covers draws the flat list this window always
     drew - never a guessed split.

Usage:
    python tests/test_comproles.py

Needs the cached card pool (.cache/bgpool.json, written by any prior run) or
a network connection; with neither it SKIPs (exit 0) like the other tests.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import threading                # noqa: E402

import bgtracker as bg          # noqa: E402
import overlay                  # noqa: E402
import ui                       # noqa: E402
import ui.comps as uicomps      # noqa: E402
from ui.base import WindowManager   # noqa: E402

# Windows remember their place in .overlay.json; a test must never write the
# player's real one (same rule as tests/test_windows.py).
POS_FILE = Path(tempfile.gettempdir()) / "bgtracker-test-comproles.json"


def texts_of(win):
    """Every text item on the window's canvas as (y, x, text), top to
    bottom - the painted truth, not what the code intended to paint."""
    c = win.canvas
    out = []
    for i in c.find_all():
        if c.type(i) != "text":
            continue
        x, y = c.coords(i)[:2]
        out.append((round(y), round(x), c.itemcget(i, "text")))
    out.sort()
    return out


def open_comp(manager, router, comps, archetype, tribes):
    """Feed the window one lobby and expand one comp, exactly as a click
    would."""
    win = manager.by_key["comps"]
    win.reset()
    router.dispatch("lobby", {"seen": tribes, "exact": True,
                              "comps": comps, "all": comps})
    win.open_key = archetype
    win.redraw()
    return win


def check_split(win, comp, label):
    """The painted canvas must carry the split comp_role_split computed."""
    split = bg.comp_role_split(comp)
    if split is None:
        print(f"    FAIL: {label}: no split computed for {comp['archetype']}")
        return False
    rows = texts_of(win)
    print(f"  {label}: {comp['archetype']} expanded, painted rows:")
    for y, x, t in rows:
        print(f"    y={y:<4} x={x:<4} {t!r}")
    ok = True
    core_ys = [y for y, _, t in rows if t == "CORE"]
    addon_ys = [y for y, _, t in rows if t == "ADD-ONS"]
    if not core_ys:
        print("    FAIL: no CORE section painted")
        return False
    core_y = core_ys[0]
    addon_y = addon_ys[0] if addon_ys else float("inf")
    shown_core = split["core"][:6 if split["addons"] else 8]
    if split["addons"] and not addon_ys:
        print("    FAIL: add-ons exist but no ADD-ONS section painted")
        ok = False
    if core_y >= addon_y:
        print("    FAIL: ADD-ONS painted above CORE")
        ok = False
    marks = [y for y, _, t in rows if t == "●"]
    if len(marks) != len(shown_core):
        print(f"    FAIL: {len(shown_core)} core rows but {len(marks)} "
              "filled markers")
        ok = False
    for nm in shown_core:
        hits = [y for y, _, t in rows if t == nm[:24] and core_y < y < addon_y]
        if not hits:
            print(f"    FAIL: core minion {nm!r} not painted in the CORE band")
            ok = False
    diff = split["difficulty"]
    if diff:
        words = [t for _, _, t in rows if t == diff["word"]]
        if "difficulty" not in [t for _, _, t in rows] or not words:
            print(f"    FAIL: difficulty {diff['word']!r} computed but "
                  "not painted")
            ok = False
    return ok


def _synth_feed():
    """A comps feed in the aggregator's exact shape, built from the live pool
    so it is always this patch's cards: one mech archetype whose boards run
    the magnetic core plus support."""
    pool = bg.bg_pool()
    mech = [m for m in pool if "MECHANICAL" in m["races"]]
    core = [m for m in mech if "MAGNETIC" in m["mechanics"]][:3]
    rest = [m for m in mech if m not in core][:4]
    board = [{"cardID": m["id"]} for m in core + rest]
    return {"compStats": [{
        "archetype": "mech_magnet", "averagePlacement": 3.9,
        "dataPoints": 5000,
        "heroStats": [{"finalBoards":
                       [{"finalComp": {"board": board}}] * 40}]}]}


def stats_rows():
    """Comp rows through the REAL comp_table parser, fed a real cached
    aggregator file when one exists, else a feed built from the live pool -
    the shape is the aggregator's either way, so the parser is exercised, not
    bypassed. A cached feed that parses to zero measured rows (stale shape,
    stripped averages) falls through to the synthetic one instead of failing
    the test for the wrong reason."""
    import json
    feeds = []
    cached = bg.CACHE_DIR / "comps-last-patch.json"
    if cached.exists():
        try:
            doc = json.loads(cached.read_text(encoding="utf-8"))
            if doc.get("compStats"):
                feeds.append(doc)
        except Exception:
            pass
    feeds.append(_synth_feed())
    real = bg.load_bucket
    try:
        for feed in feeds:
            bg.load_bucket = lambda *a, **k: feed
            rows = bg.comp_table("last-patch", "100")
            if any(not c.get("baseline") for c in rows):
                return rows
        return rows
    finally:
        bg.load_bucket = real


def main():
    try:
        pool = bg.bg_pool()
    except Exception:
        print("SKIP: no cached card pool and no network")
        return 0
    ok = True

    # 1. every roles family is a real archetype --------------------------
    roles = bg.comp_roles()
    family_ids = {f[1] for f in bg.COMP_FAMILIES}
    stray = set(roles) - family_ids
    print(f"=== roles file: {len(roles)} families "
          f"({len(family_ids)} in COMP_FAMILIES)")
    if not roles:
        print("    FAIL: data/comp_roles.json produced no families")
        ok = False
    if stray:
        print(f"    FAIL: roles for archetypes that do not exist: {stray}")
        ok = False

    # 2. difficulty is computed and in range ------------------------------
    graded = 0
    for arch, entry in roles.items():
        tribe = entry["tribes"][0] if entry["tribes"] else None
        d = bg.comp_difficulty(arch, tribe)
        if d is None:
            print(f"  {arch:22s} no core piece in this patch's pool")
            continue
        graded += 1
        print(f"  {arch:22s} {d['word']:6s} core ~t{d['tier']:.2f} "
              f"{d['pieces']:2d} pieces locked={d['locked']}")
        if (d["word"] not in ("easy", "medium", "hard")
                or not 1 <= d["tier"] <= 7 or d["pieces"] < 1):
            print("    FAIL: difficulty out of range")
            ok = False
    if not graded:
        print("    FAIL: no family got a computed difficulty")
        ok = False

    # 3 + 4 + 5: the window paints it, on both paths ----------------------
    POS_FILE.unlink(missing_ok=True)
    manager = WindowManager(ui.WINDOWS, names_fn=bg.card_names,
                            pos_file=POS_FILE)
    router = overlay.Router(manager.windows)
    try:
        # curated path: what a fresh install with zero stats sees
        curated = bg.comp_families()
        target = next((c for c in curated
                       if bg.comp_role_split(c) is not None), None)
        print(f"\n=== curated path: {len(curated)} families")
        if target is None:
            print("    FAIL: no curated family has a role split")
            ok = False
        else:
            # 0. COLD DRAW NEVER FETCHES. The split reads the card pool, and a
            # cold pool cache means a network fetch - which froze the Tk
            # thread when draw() was the caller. Repro re-run: the pool
            # functions are replaced with bombs, the warmup is forced cold,
            # and the window is opened and painted. The paint must finish
            # (flat list, no split) with ZERO pool calls from this thread;
            # the warm thread the lobby event spawns is allowed to bomb.
            calls = []
            real_pool, real_by_name = bg.bg_pool, bg.pool_by_name

            def bomb(*a, **k):
                calls.append(threading.current_thread().name)
                raise RuntimeError("card pool reached from the draw path")

            t0 = uicomps._warm["thread"]   # the warmup the manager started
            if t0 is not None:
                t0.join()                  # let it finish with the REAL pool,
            was_ok = uicomps._warm["ok"]   # or it could flip the state mid-test
            bg.bg_pool = bg.pool_by_name = bomb
            uicomps._warm["ok"] = False
            uicomps._warm["thread"] = None
            try:
                tribes = {target["tribe"]} if target["tribe"] else set()
                win = open_comp(manager, router, [target],
                                target["archetype"], tribes)
                painted = [t for _, _, t in texts_of(win)]
                main_calls = [c for c in calls if c == "MainThread"]
                print(f"=== cold draw: window errors={win.errors}, pool calls "
                      f"from the Tk thread={len(main_calls)}, painted "
                      f"{len(painted)} items, split shown="
                      f"{'CORE' in painted}")
                if win.errors or main_calls:
                    print("    FAIL: the draw path reached the card pool "
                          "(a blocking fetch on the Tk thread)")
                    ok = False
                if "CORE" in painted:
                    print("    FAIL: a split was painted with no warm pool - "
                          "where did it come from?")
                    ok = False
            finally:
                bg.bg_pool, bg.pool_by_name = real_pool, real_by_name
                uicomps._warm["ok"] = was_ok

            # From here on the warmed state is the one under test - the state
            # a running overlay reaches moments after start.
            uicomps.warm_comp_roles(wait=True)
            if not uicomps._warm["ok"]:
                print("    FAIL: the role warmup did not complete")
                ok = False
            win = open_comp(manager, router, [target],
                            target["archetype"], tribes)
            ok = check_split(win, target, "no-stats") and ok

        # stats path: real feed shape through the real parser
        rows = stats_rows()
        target = next((c for c in rows if not c.get("baseline")
                       and bg.comp_role_split(c) is not None), None)
        print(f"\n=== stats path: {len(rows)} rows from comp_table")
        if target is None:
            print("    FAIL: no stats row has a role split")
            ok = False
        else:
            tribes = {target["tribe"]} if target["tribe"] else set()
            win = open_comp(manager, router, [target],
                            target["archetype"], tribes)
            ok = check_split(win, target, "stats") and ok
            got_freq = any(t.endswith("%") for _, _, t in texts_of(win))
            if target.get("freq") and not got_freq:
                print("    FAIL: stats row has frequencies but none painted")
                ok = False

        # a comp no roles entry covers: the flat list, never a guessed split
        names = [m["name"] for m in pool[:6]]
        fake = {"archetype": "back_to_back", "tribe": None, "avg": 4.1,
                "n": 9999, "key": names[:4], "key_wide": names, "freq": {}}
        assert bg.comp_role_split(fake) is None
        win = open_comp(manager, router, [fake], "back_to_back", set())
        rows_painted = texts_of(win)
        flat = [t for _, _, t in rows_painted if t in
                {n[:24] for n in names}]
        print(f"\n=== no-roles comp: painted {len(flat)} flat minion rows")
        if any(t in ("CORE", "ADD-ONS") for _, _, t in rows_painted):
            print("    FAIL: a comp without a roles entry got a split")
            ok = False
        if len(flat) < len(names):
            print("    FAIL: the flat list lost rows")
            ok = False
    finally:
        manager.root.destroy()
        POS_FILE.unlink(missing_ok=True)

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
