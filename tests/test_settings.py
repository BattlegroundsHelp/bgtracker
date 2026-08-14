#!/usr/bin/env python3
"""The settings store and the settings panel, proved against a live Tk.

Five things are checked, and every one of them is a claim the panel makes on
screen, so each is measured rather than asserted from the code:

  1. PRECEDENCE - a flag beats the file beats the default, and a flag is never
     written back into the file.
  2. A CORRUPT FILE - falls back to defaults, says so, and does not raise.
  3. THE PANEL IS NOT CLICK-THROUGH - the exact opposite of every other window
     in ui/, read back out of Win32 rather than believed.
  4. SCALE IS LIVE - the panel's slider changes the fonts and the geometry of
     windows that are already open, measured in pixels before and after.
  5. A WINDOW SWITCHED OFF IS NOT BUILT - not hidden: absent from the manager,
     absent from the router, and holding no badge strip.

Usage:
    python tests/test_settings.py

It writes only to a throwaway settings file and a throwaway .overlay.json in
the temp folder; the real ones are never touched.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path
from tkinter import font as tkfont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import overlay                         # noqa: E402
import settings as store               # noqa: E402
import ui                              # noqa: E402
import ui.base                         # noqa: E402
import update                          # noqa: E402
from ui.settings import SettingsPanel   # noqa: E402

TMP = Path(tempfile.gettempdir())
SFILE = TMP / "bgtracker-test-settings.json"
POS_FILE = TMP / "bgtracker-test-settings-overlay.json"

WS_EX_TRANSPARENT = 0x20
GWL_EXSTYLE = -20


def exstyle(widget):
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    hwnd = u.GetParent(widget.winfo_id()) or widget.winfo_id()
    return u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)


def font_size(widget, item):
    """The point size a canvas item is REALLY drawn at, resolved through Tk."""
    return tkfont.Font(root=widget, font=widget.itemcget(item, "font")).actual("size")


def item_width(canvas, item):
    b = canvas.bbox(item)
    return (b[2] - b[0]) if b else 0


# --------------------------------------------------------------------------
# 1 + 2: the store


def test_store():
    print("\n=== store: precedence, and a file that is broken")
    ok = True
    SFILE.unlink(missing_ok=True)

    s = store.Settings.load(SFILE)
    print(f"  no file at all      -> mmr={s.get('mmr')!r} ({s.source_of('mmr')}), "
          f"duo={s.get('duo')!r} ({s.source_of('duo')})")
    ok &= s.get("mmr") == "100" and s.source_of("mmr") == "default"

    # Community sharing is ON by default (flipped from opt-in on 2026-08-12,
    # the author's call): a fresh install with no settings file pools its
    # games, and the panel's DATA box or --no-upload is the off switch.
    print(f"  sharing default     -> upload={s.get('upload')!r} "
          f"({s.source_of('upload')})")
    ok &= s.get("upload") is True and s.source_of("upload") == "default"

    s.set("mmr", "25")
    s.set("duo", True)
    on_disk = json.loads(SFILE.read_text(encoding="utf-8"))
    print(f"  after saving        -> file holds {on_disk}")
    ok &= on_disk == {"duo": True, "mmr": "25"}

    s2 = store.Settings.load(SFILE)
    print(f"  reloaded            -> mmr={s2.get('mmr')!r} ({s2.source_of('mmr')})")
    ok &= s2.get("mmr") == "25" and s2.source_of("mmr") == "file"

    s3 = store.Settings.load(SFILE, overrides={"mmr": "1", "time": None, "duo": None})
    print(f"  with --mmr 1        -> mmr={s3.get('mmr')!r} ({s3.source_of('mmr')}), "
          f"duo={s3.get('duo')!r} ({s3.source_of('duo')}), "
          f"time={s3.get('time')!r} ({s3.source_of('time')})")
    ok &= (s3.get("mmr") == "1" and s3.source_of("mmr") == "flag"
           and s3.get("duo") is True and s3.source_of("duo") == "file"
           and s3.source_of("time") == "default")

    # The flag must not leak into the file, even when something else is saved
    # in the same run - that is the whole reason overrides are a separate dict.
    s3.set("badge_scale", 1.5)
    on_disk = json.loads(SFILE.read_text(encoding="utf-8"))
    print(f"  saved something else-> file holds {on_disk}")
    ok &= on_disk.get("mmr") == "25" and on_disk.get("badge_scale") == 1.5
    if on_disk.get("mmr") != "25":
        print("    FAIL: the command-line override was written into the file")

    SFILE.write_text('{"mmr": "25", "ui_scale": 99, "duo": "yes", "windows": 5,',
                     encoding="utf-8")
    s4 = store.Settings.load(SFILE)
    print(f"  truncated json      -> mmr={s4.get('mmr')!r} "
          f"({s4.source_of('mmr')}), problems={len(s4.problems)}")
    for p in s4.problems:
        print(f"      {p}")
    ok &= s4.get("mmr") == "100" and len(s4.problems) == 1

    SFILE.write_text(json.dumps({"mmr": "25", "ui_scale": 99, "duo": "yes",
                                 "windows": 5, "mystery": "kept"}),
                     encoding="utf-8")
    s5 = store.Settings.load(SFILE)
    print(f"  valid json, bad values -> mmr={s5.get('mmr')!r} "
          f"({s5.source_of('mmr')}), ui_scale={s5.get('ui_scale')!r}, "
          f"duo={s5.get('duo')!r}, windows={s5.get('windows')!r}")
    for p in s5.problems:
        print(f"      {p}")
    ok &= (s5.get("mmr") == "25" and s5.get("ui_scale") is None
           and s5.get("duo") is False and s5.get("windows") == {}
           and len(s5.problems) == 3 and s5.data.get("mystery") == "kept")

    if not ok:
        print("    FAIL: store")
    return bool(ok)


def test_persistence():
    """Written by one process, read by a SECOND one - the real restart."""
    print("\n=== restart: a second process reads what the panel saved")
    SFILE.unlink(missing_ok=True)
    s = store.Settings.load(SFILE)
    s.set("ui_scale", 1.75)
    s.set("badge_scale", 1.25)
    s.set("mmr", "10")
    s.set("time", "past-seven")
    s.set_window_enabled("tavern", False)
    print(f"  wrote {SFILE}: {' '.join(SFILE.read_text(encoding='utf-8').split())}")
    code = (
        "import sys, json; sys.path.insert(0, r'%s');"
        "import settings;"
        "s = settings.Settings.load(r'%s');"
        "print(json.dumps({'ui_scale': s.get('ui_scale'),"
        " 'badge_scale': s.get('badge_scale'), 'mmr': s.get('mmr'),"
        " 'time': s.get('time'), 'tavern': s.window_enabled('tavern'),"
        " 'combat': s.window_enabled('combat'),"
        " 'src': s.source_of('mmr'), 'problems': s.problems}))"
    ) % (ROOT, SFILE)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=str(ROOT))
    print(f"  fresh process says: {out.stdout.strip() or out.stderr.strip()}")
    try:
        got = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        print("    FAIL: the second process could not read the settings")
        return False
    ok = (got == {"ui_scale": 1.75, "badge_scale": 1.25, "mmr": "10",
                  "time": "past-seven", "tavern": False, "combat": True,
                  "src": "file", "problems": []})
    if not ok:
        print("    FAIL: what came back is not what was written")
    return ok


# --------------------------------------------------------------------------
# 3 + 4 + 5: the panel, against real windows


class FakeApp:
    """Stands in for overlay.App where the real one would need a log reader."""

    def __init__(self, manager, settings):
        self.manager, self.settings = manager, settings
        self.quit_calls = 0
        self.toggles = []

    def quit(self):
        self.quit_calls += 1

    def set_window_enabled(self, key, on):
        self.toggles.append((key, on))


def test_panel():
    print("\n=== panel: input, live scale, live badge nudge")
    SFILE.unlink(missing_ok=True)
    POS_FILE.unlink(missing_ok=True)
    s = store.Settings.load(SFILE)
    s.set("ui_scale", 1.0)
    ui.base.set_scale(1.0)
    ui.base.set_badge_scale(1.0)

    mgr = ui.base.WindowManager(ui.WINDOWS, pos_file=POS_FILE,
                                names_fn=lambda: {})
    app = FakeApp(mgr, s)
    mgr.open_settings = lambda: None
    panel = SettingsPanel(app, s, mgr)
    ok = True

    # -- 3. it is NOT click-through -------------------------------------
    strip = mgr.by_key["tavern"].badges
    strip.show([{"pos": 1, "name": "x", "stars": 3}],
               type("R", (), {"left": 0, "top": 0, "right": 1920, "bottom": 1080})())
    mgr.root.update()
    p_style, s_style = exstyle(panel), exstyle(strip)
    print(f"  panel  exstyle 0x{p_style:X}  transparent="
          f"{bool(p_style & WS_EX_TRANSPARENT)}  "
          f"overrideredirect={bool(panel.wm_overrideredirect())}  "
          f"transparentcolor={panel.attributes('-transparentcolor')!r}  "
          f"topmost={panel.attributes('-topmost')}")
    print(f"  badge  exstyle 0x{s_style:X}  transparent="
          f"{bool(s_style & WS_EX_TRANSPARENT)}   (the overlay's own surfaces)")
    if p_style & WS_EX_TRANSPARENT:
        print("    FAIL: the settings panel inherited click-through")
        ok = False
    if not s_style & WS_EX_TRANSPARENT:
        print("    FAIL: a badge strip lost click-through")
        ok = False
    if panel.wm_overrideredirect() or panel.attributes("-transparentcolor"):
        print("    FAIL: the panel is built like an overlay window")
        ok = False
    if panel.winfo_id() not in mgr._our_ids():
        print("    FAIL: the panel is not in the focus allow-set, so opening "
              "it would hide the overlay")
        ok = False

    # -- 4. the scale is live -------------------------------------------
    comps = mgr.by_key["comps"]
    comps.handle("status", "test")
    comps.show()
    def snapshot():
        # The item id is looked up EVERY time: a repaint starts with
        # delete("all"), so an id captured before the scale change names
        # nothing afterwards.
        title = next(i for i in comps.canvas.find_all()
                     if comps.canvas.type(i) == "text")      # the header text
        return {
            "F_NAME pt": ui.base.F_NAME.size,
            "panel font pt": panel.f_label.actual("size"),
            "comps canvas px": comps.canvas.winfo_reqwidth(),
            "header item pt": font_size(comps.canvas, title),
            "header item px": item_width(comps.canvas, title),
        }

    before = snapshot()
    panel.scale_var.set(2.0)
    panel._on_scale()
    panel.update_idletasks()
    after = snapshot()
    print("  drag the UI scale slider 1.00x -> 2.00x, with comps already open:")
    for k in before:
        print(f"      {k:16} {before[k]:>5} -> {after[k]:>5}")
    for k in before:
        if after[k] < before[k] * 1.7:
            print(f"    FAIL: {k} did not follow the scale")
            ok = False
    if panel.auto_var.get():
        print("    FAIL: dragging the slider left 'automatic' ticked")
        ok = False

    # the badge nudge, which is a different scale on purpose
    ui.base.set_scale(1.0)
    panel.badge_var.set(1.5)
    panel._on_badge()
    print(f"  badge nudge 1.00x -> {ui.base.get_badge_scale():.2f}x: "
          f"badge_scale(1080)={ui.base.badge_scale(1080):.2f}, "
          f"badge_scale(2160)={ui.base.badge_scale(2160):.2f} "
          f"(clamped at {ui.base.SCALE_MAX}), panel scale still "
          f"{ui.base.get_scale():.2f}")
    if ui.base.badge_scale(1080) != 1.5 or ui.base.get_scale() != 1.0:
        print("    FAIL: the badge nudge moved the wrong thing")
        ok = False
    panel.badge_var.set(1.0)
    panel._on_badge()

    # -- saving, and what the panel refuses to invent --------------------
    panel._save_scale()
    panel._save_badge()
    saved = json.loads(SFILE.read_text(encoding="utf-8"))
    print(f"  saved on release: {saved} (the sliders read "
          f"{panel.scale_var.get():.2f} and {panel.badge_var.get():.2f})")
    ok &= saved.get("ui_scale") == 2.0 and saved.get("badge_scale") == 1.0

    panel.upload_var.set(False)
    panel._refresh_data()
    print(f"  data section: share button={panel.share_btn['state']}, "
          f"line={panel.share_lbl.cget('text')!r}")
    if str(panel.share_btn["state"]) != "disabled":
        print("    FAIL: games can be shared while the switch is off")
        ok = False
    # A share that fails says what failed, in the words the network used. The
    # error is produced for real, against a port with nothing behind it.
    import collect
    dead = collect.upload("http://127.0.0.1:9")
    panel._share_done(dead)
    print(f"  share against a dead port -> {dead['error']}")
    print(f"    panel says: {panel.share_lbl.cget('text')!r}")
    ok &= bool(dead.get("error")) and "share failed" in panel.share_lbl.cget("text")
    panel._share_done({"sent": 35, "stored": 35, "error": None, "note": None})
    print(f"  a share that worked  -> {panel.share_lbl.cget('text')!r}, "
          f"last_upload saved={store.Settings.load(SFILE).get('last_upload') is not None}")
    ok &= "35 games" in panel.share_lbl.cget("text")

    panel._refresh_updates()
    print(f"  updates section: {panel.upd_lbl.cget('text')!r}")
    if "up to date" in panel.upd_lbl.cget("text").lower():
        print("    FAIL: claimed up to date without a check")
        ok = False

    print(f"  window list built from the registry: {len(panel.win_vars)} "
          f"switches for {len(ui.WINDOWS)} windows")
    ok &= set(panel.win_vars) == {c.KEY for c in ui.WINDOWS}

    # -- the DATA copy names exactly what collect.upload_records() sends ----
    # The field list is read out of collect.upload_records' own source (the
    # record literal), so adding a field there without naming it in the panel
    # copy fails this test - the copy's claim is "exactly these fields".
    import inspect
    import re as _re
    block = inspect.getsource(collect.upload_records).split("recs.append({", 1)[1]
    sent = _re.findall(r'"(\w+)":', block.split("})", 1)[0])
    phrase = {"uid": "a scrambled game id", "date": "the date",
              "hero": "the hero you played", "place": "your placement",
              "duo": "whether it was Duos", "tribes": "the lobby tribes",
              "offered_heroes": "the heroes you were offered",
              "offered_trinkets": "the trinkets you were offered",
              "picked_trinkets": "the trinkets you picked",
              # The hero-power table and the comp ranking are built from these
              # three and from nothing else, so they leave the machine and the
              # copy has to say so in as many words.
              "offered_hero_powers": "the hero powers you were offered",
              "picked_hero_powers": "the hero powers you picked",
              "final_board": "the board you finished on",
              "client": "client id", "v": "version"}
    txt = panel.data_lbl.cget("text")
    net = panel.netcheck_lbl.cget("text")
    unnamed = [f for f in sent if phrase.get(f) is None or phrase[f] not in txt]
    print(f"  data copy: collect.upload_records sends {len(sent)} fields: {sent}")
    print(f"    named in the sharing copy: {len(sent) - len(unnamed)} of {len(sent)}"
          + (f"  MISSING: {unnamed}" if unnamed else ""))
    if unnamed:
        print("    FAIL: the sharing copy does not name every field that is sent")
        ok = False
    if "nothing leaves this machine" in txt:
        print("    FAIL: the copy still makes the blanket no-network claim")
        ok = False
    # Sharing is ON by default (author's decision, 2026-08-12) and the copy
    # must say so plainly, name the off switch, and never repeat the old
    # opt-in promise.
    for needle in ("On by default", "--no-upload", "off switch",
                   "free for everyone"):
        if needle not in txt:
            print(f"    FAIL: the sharing copy lost {needle!r}")
            ok = False
    for stale in ("Off by default", "opt-in", "opt in"):
        if stale in txt:
            print(f"    FAIL: the sharing copy still claims {stale!r}")
            ok = False
    for label, t in (("sharing", txt), ("update-check", net)):
        if "\u2014" in t or "\u2013" in t:
            print(f"    FAIL: em/en dash in the {label} copy")
            ok = False
    for needle in ("update", "every start", "network address", "--no-update-check"):
        if needle not in net:
            print(f"    FAIL: the update-check disclosure lost {needle!r}")
            ok = False
    print(f"    update-check disclosure: {net[:72]}...")

    # -- the Rank row carries the date its table was measured --------------
    mmr_txt = panel.mmr_lbl.cget("text")
    print(f"  rank row: {mmr_txt!r}")
    if store.MMR_MEASURED not in mmr_txt or "as last measured" in mmr_txt:
        print("    FAIL: the rank figure carries no measurement date")
        ok = False

    # -- the UPDATES row follows a check that lands AFTER the panel opened -
    update._RESULT = None
    update._RESULT_AT = None
    panel._upd_gave_up = False
    panel._refresh_updates()
    checking = panel.upd_lbl.cget("text")
    update.check("http://127.0.0.1:9", timeout=2.0)    # the on-start check lands
    landed = ""
    for _ in range(80):                                 # pump Tk, up to ~4s
        mgr.root.update()
        time.sleep(0.05)
        landed = panel.upd_lbl.cget("text")
        if "Could not reach" in landed:
            break
    print(f"  updates row while the check is in flight: {checking!r}")
    print(f"  updates row after it landed, no clicks:   {landed!r}")
    if "Checking" not in checking or "Could not reach" not in landed:
        print("    FAIL: the row did not follow the on-start check's result")
        ok = False

    # -- "What changed" opens https and nothing else -----------------------
    # Defence in depth: parse_manifest refuses these at check time, so a
    # poisoned result is planted directly to prove the button ALSO refuses.
    import ui.settings as uis
    opened = []
    real_wb = uis.webbrowser
    uis.webbrowser = type("WB", (), {"open": staticmethod(opened.append)})
    try:
        for target in (r"\\evil-box\share\payload.exe",
                       "file:///C:/Windows/System32/calc.exe",
                       "http://host/notes"):
            update._RESULT = update.Update(latest="9.9.9", newer=True,
                                           notes=target)
            panel._open_notes()
        refused = list(opened)
        update._RESULT = update.Update(latest="9.9.9", newer=True,
                                       url="https://host/b.zip",
                                       notes="https://host/notes")
        panel._open_notes()
    finally:
        uis.webbrowser = real_wb
        update._RESULT = None
        update._RESULT_AT = None
    print(f"  what-changed: refused {3 - len(refused)}/3 poisoned targets, "
          f"opened {opened}")
    if refused or opened != ["https://host/notes"]:
        print("    FAIL: a non-https notes target reached the system opener")
        ok = False

    # -- the quit-carrying window cannot be switched off --------------------
    qkey = next(c.KEY for c in ui.WINDOWS if c.QUIT_BUTTON)
    greyed = str(panel.win_checks[qkey]["state"]) == "disabled"
    panel.win_vars[qkey].set(False)
    panel._on_window(qkey)
    kept = (panel.win_vars[qkey].get() and s.window_enabled(qkey)
            and (qkey, False) not in app.toggles)
    s.set_window_enabled(qkey, False)      # a hand-edited file says off
    p2 = SettingsPanel(app, s, mgr)
    healed = s.window_enabled(qkey) and p2.win_vars[qkey].get()
    p2.destroy()
    print(f"  quit window ({qkey}): checkbox greyed={greyed}, toggle refused="
          f"{bool(kept)}, hand-edited off healed={bool(healed)}")
    if not (greyed and kept and healed):
        print("    FAIL: the overlay can be left with no way to quit or reopen "
              "settings")
        ok = False

    panel.destroy()
    mgr.root.destroy()
    ui.base.set_scale(1.0)
    return bool(ok)


def test_window_toggle():
    """A window switched off is not built, and switching it back on is live."""
    print("\n=== what to show: off means not built")
    SFILE.unlink(missing_ok=True)
    POS_FILE.unlink(missing_ok=True)
    s = store.Settings.load(SFILE)
    s.set("ui_scale", 1.0)
    s.set_window_enabled("tavern", False)
    s.set_window_enabled("combat", False)

    before_strips = len(ui.base._STRIPS)
    app = overlay.App(s, panel=False)
    app.manager.pos.path = POS_FILE          # never write the real positions
    keys = [w.KEY for w in app.manager.windows]
    strips = [st.kind for st in ui.base._STRIPS[before_strips:]]
    print("  settings say tavern=off combat=off")
    print(f"  built: {keys}")
    print(f"  badge strips built: {strips}")
    print(f"  router knows the 'tavern' event: "
          f"{[w.KEY for w in app.router.by_event.get('tavern', [])]}")
    ok = ("tavern" not in keys and "combat" not in keys
          and "shop" not in strips
          and not [w for w in app.router.by_event.get("tavern", [])
                   if w.KEY == "tavern"]
          and len(keys) == len(ui.WINDOWS) - 2)
    if not ok:
        print("    FAIL: a window that is off was still built")

    # dispatching its event must simply reach nobody
    app.router.dispatch("tavern", {"rows": [], "slots": [], "roll": 1, "lean": None})
    app.router.dispatch("combat", {"seq": 0, "round": 1})
    print(f"  dispatched tavern+combat anyway -> windows now: "
          f"{[w.KEY for w in app.manager.windows]}")

    app.set_window_enabled("tavern", True)
    keys2 = [w.KEY for w in app.manager.windows]
    strips2 = [st.kind for st in ui.base._STRIPS[before_strips:]]
    routed = [w.KEY for w in app.router.by_event.get("tavern", [])]
    print(f"  switched tavern back on (no restart): built={'tavern' in keys2}, "
          f"strips={strips2}, router routes 'tavern' to {routed}")
    # other windows legitimately listen to `tavern` too (a later roll closes a
    # pick panel), so the claim is that the tavern window is back on the list.
    ok &= "tavern" in keys2 and "shop" in strips2 and "tavern" in routed

    app.set_window_enabled("tavern", False)
    keys3 = [w.KEY for w in app.manager.windows]
    strips3 = [st.kind for st in ui.base._STRIPS[before_strips:]]
    print(f"  and off again: built={'tavern' in keys3}, strips={strips3}, "
          f"router routes 'tavern' to "
          f"{[w.KEY for w in app.router.by_event.get('tavern', [])]}")
    ok &= "tavern" not in keys3 and "shop" not in strips3

    # the gear that reopens the panel is only drawn when there is one to open
    comps = app.manager.by_key["comps"]
    comps.show()
    texts = [comps.canvas.itemcget(i, "text") for i in comps.canvas.find_all()
             if comps.canvas.type(i) == "text"]
    print(f"  comps header controls: {[t for t in texts if t in ('✕', '⚙')]}")
    ok &= "⚙" in texts and "✕" in texts

    app.manager.root.destroy()
    return bool(ok)


def test_geometry():
    """The window-placement and badge-strip findings, each against its repro:
    a saved drag is honored anywhere a monitor shows it (and rescued only when
    fully off every screen); at high scale the default stack keeps band order
    instead of doubling back; a badge nudge keeps the window's min_sample; and
    destroying the strip that suppressed another brings the victim back."""
    print("\n=== geometry: saved drags, high-scale tiling, badge arbitration")
    POS_FILE.unlink(missing_ok=True)
    ui.base.set_scale(1.0)
    ui.base.set_badge_scale(1.0)
    mgr = ui.base.WindowManager(ui.WINDOWS, pos_file=POS_FILE,
                                names_fn=lambda: {})
    ok = True

    def R(left, top, right, bottom):
        return type("R", (), {"left": left, "top": top,
                              "right": right, "bottom": bottom})()

    # -- a saved drag is the user's own layout ------------------------------
    rect = R(100, 100, 1380, 820)          # a windowed 1280x720 game
    mgr.rect = rect
    w = mgr.by_key["combat"]
    bx, by = w.default_xy(rect)
    w.dx = w.dy = 0
    w._place()
    at_default = w._xy == (int(bx), int(by))
    park = (1500, 300)                     # outside the game rect, on the screen
    w.dx, w.dy = park[0] - bx, park[1] - by
    w._place()
    honored = w._xy == park
    w.dx, w.dy = 100000, 100000            # the monitor it sat on is gone
    w._place()
    rescued = w._xy == (int(bx), int(by))
    print(f"  saved positions: default kept={at_default}, parked at {park} "
          f"(right of the game window, x>{rect.right}) kept={honored}, "
          f"fully off every screen rescued to the anchor={rescued}")
    if not (at_default and honored and rescued):
        print("    FAIL: a deliberate position was snapped back, or a dead one "
              "was not rescued")
        ok = False
    w.dx = w.dy = 0

    # -- 2.0x on a 1080p game window: band order, never a double-back -------
    rect = R(0, 0, 1920, 1080)
    mgr.rect = rect
    ui.base.set_scale(2.0)
    doubled_back, off_bottom = [], 0
    for win in mgr.windows:
        win.dx = win.dy = 0
        win._h = win._px(win.MAX_H)        # worst case: every window at max
        win._place()
        want_top = rect.top + win._px(win.DY)
        if win._xy[1] != want_top:
            doubled_back.append((win.KEY, win._xy[1], want_top))
        if win._xy[1] + win._h > rect.bottom:
            off_bottom += 1
    print(f"  2.0x on 1080p: every default anchor at its scaled band start="
          f"{not doubled_back}{' ' + str(doubled_back) if doubled_back else ''}, "
          f"{off_bottom} windows run off the BOTTOM edge (the documented "
          f"overflow) instead of stacking on a neighbour")
    if doubled_back or not off_bottom:
        print("    FAIL: the column doubled back over itself at high scale")
        ok = False
    ui.base.set_scale(1.0)
    for win in mgr.windows:
        win._h = win._px(win._h_base)

    # -- the badge nudge keeps the window's min_sample -----------------------
    strip = mgr.by_key["heropick"].badges
    rows = [{"pos": 1, "name": "A", "avg": 1.50, "n": 3},
            {"pos": 2, "name": "B", "avg": 3.00, "n": 100}]

    def best_xs():
        # The best offer is marked by the GOLD outline on its stat cells
        # (the HSReplay-cell restyle, 2026-08-14 - there is no "best" text
        # any more). The cells straddle the slot, so the marker position is
        # the MEAN of their centres.
        xs = [(strip.canvas.coords(i)[0] + strip.canvas.coords(i)[2]) / 2
              for i in strip.canvas.find_all()
              if strip.canvas.type(i) == "rectangle"
              and strip.canvas.itemcget(i, "outline") == ui.base.GOLD]
        return [round(sum(xs) / len(xs))] if xs else []

    # set_badge_scale re-shows every visible strip from the LIVE game window
    # (hs_rect) - correct in production, but this test measures chip x against
    # its own fabricated rect, and with Hearthstone actually running the
    # assertion drifted with wherever the real window happened to sit that
    # day (caught 2026-08-13: pass at one window position, +9px fail after
    # the window was moved). Pin the rect for the duration of the nudge.
    real_hs_rect = ui.base.hs_rect
    ui.base.hs_rect = lambda: rect
    try:
        strip.show(rows, rect, min_sample=25)
        before = (strip.min_sample, best_xs())
        ui.base.set_badge_scale(1.3)       # re-shows every visible strip
        after = (strip.min_sample, best_xs())
        ui.base.set_badge_scale(1.0)
    finally:
        ui.base.hs_rect = real_hs_rect
    slot_b = int(1920 * 0.586)             # SLOT_X["hero"][2][1]: row B's slot
    on_b = (lambda xs: bool(xs) and all(abs(x - slot_b) <= 4 for x in xs))
    print(f"  badge nudge: min_sample {before[0]} -> {after[0]}, 'best' chip at "
          f"x={before[1]} -> {after[1]} (row B's slot is x={slot_b}; the 3-game "
          f"1.50 average must never win)")
    if not (before[0] == 25 and after[0] == 25 and on_b(before[1])
            and on_b(after[1])):
        print("    FAIL: the nudge re-show dropped the window's min_sample")
        ok = False
    strip.hide()

    # -- disabling the suppressor revives the suppressed strip ---------------
    mgr.game_front = True                  # the revive only acts over the game
    shop = mgr.by_key["tavern"].badges     # priority 10
    choice = mgr.by_key["discover"].badges # priority 30
    shop.show([{"pos": 1, "name": "x", "stars": 3}], rect)
    choice.show([{"pos": 1, "name": "y", "stars": 1}], rect)
    suppressed = (not shop.visible) and bool(shop.rows)   # rows must be kept
    mgr.disable("discover")
    revived = shop.visible
    print(f"  strip arbitration: shop suppressed by the choice strip="
          f"{suppressed} (rows kept), revived when the discover window was "
          f"disabled={revived}")
    if not (suppressed and revived):
        print("    FAIL: lower-priority badges stay hidden after their hider "
              "is destroyed")
        ok = False

    mgr.root.destroy()
    ui.base.set_scale(1.0)
    POS_FILE.unlink(missing_ok=True)
    return bool(ok)


def test_pool():
    """The overlay's own community pooling (pool.py), against a REAL loopback
    ingest server (server/ingest.py, the code the VPS runs), never the live
    one. Proved, in order: the default is ON; --no-upload wins for one run
    without touching the file; the opt-out persists; the sent ledger stops
    re-uploads (and a record that GAINED data goes out again); a dead server
    neither raises nor blocks and leaves the ledger alone; and the exit flush
    is bounded."""
    print("\n=== pool: on by default, ledger, throttle plumbing, dead server")
    import http.server
    import os
    import shutil
    import urllib.request

    import bgtracker as bg
    import collect
    import pool as pool_mod

    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="bgtracker-test-pool-"))
    SFILE.unlink(missing_ok=True)

    # ---- the real ingest server, on loopback, with a throwaway database
    os.environ["BGTRACKER_DB"] = str(tmp / "games.db")
    sys.path.insert(0, str(ROOT / "server"))
    import importlib
    import ingest
    importlib.reload(ingest)               # re-read the env on a warm import
    with ingest.db() as c:
        c.executescript(ingest.SCHEMA)
        ingest.migrate(c)
        c.commit()

    class Counting(ingest.Handler):
        posts = []

        def do_POST(self):
            Counting.posts.append(self.path)
            super().do_POST()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Counting)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def health():
        with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
            return json.loads(r.read())

    # ---- point collect + pool at throwaway files, never the real ones
    saved = (collect.DATA, collect.OUT, collect.CLIENT_ID_FILE,
             pool_mod.SENT_FILE, bg.HS_LOGS)
    collect.DATA = tmp / "data"
    collect.OUT = collect.DATA / "games.jsonl"
    collect.CLIENT_ID_FILE = collect.DATA / "client_id"
    pool_mod.SENT_FILE = collect.DATA / "uploaded.json"
    bg.HS_LOGS = tmp / "no-logs-here"      # the full-history mine finds nothing
    try:
        collect.DATA.mkdir()
        games = [{"date": "2026_08_10", "game_id": f"Hearthstone_x:{i}",
                  "hero": "BG26_HERO_104", "place": (i % 8) + 1, "duo": False,
                  "tribes": ["MURLOC", "BEAST"], "offered_heroes": [],
                  "offered_trinkets": [], "picked_trinkets": [],
                  "source_log": "Hearthstone_x"} for i in range(3)]
        # Game 0 predates the duos detector: no mode known. The server must
        # store it unclassified, and the re-mine below must classify it.
        games[0]["duo"] = None
        collect.OUT.write_text(
            "".join(json.dumps(g) + "\n" for g in games), encoding="utf-8")

        # -- default ON, and --no-upload wins for a run without writing it --
        s = store.Settings.load(SFILE)
        s.set("upload_url", base)
        p = pool_mod.Pool(s, spacing=0.01, start_delay=0)
        flagged = store.Settings.load(SFILE, overrides={"upload": False})
        p_flag = pool_mod.Pool(flagged, spacing=0.01, start_delay=0)
        flagged.set("time", "past-seven")            # save something else
        on_disk = json.loads(SFILE.read_text(encoding="utf-8"))
        print(f"  default: enabled={p.enabled()}; with --no-upload: "
              f"enabled={p_flag.enabled()}, upload source="
              f"{flagged.source_of('upload')}, file holds {on_disk}")
        if not p.enabled() or p_flag.enabled():
            print("    FAIL: the default or the flag override is wrong")
            ok = False
        if "upload" in on_disk:
            print("    FAIL: --no-upload leaked into the settings file")
            ok = False
        # enabled() is the gate the sharing thread checks before every sync;
        # drive the flagged pool through that same gate, as the thread would.
        if p_flag.enabled():
            p_flag._sync(logs=[])
        if Counting.posts:
            print("    FAIL: a --no-upload run still uploaded")
            ok = False

        # -- the first sync backfills, the ledger stops the second ----------
        p._sync(logs=[])
        h = health()
        first = list(Counting.posts)
        p._sync(logs=[])
        print(f"  backfill: {len(first)} POST(s), server now holds "
              f"{h['games']} games; re-sync made "
              f"{len(Counting.posts) - len(first)} request(s)")
        if h["games"] != 3 or len(first) != 1:
            print("    FAIL: the backfill did not land as one batch of 3")
            ok = False
        if len(Counting.posts) != len(first):
            print("    FAIL: the ledger did not stop a re-upload")
            ok = False

        # -- a record that gained data since it was sent goes out again -----
        games[0]["duo"] = True                        # a re-mine filled duo in
        collect.OUT.write_text(
            "".join(json.dumps(g) + "\n" for g in games), encoding="utf-8")
        before = len(Counting.posts)
        p._sync(logs=[])
        h = health()
        print(f"  refilled record: {len(Counting.posts) - before} more POST(s), "
              f"server counts duo={h['duo']} (was 0), games={h['games']}")
        if len(Counting.posts) - before != 1 or h["duo"] != 1 or h["games"] != 3:
            print("    FAIL: the duo backfill never reached the server")
            ok = False

        # -- a dead server: no raise, no block, nothing marked sent ---------
        games.append({"date": "2026_08_11", "game_id": "Hearthstone_x:99",
                      "hero": "BG26_HERO_104", "place": 1, "duo": False,
                      "tribes": [], "offered_heroes": [], "offered_trinkets": [],
                      "picked_trinkets": [], "source_log": "Hearthstone_x"})
        collect.OUT.write_text(
            "".join(json.dumps(g) + "\n" for g in games), encoding="utf-8")
        s.set("upload_url", "http://127.0.0.1:9")     # nothing listens there
        t0 = time.time()
        p._sync(logs=[])
        took = time.time() - t0
        print(f"  dead server: returned in {took:.2f}s, error="
              f"{(p.last or {}).get('error')!r}")
        if took > 10 or not (p.last or {}).get("error"):
            print("    FAIL: a dead server raised, hung, or claimed success")
            ok = False
        ledger = json.loads(pool_mod.SENT_FILE.read_text(encoding="utf-8"))
        if len(ledger.get("sent", {})) != 3:
            print("    FAIL: a failed upload was marked sent")
            ok = False

        # -- the server comes back: the missed game goes at the next boundary
        s.set("upload_url", base)
        p._sync(logs=[])
        h = health()
        print(f"  server back: games={h['games']}, ledger holds "
              f"{len(json.loads(pool_mod.SENT_FILE.read_text(encoding='utf-8'))['sent'])}")
        if h["games"] != 4:
            print("    FAIL: the game missed during the outage never arrived")
            ok = False

        # -- the opt-out persists, and the thread wiring shuts down bounded -
        s.set("upload", False)
        s2 = store.Settings.load(SFILE)
        p2 = pool_mod.Pool(s2, spacing=0.01, start_delay=0)
        print(f"  opt-out: reloaded upload={s2.get('upload')!r} "
              f"({s2.source_of('upload')}), pool enabled={p2.enabled()}")
        if s2.get("upload") is not False or p2.enabled():
            print("    FAIL: the opt-out did not persist")
            ok = False
        p2.start()
        p2.on_game()
        t0 = time.time()
        p2.on_exit(timeout=2.0)
        took = time.time() - t0
        print(f"  exit flush: returned in {took:.2f}s (bound is ~2s)")
        if took > 3.0:
            print("    FAIL: shutdown waited past its bound")
            ok = False
        if Counting.posts and Counting.posts[-1] != "/upload":
            print("    FAIL: something other than /upload was posted")
            ok = False
    finally:
        srv.shutdown()
        (collect.DATA, collect.OUT, collect.CLIENT_ID_FILE,
         pool_mod.SENT_FILE, bg.HS_LOGS) = saved
        os.environ.pop("BGTRACKER_DB", None)
        shutil.rmtree(tmp, ignore_errors=True)
        SFILE.unlink(missing_ok=True)
    return bool(ok)


def main():
    results = {
        "store": test_store(),
        "restart": test_persistence(),
        "panel": test_panel(),
        "what to show": test_window_toggle(),
        "geometry": test_geometry(),
        "pool": test_pool(),
    }
    SFILE.unlink(missing_ok=True)
    POS_FILE.unlink(missing_ok=True)
    print("\n" + "  ".join(f"{k}={'PASS' if v else 'FAIL'}"
                           for k, v in results.items()))
    print("PASS" if all(results.values()) else "FAIL")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
