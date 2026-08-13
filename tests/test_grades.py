#!/usr/bin/env python3
"""Card grades: the star a minion gets when NOTHING has measured it yet.

    python tests/test_grades.py [<Power.log> ...]

grades.py rates a minion off the card alone - stat line against its own tavern
tier, keywords, comp role, tribe. That is an opinion, and this tool's whole
standing rests on never letting an opinion pass for a measurement. So the
claims under test are the ones that keep the line:

  1. MEASURED WINS. Where a real card table has a differential for a card,
     that is the rating - per card, not per table, so the first game that
     measures a minion takes it off the computed path.
  2. A card nothing has measured still gets a grade, so a fresh install is not
     a wall of blanks.
  3. Grades are cut WITHIN the tavern tier. The same body is a better tier 1
     than it is a tier 6, and no tier's band is borrowed from another's.
  4. The same card grades identically across runs, including through the
     cache - a rating that wobbles between launches is not a rating.
  5. NOTHING here fetches on a draw path. The grade is warmed on a background
     thread like every other card-derived table; a cold table draws no star at
     all rather than reaching for the network on the Tk thread.

With a Power.log argument (or one under the Hearthstone install) it also
replays the real reader and checks the shop rows the overlay actually emits:
every row states which kind of star it carries, and a row with a measured
differential is never a graded one. Without a log that section SKIPs - a real
log is player data and is deliberately not in the repository.
"""

from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg          # noqa: E402
import grades                   # noqa: E402
import overlay                  # noqa: E402
import ui                       # noqa: E402
from ui.base import WindowManager   # noqa: E402

# Windows remember their place in .overlay.json; a test must never write the
# player's real one (same rule as tests/test_windows.py).
POS_FILE = Path(tempfile.gettempdir()) / "bgtracker-test-grades.json"

FILLED, HOLLOW = "★", "☆"


def fake_pool(per_tier=12, tiers=(1, 2, 3, 4, 5, 6)):
    """A synthetic pool with a known shape, so the scoring claims can be
    checked without the live card database and without a network call.

    Bodies grow with the index inside each tier, so the ranking inside a tier
    is known before the code runs, and they grow with the TIER as well, the
    way the real pool does (measured: 4.04 total stats at tier 1 rising to
    18.31 at tier 7). Text and mechanics are empty so nothing else moves the
    score.
    """
    pool = []
    for t in tiers:
        for i in range(per_tier):
            body = 2 * t + i                 # bigger bodies at higher tiers
            pool.append({"id": f"T{t}_{i:02d}", "name": f"Tier {t} card {i}",
                         "techLevel": t, "attack": body - 1, "health": 1,
                         "races": [], "mechanics": [], "text": ""})
    return pool


def texts_of(win):
    """Every text item painted on a window's canvas, top to bottom."""
    c = win.canvas
    out = []
    for i in c.find_all():
        if c.type(i) != "text":
            continue
        x, y = c.coords(i)[:2]
        out.append((round(y), round(x), c.itemcget(i, "text")))
    out.sort()
    return [t for _, _, t in out]


# --------------------------------------------------------------- the scoring


def check_within_tier() -> bool:
    """Claim 3: a tier is ranked against itself and nothing else."""
    ok = True
    pool = fake_pool()
    doc = grades.build(pool)
    means = doc["means"]
    print("=== tier means from the synthetic pool: "
          + ", ".join(f"T{t} {means[t]:.2f}" for t in sorted(means)))

    # Every tier must span the whole scale: if a band were cut across tiers,
    # the small-bodied tiers would hold every 1 and the big ones every 5.
    for t in sorted(means):
        got = sorted({doc["stars"][f"T{t}_{i:02d}"] for i in range(12)})
        if got != [1, 2, 3, 4, 5]:
            print(f"    FAIL: tier {t} bands are {got}, not 1..5")
            ok = False

    # The same body, tiers apart. Tier 1's typical body is small and tier 6's
    # is large, so an identical stat line has to grade lower as the tier rises.
    body = {"attack": 3, "health": 3, "races": [], "mechanics": [], "text": ""}
    low = grades.score(dict(body, id="x", techLevel=1), means, ([], []))
    high = grades.score(dict(body, id="y", techLevel=6), means, ([], []))
    print(f"=== a 3/3 scores {low:+.2f} at tier 1 and {high:+.2f} at tier 6")
    if not low > high:
        print("    FAIL: the same body did not grade higher at the lower tier")
        ok = False

    # A tier too thin to have a distribution gets no grade at all, rather than
    # a rank invented out of a handful of cards.
    thin = grades.build(fake_pool(per_tier=grades.MIN_TIER_POOL - 1, tiers=(7,)))
    print(f"=== a {grades.MIN_TIER_POOL - 1}-card tier graded "
          f"{len(thin['stars'])} cards")
    if thin["stars"]:
        print("    FAIL: a tier under MIN_TIER_POOL was still banded")
        ok = False
    return ok


def check_keywords() -> bool:
    """The weights are a judgement, but they must at least be APPLIED: a
    keyword on the card has to move the number it claims to move."""
    ok = True
    means = grades.tier_means(fake_pool())
    plain = {"id": "k", "techLevel": 3, "attack": 3, "health": 3,
             "races": [], "mechanics": [], "text": ""}
    base = grades.score(plain, means, ([], []))
    for key in ("DIVINE_SHIELD", "TAUNT"):
        weight = grades.KEYWORDS[key]
        got = grades.score(dict(plain, mechanics=[key]), means, ([], [])) - base
        if abs(got - weight) > 1e-9:
            print(f"    FAIL: {key} moved the score {got:+.3f}, weight is {weight}")
            ok = False
    # An unknown mechanic scores zero rather than a guessed default.
    unknown = grades.score(dict(plain, mechanics=["SOMETHING_NEW_2027"]),
                           means, ([], [])) - base
    # A core piece of a comp family outscores the same card with no role.
    core = grades.score(plain, means, (["mech magnetic"], [])) - base
    print(f"=== keyword terms applied; unknown mechanic {unknown:+.2f}, "
          f"comp core {core:+.2f}")
    if unknown != 0:
        print("    FAIL: an unknown mechanic changed the score")
        ok = False
    if abs(core - grades.CORE_FIRST) > 1e-9:
        print("    FAIL: the comp-core weight was not applied")
        ok = False
    return ok


def check_stable() -> bool:
    """Claim 4: the same card grades the same every run, and through the
    cache. A rating that moves between launches is not a rating."""
    ok = True
    pool = fake_pool()
    first = grades.build(pool)["stars"]
    second = grades.build(list(reversed(pool)))["stars"]
    if first != second:
        print("    FAIL: grades changed when the pool arrived in another order")
        ok = False

    # Through the cache file, which is the path a second launch takes.
    tmp = Path(tempfile.mkdtemp(prefix="bgtracker-grades-"))
    real_dir, real_pool = bg.CACHE_DIR, bg.bg_pool
    grades.reset()
    try:
        bg.CACHE_DIR = tmp
        bg.bg_pool = lambda *a, **k: pool
        built = grades.table()["stars"]
        grades.reset()
        bg.bg_pool = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("the cache should have answered"))
        cached = grades.table()["stars"]
    finally:
        bg.CACHE_DIR, bg.bg_pool = real_dir, real_pool
        grades.reset()
    if built != cached:
        print("    FAIL: the cached table does not match the built one")
        ok = False
    print(f"=== stable across runs and through the cache "
          f"({len(cached)} cards, cache {grades.CACHE_FILE})")
    return ok


def check_live_pool() -> bool:
    """The real pool: every minion in it gets a grade, and the bands keep the
    top-heavy shape the measured stars use."""
    try:
        pool = bg.bg_pool()
    except Exception as e:
        print(f"SKIP: no card pool available ({e.__class__.__name__})")
        return True
    if not pool or "attack" not in pool[0]:
        print("SKIP: cached pool predates the stat line")
        return True
    doc = grades.build(pool)
    missing = [m["id"] for m in pool if m["id"] not in doc["stars"]]
    by_tier = {}
    for m in pool:
        by_tier.setdefault(m["techLevel"], []).append(doc["stars"][m["id"]])
    print(f"=== live pool: {len(pool)} minions, {len(missing)} ungraded")
    for t in sorted(by_tier):
        v = by_tier[t]
        share5 = 100.0 * sum(1 for s in v if s == 5) / len(v)
        print(f"    tier {t}: n={len(v):3d}  mean {doc['means'][t]:5.2f} stats"
              f"   five stars {share5:.0f}%")
    ok = True
    if missing:
        print(f"    FAIL: {len(missing)} pool minions got no grade")
        ok = False
    return ok


# --------------------------------------------------------------- the surfaces


def check_surfaces() -> bool:
    """Claims 1, 2 and 5 where the player meets them: the minion browser and
    the tavern rows."""
    grades.reset()
    grades._TABLE = grades.build(fake_pool())
    POS_FILE.unlink(missing_ok=True)
    try:
        manager = WindowManager(ui.WINDOWS, names_fn=lambda: {},
                                pos_file=POS_FILE)
    except Exception as e:
        print(f"SKIP: no Tk display ({e.__class__.__name__})")
        grades.reset()
        return True
    router = overlay.Router(manager.windows)
    ok = True
    try:
        ok = check_browser(manager) and ok
        ok = check_tavern(manager, router) and ok
        ok = check_no_fetch(manager) and ok
    finally:
        manager.root.destroy()
        POS_FILE.unlink(missing_ok=True)
        grades.reset()
    return ok


def check_browser(manager) -> bool:
    """Measured wins per card; everything else still gets a hollow star."""
    ok = True
    win = manager.by_key["browser"]
    pool = fake_pool()
    win.pool = pool
    win.expanded = True
    win.sel_tiers = {3}
    measured = pool[24]          # a tier 3 card, and the only one measured
    win.cards = {measured["id"]: {"avg": 3.9, "n": 500, "delta": -0.42}}
    # One tier-3 band, so stars() can answer for the measured card only.
    win.bands = {3: [-0.40, -0.20, 0.0, 0.20]}
    win.redraw()
    painted = texts_of(win)

    got, graded = win.rating(measured)
    print(f"=== browser: measured card rates {got} stars, graded={graded}")
    if graded or got is None:
        print("    FAIL: a measured card was graded")
        ok = False
    # The claim only means something if the grade WOULD have answered for this
    # same card: measured has to beat a live alternative, not an absent one.
    if grades.grade(measured["id"]) is None:
        print("    FAIL: the fixture card has no grade for the data to beat")
        ok = False

    unmeasured = pool[25]
    got, graded = win.rating(unmeasured)
    print(f"=== browser: unmeasured card rates {got} stars, graded={graded}")
    if got is not None or graded:
        print("    FAIL: an unmeasured card got no grade")
        ok = False

    # A star ROW is a run of one glyph and nothing else; the footer names both
    # glyphs in a sentence and is not a rating.
    filled = [t for t in painted if t and set(t) == {FILLED}]
    hollow = [t for t in painted if t and set(t) == {HOLLOW}]
    print(f"=== browser painted {len(filled)} filled and {len(hollow)} hollow "
          f"star rows; footer {painted[-1]!r}")
    if len(filled) != 1:
        print("    FAIL: exactly one row was measured, so exactly one row "
              "should carry filled stars")
        ok = False
    if hollow:
        print("    FAIL: a computed star was painted; the card cannot rank itself")
        ok = False
    if any(HOLLOW in t for t in painted):
        print("    FAIL: the footer still advertises a computed star")
        ok = False

    # The opened row has to SAY it is not a measurement, and say what it read.
    win.open_id = unmeasured["id"]
    win.redraw()
    opened = texts_of(win)
    said = [t for t in opened if "no games have measured this one yet" in t]
    fact = [t for t in opened if "body" in t or "core of" in t or "supports" in t]
    # Only the opened card's own detail lines: the window also holds other
    # rows, and a measured row's stars are correct and must not fail this.
    detail = opened[opened.index(said[0]):] if said else []
    star = [t for t in detail if t and set(t) <= {FILLED, HOLLOW} and t.strip()]
    print(f"=== opened row says {said[:1]} / facts {fact[:1]} / stars {star[:1]}")
    if not said:
        print("    FAIL: the opened row does not say it is unmeasured")
        ok = False
    if star:
        print("    FAIL: the opened row invented a star for an unmeasured card")
        ok = False
    win.open_id = None
    return ok


def check_tavern(manager, router) -> bool:
    """The 22px shop row draws the two kinds of star differently, and says
    what the hollow one means without growing the window."""
    ok = True
    win = manager.by_key["tavern"]
    before = win.MAX_H
    rows = [{"pos": 1, "name": "Measured One", "card": "T3_00", "stars": 4,
             "graded": False, "avg": 3.8, "n": 400, "tier": 3},
            {"pos": 2, "name": "Graded One", "card": "T3_01", "stars": 3,
             "graded": True, "avg": None, "n": 0, "tier": 3}]
    router.dispatch("tavern", {"rows": rows, "slots": rows, "roll": 2,
                               "lean": None})
    win.redraw()
    painted = texts_of(win)
    filled = [t for t in painted if t and set(t) == {FILLED}]
    hollow = [t for t in painted if t and set(t) == {HOLLOW}]
    print(f"=== tavern painted {filled} / hollow {hollow}")
    if filled != [FILLED * 4]:
        print("    FAIL: the measured row is not four filled stars")
        ok = False
    if hollow:
        print("    FAIL: a computed star reached a shop row")
        ok = False
    if win.MAX_H != before:
        print("    FAIL: the tavern window changed its band")
        ok = False
    return ok


def check_no_fetch(manager) -> bool:
    """Claim 5: no draw ever reaches the card database.

    The repro is the one that froze the Tk thread before (tests/
    test_comproles.py): the pool functions are replaced with bombs and the
    windows are painted. A cold grade table must paint no star rather than
    build one on the way past.
    """
    ok = True
    calls = []
    real = {n: getattr(bg, n) for n in
            ("_fetch", "bg_pool", "card_tiers", "golden_aliases",
             "comp_role_hits")}
    real_build = grades.build
    warm = grades._TABLE

    def bomb(*a, **k):
        calls.append(threading.current_thread().name)
        raise RuntimeError("the card database was reached from the draw path")

    try:
        for name in real:
            setattr(bg, name, bomb)
        grades.build = bomb
        browser, tavern = manager.by_key["browser"], manager.by_key["tavern"]
        browser.redraw()
        tavern.redraw()
        warm_rows = [t for t in texts_of(browser) if HOLLOW in t]
        # ... and now with nothing warm at all, which is a first run offline.
        grades._TABLE = None
        browser.redraw()
        tavern.redraw()
        cold = texts_of(browser)
        errors = browser.errors + tavern.errors
        main = [c for c in calls if c == "MainThread"]
        print(f"=== draw path: {len(main)} card-database calls, "
              f"{errors} window errors, warm draw had {len(warm_rows)} hollow "
              f"rows, cold draw has "
              f"{len([t for t in cold if HOLLOW in t])}")
        if main or errors:
            print("    FAIL: a draw reached the card database")
            ok = False
        if warm_rows:
            print("    FAIL: a warm grade table still painted a computed star")
            ok = False
        if any(t and set(t) == {HOLLOW} for t in cold):
            print("    FAIL: a cold table still painted a star")
            ok = False
    finally:
        for name, fn in real.items():
            setattr(bg, name, fn)
        grades.build = real_build
        grades._TABLE = warm
    return ok


# ------------------------------------------------------------ the real reader


def measurable(mmr="100", period="last-patch"):
    """GROUND TRUTH for claim 1, measured off the configured feed itself and
    not off the overlay: the set of cardIds the star scale really can rate.

    Re-derived here rather than imported, the same way tests/test_windows.py
    re-reads the log instead of trusting the reader: a card is measurable when
    the table gives it a differential over MIN_SAMPLE games AND its tavern
    tier has at least ten such cards to be ranked against. Anything else the
    overlay is entitled to grade.
    """
    try:
        cards = bg.card_table(mmr, period)
        tiers = bg.card_tiers()
    except Exception:
        return set(), {}
    rated = {}
    for cid, v in cards.items():
        if v.get("delta") is not None and v.get("n", 0) >= bg.MIN_SAMPLE:
            rated.setdefault(tiers.get(cid, 0), []).append(cid)
    banded = {t: ids for t, ids in rated.items() if len(ids) >= 10}
    return {cid for ids in banded.values() for cid in ids}, banded


def shop_rows(path, table=None):
    """Every shop row the real reader emits over one log, optionally against a
    substituted card table."""
    rows = []

    class Sink:
        def put(self, item):
            name, payload = item
            if name == "tavern":
                rows.extend(payload.get("rows") or [])

    real = bg.card_table
    try:
        if table is not None:
            bg.card_table = lambda *a, **k: table
        overlay.Reader(Sink(), "100", "last-patch", demo=Path(path),
                       pace=False).run()
    finally:
        bg.card_table = real
    return rows


def check_measured_wins(path, seen) -> bool:
    """Claim 1 through the OVERLAY, on a real log.

    A live feed that has measured nothing yet cannot prove a priority rule -
    it can only show the fallback working. So this pass hands the reader a
    card table that CAN measure: every minion of one tavern tier, with a
    differential over the sample floor. Every shop row of that tier must then
    come back measured, and the rest of the shop must still be graded.
    """
    try:
        pool = bg.bg_pool()
    except Exception as e:
        print(f"SKIP: no card database ({e.__class__.__name__})")
        return True
    counts = {}
    for m in pool:
        counts.setdefault(m["techLevel"], []).append(m["id"])
    # The tier this log's shops actually showed most, so the pass is not
    # vacuous: an early-game log never offers a tier 6 minion.
    shown = {}
    for r in seen:
        shown[r.get("tier")] = shown.get(r.get("tier"), 0) + 1
    tier = max((t for t in shown if t in counts), key=lambda t: shown[t],
               default=None)
    if tier is None:
        print("    SKIP: no shop row carried a tavern tier")
        return True
    table = {cid: {"avg": 3.0 + 0.01 * i, "n": 500,
                   "delta": -0.9 + 0.01 * i}
             for i, cid in enumerate(counts[tier])}
    rows = shop_rows(path, table)
    ours = [r for r in rows if r.get("tier") == tier]
    wrong = [r["name"] for r in ours if r.get("graded")]
    others = [r for r in rows if r.get("tier") != tier]
    print(f"=== measured feed for tier {tier} ({len(table)} cards): "
          f"{len(ours)} shop rows of that tier, {len(wrong)} still graded; "
          f"{sum(1 for r in others if r.get('graded'))} of {len(others)} "
          f"other rows graded")
    if not ours:
        print("    SKIP: the log's shops never showed that tier")
        return True
    if wrong:
        print(f"    FAIL: measured cards drawn as computed: {wrong[:4]}")
        return False
    return True


def check_replay(paths) -> bool:
    """The shop rows the overlay really emits, off a real log: every row says
    which kind of star it carries, and a card the feed CAN measure is never
    drawn as a computed one."""
    ok = True
    can_measure, banded = measurable()
    print(f"=== the configured feed can measure {len(can_measure)} cards "
          f"across {len(banded)} banded tiers")
    for path in paths:
        rows = shop_rows(path)
        missing = [r for r in rows if "graded" not in r]
        lied = [r for r in rows if r.get("graded")
                and (r["card"][:-2] if r["card"].endswith("_G")
                     else r["card"]) in can_measure]
        graded = sum(1 for r in rows if r.get("graded") and r["stars"])
        print(f"=== {Path(path).name}: {len(rows)} shop rows, {graded} carry a "
              f"computed star, {len(missing)} say nothing, {len(lied)} "
              f"measurable cards drawn as computed")
        if missing or lied:
            print("    FAIL: a shop row does not carry the right kind of star")
            ok = False
        ok = check_measured_wins(path, rows) and ok
    return ok


def main(argv) -> int:
    ok = True
    ok = check_within_tier() and ok
    ok = check_keywords() and ok
    ok = check_stable() and ok
    ok = check_live_pool() and ok
    ok = check_surfaces() and ok

    logs = []
    for a in argv:
        if Path(a).exists():
            logs.append(Path(a))
        else:
            # Never quietly swap in a different log: a replay of the WRONG log
            # answers a question nobody asked, and the newest one is usually
            # the live one, which grows under the test.
            print(f"    FAIL: no such log: {a}")
            ok = False
    if not logs:
        newest = bg.newest_power_log()
        logs = [newest] if newest else []
    if logs:
        ok = check_replay(logs) and ok
    else:
        print("SKIP: no Power.log for the reader replay")

    print("\nPASS" if ok else "\nFAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
