#!/usr/bin/env python3
"""The badge strips: where they land, that they still let clicks through, and
the two card-data readings that ride on them.

Four claims, each measured rather than asserted:

  1. THE DISCOVER SLOTS ARE CALIBRATED, not guessed. The fractions in
     ui/base.SLOT_X["choice"] are checked against the card rectangles measured
     off a live three-option Choose-One frame, and the old guessed spacing is
     scored on the same frame so the difference is a number, not an opinion.
  2. THE GAME STILL GETS THE CLICKS. WS_EX_TRANSPARENT is read back out of
     Win32 - before, during and after calibrate mode - because that property
     is the entire reason the strips are allowed to exist, and calibrate mode
     is the one thing in the overlay that deliberately turns it off.
  3. CALIBRATE MODE MOVES THE BADGES AND INVENTS NOTHING. A drag saves an
     offset, the offset moves the drawn badge, and the pattern on screen while
     it is being dragged contains no digits at all.
  4. THE TWO CARD-DATA READINGS ARE HONEST. Mechanical synergy names a payoff
     with no stats source at all and prints a COUNT only when the board is
     actually readable; the turn-by-turn split flags a thin stretch as thin
     and an empty stretch as a dash.

Usage:
    python tests/test_badges.py

Writes only a throwaway .overlay.json in the temp folder.
"""

from __future__ import annotations

import ctypes
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bgtracker as bg              # noqa: E402
import ui                           # noqa: E402
import ui.base                      # noqa: E402
from ui import synergy as mech      # noqa: E402
from ui.browser import BrowserWindow    # noqa: E402

POS_FILE = Path(tempfile.gettempdir()) / "bgtracker-test-badges-overlay.json"

WS_EX_TRANSPARENT = 0x20
GWL_EXSTYLE = -20

# The frame the discover slots were measured on: a live three-option Choose-One
# in a 1892x1000 game window. These are the CARD rectangles, taken from the
# green glow the dialog draws down each card's sides (left run and right run,
# midpoint to midpoint), plus the card band's vertical extent from the same
# glow. Numbers only - the frame itself is a picture of somebody's game and has
# no business in a repository.
FRAME_W, FRAME_H = 1892, 1000
CARDS_3 = ((456.5, 719.5), (814.0, 1076.5), (1174.0, 1435.5))
CARD_TOP, CARD_BOTTOM = 302, 617      # side glow
NAME_BANNER_TOP = 470                 # the card starts printing words here
OLD_SPACING = 0.165                   # what the file held before it was measured


def R(left, top, right, bottom):
    return type("R", (), {"left": left, "top": top,
                          "right": right, "bottom": bottom})()


def exstyle(widget):
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    hwnd = u.GetParent(widget.winfo_id()) or widget.winfo_id()
    return u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def texts(canvas):
    return [canvas.itemcget(i, "text") for i in canvas.find_all()
            if canvas.type(i) == "text"]


# ---------------------------------------------------------------- 1. the slots

def test_choice_slots():
    print("\n=== discover slots vs the measured Choose-One frame")
    ok = True
    xs = [FRAME_W * f for f in ui.base.SLOT_X["choice"][3]]
    old = [FRAME_W * (0.5 + (i - 1) * OLD_SPACING) for i in range(3)]
    for i, (lo, hi) in enumerate(CARDS_3):
        centre = (lo + hi) / 2
        off, off_old = xs[i] - centre, old[i] - centre
        inside = lo < xs[i] < hi
        print(f"  card {i + 1}: centre {centre:.1f}, badge {xs[i]:.1f} "
              f"({off:+.1f}px, on the card={inside}) · the old guess "
              f"{old[i]:.1f} ({off_old:+.1f}px)")
        if not inside or abs(off) > 4:
            print("    FAIL: the badge does not sit on its card")
            ok = False

    y0 = FRAME_H * ui.base.BAND_Y["choice"]
    star_y, sub_y = y0 + 12, y0 + 28     # where show() puts the two rows
    clear = CARD_TOP <= star_y and sub_y <= NAME_BANNER_TOP
    print(f"  band: y0={y0:.0f}, rows at {star_y:.0f}/{sub_y:.0f} - the card "
          f"runs {CARD_TOP}-{CARD_BOTTOM} and starts printing words at "
          f"{NAME_BANNER_TOP}, so the badge is over art only={clear}")
    if not clear:
        print("    FAIL: the badge band covers the card's own text")
        ok = False
    return ok


# ------------------------------------------------- 2 & 3. click-through + drag

def test_clickthrough_and_drag():
    print("\n=== click-through, calibrate mode, and the saved offset")
    POS_FILE.unlink(missing_ok=True)
    ui.base.set_scale(1.0)
    ui.base.set_badge_scale(1.0)
    mgr = ui.base.WindowManager(ui.WINDOWS, pos_file=POS_FILE,
                                names_fn=lambda: {})
    rect = R(0, 0, 1920, 1080)
    mgr.rect = rect
    ok = True
    # Keyed by WINDOW, not by kind: two windows own a "choice" strip (the
    # discover panel and the hero-power panel are dealt on the same frame), and
    # keying by kind would silently drop one of them from the check.
    strips = {w.KEY: w.badges for w in mgr.windows if w.badges is not None}
    disc = mgr.by_key["discover"].badges
    rows = [{"pos": i + 1, "name": f"opt{i}", "stars": 3, "comp": "beast summons"}
            for i in range(3)]

    # -- normal play: a strip on screen lets the click through --------------
    # Only a strip that is actually up can eat a click, and every one of them
    # goes through show() to get there - so each is checked at the moment it
    # is shown, which is also the moment the style is (re-)asserted.
    live = {}
    for key, s in strips.items():
        s.show(rows, rect)
        mgr.root.update()
        live[key] = bool(exstyle(s) & WS_EX_TRANSPARENT)
        if key != "discover":
            s.hide()
    mgr.root.update()
    print(f"  normal play, read out of Win32 at the moment each strip is "
          f"shown: click-through {live} (discover strip style "
          f"{exstyle(disc):#x})")
    if not all(live.values()):
        print("    FAIL: a strip is eating clicks in normal play")
        ok = False

    def star_xs():
        return sorted(round(disc.canvas.coords(i)[0])
                      for i in disc.canvas.find_all()
                      if disc.canvas.type(i) == "text"
                      and disc.canvas.itemcget(i, "text") == "★★★")

    x_before = star_xs()

    # -- calibrate mode: click-through OFF, and no numbers on screen --------
    ui.base.set_badge_edit(True)
    mgr.root.update()
    during = {k: bool(exstyle(s) & WS_EX_TRANSPARENT) for k, s in strips.items()}
    shown = texts(disc.canvas)
    digits = [t for t in shown if any(ch.isdigit() for ch in t)]
    print(f"  calibrate mode: click-through {during}, pattern={shown[:3]}, "
          f"items carrying a digit={digits}")
    if any(during.values()) or digits:
        print("    FAIL: calibrate mode kept click-through on, or drew a number")
        ok = False

    # -- a drag saves an offset, in fractions of the game window -----------
    disc._press(type("E", (), {"x_root": 500, "y_root": 500})())
    disc._motion(type("E", (), {"x_root": 538, "y_root": 521})())
    disc._release(type("E", (), {"x_root": 538, "y_root": 521})())
    saved = mgr.pos.get_badge("choice")
    want = (38 / 1920, 21 / 1080)
    print(f"  drag of +38/+21px on a 1920x1080 game -> saved {saved} "
          f"(expected {want[0]:.5f}/{want[1]:.5f})")
    if abs(saved[0] - want[0]) > 1e-4 or abs(saved[1] - want[1]) > 1e-4:
        print("    FAIL: the drag was not stored as a fraction of the window")
        ok = False

    # -- leaving puts click-through back on EVERY strip --------------------
    ui.base.set_badge_edit(False)
    mgr.root.update()
    after = {k: bool(exstyle(s) & WS_EX_TRANSPARENT) for k, s in strips.items()}
    disc.show(rows, rect)                      # and it survives a real offer
    mgr.root.update()
    after_show = bool(exstyle(disc) & WS_EX_TRANSPARENT)
    print(f"  back to normal play: click-through {after}, still on after the "
          f"next real offer={after_show}")
    if not all(after.values()) or not after_show:
        print("    FAIL: the game would not get its clicks back")
        ok = False

    # -- and the offset actually moved the badge ---------------------------
    x_after = star_xs()
    moved = [b - a for a, b in zip(x_before, x_after)]
    print(f"  badge x {x_before} -> {x_after} (moved {moved}, asked for +38)")
    if not moved or any(abs(d - 38) > 2 for d in moved):
        print("    FAIL: the saved offset did not move the badge")
        ok = False

    mgr.pos.set_badge("choice", 0, 0)
    mgr.root.destroy()
    return ok


# ------------------------------------------------------- 4a. mechanical synergy

BEAST_BUFF = {"id": "X1", "name": "Buffer", "races": ["MURLOC"],
              "mechanics": ["END_OF_TURN_TRIGGER"],
              "text": "At the end of your turn, give your <b>Beasts</b> +2/+1."}
MAGNET = {"id": "X2", "name": "Magnet", "races": ["MECHANICAL"],
          "mechanics": ["MAGNETIC"], "text": "<b>Magnetic</b> Taunt"}
GEMS = {"id": "X3", "name": "Gemmer", "races": [],
        "mechanics": [], "text": "Whenever you play a <b>Blood Gem</b>, gain 1."}
PLAIN = {"id": "X4", "name": "Vanilla", "races": ["PIRATE"],
         "mechanics": [], "text": "<b>Taunt</b>"}


def test_synergy():
    print("\n=== mechanical synergy (card data only, no stats source)")
    ok = True
    name_tribes = {"Wolf": {"BEAST"}, "Bear": {"BEAST"}, "Cat": {"BEAST"},
                   "Fish": {"MURLOC"}, "Blob": {"ALL"}}
    held, wild = mech.held_counts(["Wolf", "Bear", "Cat", "Fish", "Blob"],
                                  name_tribes)
    print(f"  board Wolf/Bear/Cat/Fish/Blob -> {held}, counts-as-any={wild}")
    if held != {"BEAST": 3, "MURLOC": 1} or wild != 1:
        print("    FAIL: an every-tribe minion was counted into each tribe")
        ok = False

    cases = [
        (BEAST_BUFF, "▸ Beasts 4", "pays off Beasts · you hold 3 (+1 any)"),
        # One of a tribe is a coincidence, not a build: no short tag, but the
        # full line still reports the dead payoff.
        (MAGNET, None, "pays off Mechs · you hold 0 (+1 any)"),
        (GEMS, None, "pays off Quilboar · you hold 0 (+1 any)"),
        (PLAIN, None, None),
    ]
    for entry, short, full in cases:
        got = mech.format_synergy(mech.synergy(entry, held, wild,
                                               board_known=True))
        print(f"  {entry['name']:8} -> {got[0]!r} / {got[1]!r}")
        if got != (short, full):
            print(f"    FAIL: expected {short!r} / {full!r}")
            ok = False

    # No memory reader: the payoff is still card text, the count is not.
    blind = mech.format_synergy(mech.synergy(BEAST_BUFF, {}, 0,
                                             board_known=False))
    member = mech.format_synergy(mech.synergy(PLAIN, {"PIRATE": 3}, 0,
                                              board_known=True))
    print(f"  board unreadable -> {blind[0]!r} / {blind[1]!r}")
    print(f"  no payoff text but a third Pirate -> {member[0]!r} / {member[1]!r}")
    if blind != (None, "pays off Beasts"):
        print("    FAIL: an unknown board printed a count")
        ok = False
    if member[0] != "▸ Pirates 3":
        print("    FAIL: the tribe-body case is not reported")
        ok = False
    return ok


# -------------------------------------------------------- 4b. turn-by-turn

FEED = {"cardStats": [
    {"cardId": "GOOD", "turnStats": [
        {"turn": 1, "totalPlayed": 10, "averagePlacement": 5.0,
         "totalOther": 100, "averagePlacementOther": 4.0},
        {"turn": 2, "totalPlayed": 30, "averagePlacement": 4.0,
         "totalOther": 100, "averagePlacementOther": 4.0},
        {"turn": 9, "totalPlayed": 200, "averagePlacement": 2.5,
         "totalOther": 200, "averagePlacementOther": 4.0},
        {"turn": 13, "totalPlayed": 5, "averagePlacement": 1.0,
         "totalOther": 5, "averagePlacementOther": 4.0},
        {"turn": 4, "averagePlacement": None},          # malformed: dropped
        "not a dict",                                   # malformed: dropped
    ]},
    {"cardId": "BARE", "totalPlayed": 3},               # a feed with no split
]}


def test_turn_bands():
    print("\n=== turn-by-turn: weighted, thin flagged, empty dashed")
    ok = True
    real, bg.load_bucket = bg.load_bucket, lambda *a, **k: FEED
    try:
        rows = BrowserWindow._read_turns("100", "last-patch")
    finally:
        bg.load_bucket = real
    print(f"  parsed: {sorted(rows)} · GOOD has {len(rows.get('GOOD', []))} "
          f"usable turns of 6 rows (2 malformed dropped, never repaired)")
    if sorted(rows) != ["GOOD"] or len(rows["GOOD"]) != 4:
        print("    FAIL: the raw feed was not read the way it is documented")
        ok = False

    bands = BrowserWindow._turn_bands(rows["GOOD"])
    for label, delta, played, thin in bands:
        print(f"  {label:6} delta={'-' if delta is None else format(delta, '+.3f')}"
              f" played={played} thin={thin}")
    # t1-4: played 10x5.00 + 30x4.00 = 4.25 against 200 games of 4.00 = +0.25,
    # and 40 games is over the floor, so it is a number.
    first = bands[0]
    if abs(first[1] - 0.25) > 1e-9 or first[2] != 40 or first[3]:
        print("    FAIL: the stretch is not weighted by its own game counts")
        ok = False
    if bands[1][1] is not None or bands[1][2]:
        print("    FAIL: a stretch nobody played it in must be a dash")
        ok = False
    if not bands[3][3] or bands[3][2] != 5:
        print(f"    FAIL: 5 games is under the floor of {bg.MIN_SAMPLE} and "
              f"must be flagged thin")
        ok = False

    # -- and it renders, with the words the panel promises ------------------
    mgr = ui.base.WindowManager([], pos_file=POS_FILE, names_fn=lambda: {})
    b = BrowserWindow(mgr)
    b.pool = [{"id": "GOOD", "name": "Good Minion", "techLevel": 4,
               "races": ["BEAST"], "mechanics": [], "text": "Taunt"},
              {"id": "BARE", "name": "Bare Minion", "techLevel": 2,
               "races": [], "mechanics": [], "text": "Taunt"}]
    b.cards = {"GOOD": {"avg": 3.0, "n": 400, "delta": -0.9},
               "BARE": {"avg": 4.0, "n": 90, "delta": -0.1}}
    b.turns = rows
    b.bands = {}
    b.expanded = True
    b.open_id = "GOOD"
    b.show()
    got = texts(b.canvas)
    b.open_id = "BARE"
    b.redraw()
    bare = texts(b.canvas)
    print(f"  drawn for GOOD: "
          f"{[t for t in got if t in ('BY TURN', 't1-4', 't5-8', 't9-12', 't13+')]}"
          f" values={[t for t in got if t.startswith(('thin', '+', '—'))]}")
    print(f"  drawn for BARE (rated, no split): "
          f"{[t for t in bare if 'turn-by-turn' in t]}")
    if "BY TURN" not in got or not any(t.startswith("thin") for t in got):
        print("    FAIL: the turn strip did not paint")
        ok = False
    if not any("turn-by-turn" in t for t in bare):
        print("    FAIL: a source with no split must say so")
        ok = False
    if b.errors:
        print("    FAIL: the browser raised while drawing")
        ok = False
    mgr.root.destroy()
    return ok


def main():
    POS_FILE.unlink(missing_ok=True)
    results = [test_choice_slots(), test_clickthrough_and_drag(),
               test_synergy(), test_turn_bands()]
    POS_FILE.unlink(missing_ok=True)
    print("\nPASS" if all(results) else "\nFAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
