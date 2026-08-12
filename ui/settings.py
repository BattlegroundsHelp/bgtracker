"""The settings panel: the one window here that is the OPPOSITE of an overlay.

Every other window in this package is a frameless, always-on-top,
transparent-color surface that clicks fall straight through, because it sits
on a fullscreen game and must never steal a click meant for a card. This one
has to take real input, so it is built the other way round on purpose, and the
differences are the whole point rather than an oversight:

  * it is a plain ``tk.Toplevel``: NO ``overrideredirect``, so the operating
    system gives it a title bar to drag and a close button;
  * NO ``-transparentcolor``: the key color is a HOLE, and a hole cannot be
    clicked. That single attribute is what would make a settings panel look
    right and do nothing;
  * NO ``WS_EX_TRANSPARENT`` / ``WS_EX_NOACTIVATE``: ``BadgeStrip.clickthrough``
    is never called on it, and nothing here touches the extended style;
  * ``-topmost`` YES, and for a measured reason rather than for symmetry: the
    game is borderless fullscreen, so a panel that is merely focused still
    opens BEHIND it (screenshotted against a running client - the panel was
    nowhere on screen). Topmost is a z-order property only; it has nothing to
    do with hit testing, so the panel still takes every click. It is also
    registered in the manager's focus allow-set
    (``WindowManager.extra_hwnds``), so giving it focus does not read as the
    game losing focus and withdraw the whole overlay while you are dragging a
    slider. Watching the overlay resize while you drag IS the feature;
  * closing it HIDES it. The overlay keeps running, and the gear in the
    bgtracker window's header brings the same panel back.

It also draws with real widgets rather than a canvas: a canvas panel would
need a hand-rolled hit box per control, and this is the one surface where the
platform's own checkbox is both cheaper and more correct (keyboard, focus
ring, high-contrast themes).

WHAT IS LIVE AND WHAT IS NOT, because a settings panel that quietly needs a
restart is worse than one that says so:

    UI scale, badge nudge, every window on/off   applied as you change them
    update settings, the data opt-in             applied immediately
    MMR bracket, time window, Duos, stats feed   next start, and the row says so

The three that wait are the ones the log reader loads ONCE, when it starts: the
hero, trinket, minion and comp tables for that bracket. Reloading them under a
running game would mean re-scoring an offer that is already on screen from a
different table, which is exactly the "the number changed while I was reading
it" class of bug the per-window contract exists to prevent.

NOTHING HERE INVENTS A VALUE. Where a number is not known - the badge size
with no game window open, the last update check before one has happened, the
last upload before there has been one - the row shows what it really is and
says why.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import font as tkfont

import bgtracker as bg
import settings as store
import update
from paths import app_dir, bundle_dir

from . import WINDOWS
from .base import (ACCENT, AMBER, BAD, DIM, GOOD, LINE, PANEL, PANEL_HI, SOFT,
                   TEXT, auto_scale, badge_scale, get_badge_scale, get_scale,
                   hs_rect, set_badge_scale, set_scale)

# The panel is drawn at these point sizes at scale 1.0 and multiplied by the UI
# scale like everything else - it is the window where somebody on a 4K screen
# goes to fix a 4K problem, so it cannot itself be unreadable while they do it.
BASE_W, BASE_H = 560, 700
F_HEAD, F_LABEL, F_SUB, F_TINY = 11, 10, 9, 8

INPUT_BG = "#0e1014"


def _first_sentence(text, cap=112):
    """A window module's own one-line description, from its docstring.

    The WHAT TO SHOW list is generated from the registry so a window added
    later cannot be forgotten - and its description is generated the same way,
    from the module that defines it, so that cannot be forgotten either.
    """
    text = " ".join((text or "").split())
    if not text:
        return ""
    dot = text.find(". ")
    if dot > 0:
        text = text[:dot]
    text = text.rstrip(".")
    return text if len(text) <= cap else text[:cap - 1].rstrip() + "…"


def _community_sources():
    """The community feed's table urls, four tables plus their Duos twins.

    Read out of ``sources.example.json``, which ships in the build, rather than
    written out again here: two copies of a url is one copy that goes stale the
    day the feed moves. Falls back to building them off the same host constant
    the uploader uses, if that file is ever missing.
    """
    for base in (app_dir(), bundle_dir()):
        try:
            raw = json.loads((base / "sources.example.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        out = {k: v for k, v in raw.items()
               if not k.startswith("_") and isinstance(v, str)}
        if out:
            return out
    host = store.COMMUNITY_UPLOAD.rstrip("/")
    return {k + d: f"{host}/{k}{'-duo' if d else ''}-{{mmr}}-{{time}}.json"
            for k in ("heroes", "trinkets", "cards", "comps")
            for d in ("", "_duo")}


class SettingsPanel(tk.Toplevel):
    """The panel. One instance, hidden and re-shown rather than rebuilt."""

    SOURCE_KINDS = ("heroes", "trinkets", "cards", "comps")

    def __init__(self, app, settings, manager):
        super().__init__(manager.root)
        self.app, self.s, self.manager = app, settings, manager
        self.title("bgtracker settings")
        self.configure(bg=PANEL)
        self.protocol("WM_DELETE_WINDOW", self.hide)
        self.minsize(420, 320)
        # Over the game, not under it - see the note in the module docstring.
        # Z-order only: this window still activates and still takes clicks.
        self.attributes("-topmost", True)

        self._fonts = []          # (font, base point size)
        self._wrapped = []        # (label, base wraplength) - wraps in px too
        self._syncing = False     # a control is being set in code, not by hand
        self.f_head = self._font(F_HEAD, "bold")
        self.f_label = self._font(F_LABEL)
        self.f_sub = self._font(F_SUB)
        self.f_tiny = self._font(F_TINY)

        self._build()
        self._apply_own_scale()
        # The manager's focus poll treats anything in extra_hwnds as "still
        # ours", so giving the panel focus does not hide the overlay.
        try:
            manager.extra_hwnds.append(self.winfo_id())
        except Exception:
            pass
        self.refresh()

    # ------------------------------------------------------------- plumbing

    def _font(self, size, weight="normal"):
        f = tkfont.Font(root=self, family="Segoe UI", size=size, weight=weight)
        self._fonts.append((f, size))
        return f

    def _apply_own_scale(self):
        """Resize the panel's own text and window with the UI scale.

        The panel is a normal DPI-aware window, so on a 4K display it is drawn
        in real pixels and would be exactly as small as the overlay it is there
        to fix. Its fonts therefore follow the same scale, which also makes the
        slider prove itself: drag it and this window grows under your hand.
        """
        s = get_scale()
        for f, base in self._fonts:
            try:
                f.configure(size=max(1, int(round(base * s))))
            except Exception:
                pass
        for lbl, base in self._wrapped:
            try:
                lbl.configure(wraplength=int(base * s))
            except Exception:
                pass
        try:
            sh = self.winfo_screenheight() - 80
            self.geometry(f"{int(BASE_W * s)}x{min(int(BASE_H * s), sh)}")
        except Exception:
            pass

    def show(self):
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass
        self.refresh()

    def hide(self):
        self.withdraw()

    # -------------------------------------------------------------- widgets

    def _section(self, title, note=None):
        wrap = tk.Frame(self.body, bg=PANEL)
        wrap.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(wrap, text=title, bg=PANEL, fg=ACCENT, font=self.f_head,
                 anchor="w").pack(fill="x")
        tk.Frame(wrap, bg=LINE, height=1).pack(fill="x", pady=(2, 6))
        if note:
            self._sub(wrap, note)
        return wrap

    def _sub(self, parent, text, fill=DIM, font=None):
        lbl = tk.Label(parent, text=text, bg=PANEL, fg=fill,
                       font=font or self.f_sub, anchor="w", justify="left",
                       wraplength=BASE_W - 60)
        lbl.pack(fill="x", pady=(0, 2))
        self._wrapped.append((lbl, BASE_W - 60))
        return lbl

    def _check(self, parent, text, var, command):
        c = tk.Checkbutton(parent, text=text, variable=var, command=command,
                           bg=PANEL, fg=TEXT, selectcolor=INPUT_BG,
                           activebackground=PANEL, activeforeground=TEXT,
                           highlightthickness=0, bd=0, anchor="w",
                           font=self.f_label, takefocus=True)
        c.pack(fill="x")
        return c

    def _button(self, parent, text, command, side="left"):
        b = tk.Button(parent, text=text, command=command, bg=PANEL_HI, fg=TEXT,
                      activebackground=ACCENT, activeforeground="#101116",
                      relief="flat", bd=0, padx=10, pady=3, font=self.f_sub,
                      cursor="hand2")
        b.pack(side=side, padx=(0, 6))
        return b

    def _slider(self, parent, lo, hi, step, var, command, release):
        sc = tk.Scale(parent, from_=lo, to=hi, resolution=step, variable=var,
                      orient="horizontal", showvalue=False, command=command,
                      bg=PANEL, fg=TEXT, troughcolor=INPUT_BG, bd=0,
                      highlightthickness=0, activebackground=ACCENT,
                      sliderrelief="flat", length=240)
        sc.pack(side="left")
        sc.bind("<ButtonRelease-1>", release)
        return sc

    def _option(self, parent, var, values, command):
        m = tk.OptionMenu(parent, var, *values, command=command)
        m.configure(bg=PANEL_HI, fg=TEXT, activebackground=ACCENT, relief="flat",
                    bd=0, highlightthickness=0, font=self.f_sub, width=11,
                    anchor="w")
        m["menu"].configure(bg=PANEL_HI, fg=TEXT, activebackground=ACCENT,
                            activeforeground="#101116", bd=0, font=self.f_sub)
        m.pack(side="left", padx=(0, 8))
        return m

    # ---------------------------------------------------------------- build

    def _build(self):
        outer = tk.Frame(self, bg=PANEL)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0, bd=0)
        bar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg=PANEL)
        self.body.bind("<Configure>",
                       lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # The wheel goes to whatever has the pointer, and over a checkbox that
        # is the checkbox, not the canvas - so the binding is on the panel.
        self.bind("<MouseWheel>",
                  lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        self._build_problems()
        self._build_display()
        self._build_data()
        self._build_windows()
        self._build_updates()
        self._build_footer()

    def _build_problems(self):
        box = tk.Frame(self.body, bg=PANEL)
        box.pack(fill="x", padx=16, pady=(12, 0))
        self.problem_lbl = tk.Label(box, text="", bg=PANEL, fg=BAD,
                                    font=self.f_sub, anchor="w", justify="left",
                                    wraplength=BASE_W - 60)
        self._wrapped.append((self.problem_lbl, BASE_W - 60))
        self.problem_lbl.pack(fill="x")

    # -- DISPLAY -----------------------------------------------------------

    def _build_display(self):
        sec = self._section("DISPLAY")
        saved = self.s.get("ui_scale")
        self.auto_var = tk.BooleanVar(value=saved is None)
        self._check(sec, "Size everything from the display, automatically",
                    self.auto_var, self._on_auto)
        self.auto_lbl = self._sub(sec, "")

        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="UI scale", bg=PANEL, fg=TEXT, font=self.f_label,
                 width=9, anchor="w").pack(side="left")
        self.scale_var = tk.DoubleVar(value=float(saved or get_scale()))
        self.scale_slider = self._slider(row, store.SCALE_MIN, store.SCALE_MAX,
                                         0.05, self.scale_var, self._on_scale,
                                         self._save_scale)
        self.scale_lbl = tk.Label(row, text="", bg=PANEL, fg=SOFT,
                                  font=self.f_label, width=6, anchor="w")
        self.scale_lbl.pack(side="left", padx=(8, 0))

        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        tk.Label(row, text="Badges", bg=PANEL, fg=TEXT, font=self.f_label,
                 width=9, anchor="w").pack(side="left")
        self.badge_var = tk.DoubleVar(value=float(self.s.get("badge_scale")))
        self.badge_slider = self._slider(row, store.BADGE_MIN, store.BADGE_MAX,
                                         0.05, self.badge_var, self._on_badge,
                                         self._save_badge)
        self.badge_lbl = tk.Label(row, text="", bg=PANEL, fg=SOFT,
                                  font=self.f_label, width=6, anchor="w")
        self.badge_lbl.pack(side="left", padx=(8, 0))
        self.badge_note = self._sub(sec, "")

    def _on_auto(self):
        if self.auto_var.get():
            self.s.set("ui_scale", None)
            # A Scale fires its command whenever its variable changes, not only
            # when a hand moves it. Moving the slider to where automatic landed
            # therefore looks exactly like a drag, and _on_scale would untick
            # the box the user just ticked. Hence the guard rather than a
            # cleverer callback.
            self._syncing = True
            try:
                self.scale_var.set(set_scale(auto_scale()))
            finally:
                self._syncing = False
        else:
            self.s.set("ui_scale", round(float(self.scale_var.get()), 2))
            set_scale(self.scale_var.get())
        self._after_scale()

    def _on_scale(self, _value=None):
        """Live on every pixel of the drag. The file is written on release."""
        if self._syncing:
            return
        if self.auto_var.get():
            self.auto_var.set(False)
        set_scale(self.scale_var.get())
        self._after_scale()

    def _save_scale(self, _e=None):
        if not self.auto_var.get():
            self.s.set("ui_scale", round(float(self.scale_var.get()), 2))

    def _after_scale(self):
        self._apply_own_scale()
        self._refresh_display()

    def _on_badge(self, _value=None):
        set_badge_scale(self.badge_var.get())
        self._refresh_display()

    def _save_badge(self, _e=None):
        self.s.set("badge_scale", round(float(self.badge_var.get()), 2))

    def _refresh_display(self):
        self.scale_lbl.configure(text=f"{get_scale():.2f}x")
        self.badge_lbl.configure(text=f"{get_badge_scale():.2f}x")
        rect = hs_rect()
        if rect is not None:
            gh = rect.bottom - rect.top
            src = f"the Hearthstone window is {rect.right - rect.left}x{gh}"
            eff = f"{badge_scale(gh):.2f}x on screen right now"
        else:
            src = "Hearthstone is not open, so this reads your main screen"
            eff = "unknown until the game is open"
        self.auto_lbl.configure(
            text=f"Automatic picks {auto_scale():.2f}x right now ({src}). The "
                 f"overlay was drawn for a 1920x1080 game window, so a 4K game "
                 f"wants about 2.00x.")
        self.badge_note.configure(
            text="Badges are the numbers printed on the cards themselves. They "
                 "already follow the game window on their own, so this only "
                 f"nudges them. Size over the cards: {eff}.")

    # -- DATA --------------------------------------------------------------

    def _build_data(self):
        sec = self._section("DATA")
        self.upload_var = tk.BooleanVar(value=bool(self.s.get("upload")))
        self._check(sec, "Share my finished games with the community feed",
                    self.upload_var, self._on_upload_toggle)
        # This copy is a list of facts, so it is kept EXACTLY in step with what
        # collect.upload() builds: every field in its record is named here, in
        # order, and nothing else is sent with it. Change one, change both -
        # tests/test_settings.py holds the two together.
        self.data_lbl = self._sub(sec,
                  "Off by default: while this box is clear bgtracker does not "
                  "upload your games. Ticked, one record per finished game is "
                  "sent, holding exactly these fields: a scrambled game id, "
                  "the date, the hero you played, your placement, whether it "
                  "was Duos, the lobby tribes, the heroes you were offered, "
                  "the trinkets you were offered, the trinkets you picked, "
                  "the first 8 characters of this machine's random client id "
                  "(sent as is, so the feed can group games from one install "
                  "without knowing whose it is), and the bgtracker version "
                  "that mined it. No name, no battletag, no log files. The "
                  "pooled numbers are free for everyone and are never "
                  "paywalled. Sending happens shortly after bgtracker starts, "
                  "at most once every twelve hours; Share now sends "
                  "immediately.")
        self.netcheck_lbl = self._sub(sec,
                  "Separate from this box: when the update check is on (it is "
                  "on unless you turn it off), bgtracker asks its update "
                  "server for the newest version number once on every start. "
                  "By default that is the same machine that hosts the "
                  "community feed, and like any web request it shows the "
                  "server your network address and your bgtracker version. "
                  "Turn it off under UPDATES below, or start with "
                  "--no-update-check.")
        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(2, 0))
        tk.Label(row, text="Feed", bg=PANEL, fg=TEXT, font=self.f_label,
                 width=9, anchor="w").pack(side="left")
        self.url_var = tk.StringVar(value=str(self.s.get("upload_url")))
        e = tk.Entry(row, textvariable=self.url_var, bg=INPUT_BG, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=self.f_sub)
        e.pack(side="left", fill="x", expand=True, padx=(0, 8))
        e.bind("<FocusOut>", self._save_url)
        e.bind("<Return>", self._save_url)
        self.share_btn = self._button(row, "Share now", self._share_now)
        self.share_lbl = self._sub(sec, "")

        # -- which numbers the overlay reads
        tk.Frame(sec, bg=PANEL, height=8).pack()
        tk.Label(sec, text="Numbers come from", bg=PANEL, fg=TEXT,
                 font=self.f_label, anchor="w").pack(fill="x")
        self.source_var = tk.StringVar(value=self._detect_source())
        for key, label in (("community", "the community feed (everyone's shared games)"),
                           ("local", "your own games only (collected on this machine)"),
                           ("custom", "whatever sources.json already says")):
            tk.Radiobutton(sec, text=label, variable=self.source_var, value=key,
                           command=self._on_source, bg=PANEL, fg=TEXT,
                           selectcolor=INPUT_BG, activebackground=PANEL,
                           activeforeground=TEXT, highlightthickness=0, bd=0,
                           anchor="w", font=self.f_sub).pack(fill="x")
        self.source_lbl = self._sub(sec, "")
        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(2, 0))
        self.feed_btn = self._button(row, "Rebuild my own feed", self._rebuild_feed)
        self.feed_lbl = tk.Label(row, text="", bg=PANEL, fg=DIM, font=self.f_sub,
                                 anchor="w")
        self.feed_lbl.pack(side="left")

        # -- bracket / period / mode
        tk.Frame(sec, bg=PANEL, height=8).pack()
        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Rank", bg=PANEL, fg=TEXT, font=self.f_label,
                 width=9, anchor="w").pack(side="left")
        self.mmr_var = tk.StringVar(value=str(self.s.get("mmr")))
        self._option(row, self.mmr_var, store.MMR_CHOICES, self._on_mmr)
        self.mmr_lbl = tk.Label(row, text="", bg=PANEL, fg=DIM, font=self.f_sub,
                                anchor="w")
        self.mmr_lbl.pack(side="left")

        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="Period", bg=PANEL, fg=TEXT, font=self.f_label,
                 width=9, anchor="w").pack(side="left")
        self.time_var = tk.StringVar(value=str(self.s.get("time")))
        self._option(row, self.time_var, store.TIME_CHOICES, self._on_time)
        self.time_lbl = tk.Label(row, text="", bg=PANEL, fg=DIM, font=self.f_sub,
                                 anchor="w")
        self.time_lbl.pack(side="left")

        self.duo_var = tk.BooleanVar(value=bool(self.s.get("duo")))
        self._check(sec, "Duos (hero numbers only: Duos has no comp, trinket or "
                         "minion feed)", self.duo_var, self._on_duo)
        self.restart_lbl = self._sub(sec, "")

    def _detect_source(self):
        """Which of the three presets sources.json currently matches."""
        import collect
        cur = {k: bg.raw_source(k) for k in self.SOURCE_KINDS}
        if not any(cur.values()):
            return "custom"
        comm = _community_sources()
        if all(cur[k] == comm.get(k) for k in self.SOURCE_KINDS):
            return "community"
        if all(cur[k] == collect.LOCAL_FEED.get(k) for k in self.SOURCE_KINDS):
            return "local"
        return "custom"

    def _write_sources(self, table):
        """Rewrite only the table keys, keeping everything else in the file.

        sources.json is the user's own file and can carry keys this panel knows
        nothing about (`updates` is one), so it is merged, never replaced.
        """
        p = app_dir() / "sources.json"
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(cur, dict):
                cur = {}
        except Exception:
            cur = {}
        cur.update(table)
        try:
            p.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        except Exception as e:
            self.source_lbl.configure(text=f"could not write sources.json: {e}",
                                      fg=BAD)
            return False
        return True

    def _on_source(self):
        choice = self.source_var.get()
        if choice == "community":
            self._write_sources(_community_sources())
        elif choice == "local":
            import collect
            self._write_sources(collect.LOCAL_FEED)
        self._refresh_data()

    def _on_mmr(self, *_):
        self.s.set("mmr", self.mmr_var.get())
        self._refresh_data()

    def _on_time(self, *_):
        self.s.set("time", self.time_var.get())
        self._refresh_data()

    def _on_duo(self):
        self.s.set("duo", bool(self.duo_var.get()))
        self._refresh_data()

    def _save_url(self, _e=None):
        url = self.url_var.get().strip()
        if url and url != self.s.get("upload_url"):
            self.s.set("upload_url", url)
        self._refresh_data()

    def _on_upload_toggle(self):
        self.s.set("upload", bool(self.upload_var.get()))
        self._refresh_data()

    def _share_now(self):
        """Collect what the log history holds, then send it. In a thread.

        Only ever from this button, or from the opt-in being on at startup (see
        overlay.py). The result line is whatever actually happened, with the
        error text verbatim when there is one.
        """
        if not self.upload_var.get():
            self.share_lbl.configure(text="tick the box first: nothing is sent "
                                          "while it is clear", fg=AMBER)
            return
        url = self.url_var.get().strip()
        if not url:
            self.share_lbl.configure(text="no feed address to send to", fg=BAD)
            return
        self.share_btn.configure(state="disabled")
        self.share_lbl.configure(text="collecting your games and sending...", fg=SOFT)

        def work():
            import collect
            try:
                collect.collect()
                res = collect.upload(url) or {}
            except Exception as e:
                res = {"error": f"{type(e).__name__}: {e}"}
            self.after(0, self._share_done, res)

        threading.Thread(target=work, daemon=True).start()

    def _share_done(self, res):
        self.share_btn.configure(state="normal")
        if res.get("error"):
            self.share_lbl.configure(text=f"share failed: {res['error']}", fg=BAD)
            return
        if not res.get("sent"):
            self.share_lbl.configure(
                text=f"nothing to share: {res.get('note') or 'no games yet'}",
                fg=SOFT)
            return
        self.s.set("last_upload", time.time())
        self.share_lbl.configure(
            text=f"shared {res.get('sent', 0)} games, {res.get('stored', 0)} of "
                 f"them new to the feed", fg=GOOD)

    def _rebuild_feed(self):
        self.feed_btn.configure(state="disabled")
        self.feed_lbl.configure(text="mining your logs...")

        def work():
            import collect
            try:
                collect.collect()
                collect.local_feed()
                msg = "rebuilt from your own games"
            except Exception as e:
                msg = f"failed: {type(e).__name__}: {e}"
            self.after(0, self._feed_done, msg)

        threading.Thread(target=work, daemon=True).start()

    def _feed_done(self, msg):
        self.feed_btn.configure(state="normal")
        self.feed_lbl.configure(text=msg)
        self._refresh_data()

    def _refresh_data(self):
        self.share_btn.configure(state="normal" if self.upload_var.get()
                                 else "disabled")
        last = self.s.get("last_upload")
        self.share_lbl.configure(
            text="last shared: " + (time.strftime("%Y-%m-%d %H:%M",
                                                  time.localtime(last))
                                    if last else "never from this machine"),
            fg=DIM)
        cur = bg.raw_source("heroes")
        feed = app_dir() / "data" / "feed"
        n_feed = len(list(feed.glob("*.json"))) if feed.is_dir() else 0
        self.source_lbl.configure(
            text="hero numbers load from: " + (cur or "nothing configured, so "
                 "offers are named but carry no numbers"), fg=DIM)
        self.feed_lbl.configure(
            text=(f"{n_feed} files in data/feed" if n_feed
                  else "no personal feed built yet"))
        # Short on purpose: this label sits on one row beside the control and
        # is not wrapped, so a long sentence is simply cut off (seen on screen).
        # The date is the one from settings.py's table - a rating threshold
        # with no date reads as a live figure, and the ladder inflates.
        self.mmr_lbl.configure(
            text=f"= {store.MMR_LABEL.get(self.mmr_var.get(), '?')}, "
                 f"measured {store.MMR_MEASURED}")
        self.time_lbl.configure(text={
            "last-patch": "since the current patch (the safe default)",
            "past-seven": "the last seven days",
            "past-three": "the last three days",
            "all-time": "everything the feed holds",
        }.get(self.time_var.get(), ""))

        flags = [f"--{k}" for k in ("mmr", "time", "duo")
                 if self.s.source_of(k) == "flag"]
        note = ("These are read once, when the log reader starts, so changing "
                "them here takes effect the next time bgtracker starts. The "
                "same goes for switching feed.")
        if flags:
            note += (" " + ", ".join(flags) + " was given on the command line, "
                     "so it wins for this run and is not written to the file.")
        self.restart_lbl.configure(text=note)

    # -- WHAT TO SHOW ------------------------------------------------------

    def _build_windows(self):
        sec = self._section(
            "WHAT TO SHOW",
            "One switch per overlay window, generated from the registry in "
            "ui/__init__.py so a window added later appears here on its own. "
            "Off means the window is not built at all: no panel, no badges on "
            "the cards, nothing routed to it.")
        self.win_vars = {}
        self.win_checks = {}          # KEY -> the checkbox (the test reads state)
        for cls in WINDOWS:
            enabled = self.s.window_enabled(cls.KEY)
            if cls.QUIT_BUTTON and not enabled:
                # A hand-edited settings file can say off; heal it, because off
                # would strand the user (see the refusal below).
                self.s.set_window_enabled(cls.KEY, True)
                try:
                    self.app.set_window_enabled(cls.KEY, True)
                except Exception:
                    traceback.print_exc()
                enabled = True
            var = tk.BooleanVar(value=enabled)
            self.win_vars[cls.KEY] = var
            chk = self._check(sec, f"{cls.TITLE or cls.KEY}  ({cls.KEY})", var,
                              lambda k=cls.KEY: self._on_window(k))
            self.win_checks[cls.KEY] = chk
            mod = sys.modules.get(cls.__module__)
            blurb = _first_sentence(getattr(mod, "__doc__", ""))
            extra = []
            if cls.QUIT_BUTTON:
                # Refused rather than allowed-and-regretted: every other
                # overlay surface is click-through, so the gear and the X on
                # this window are the only clicks the overlay can ever take
                # once this panel is closed. The panel's own Quit button is no
                # substitute - the panel can be closed, and "open on start"
                # can be off, which would leave a running overlay with no
                # visible way to reach settings or quit short of killing the
                # process.
                chk.configure(state="disabled")
                extra.append("always on: it carries the X that quits and the "
                             "gear that reopens this panel, so without it "
                             "there would be no way back in")
            if cls.KEY == "players" and not bg.MSYNC_EXE.exists():
                extra.append("needs the optional memory reader, which is not "
                             "built here, so it never opens")
            lbl = tk.Label(sec, text=blurb + ("  -  " + "; ".join(extra) if extra else ""),
                           bg=PANEL, fg=DIM, font=self.f_tiny, anchor="w",
                           justify="left", wraplength=BASE_W - 80)
            lbl.pack(fill="x", padx=(22, 0), pady=(0, 3))
            self._wrapped.append((lbl, BASE_W - 80))

    def _on_window(self, key):
        cls = next((c for c in WINDOWS if c.KEY == key), None)
        if cls is not None and cls.QUIT_BUTTON:
            # Defence in depth behind the greyed-out checkbox: whatever fires
            # this, the quit window stays on (the reason is on its row).
            self.win_vars[key].set(True)
            return
        on = bool(self.win_vars[key].get())
        self.s.set_window_enabled(key, on)
        try:
            self.app.set_window_enabled(key, on)
        except Exception:
            traceback.print_exc()

    # -- UPDATES -----------------------------------------------------------

    def _build_updates(self):
        sec = self._section("UPDATES")
        self.ver_lbl = self._sub(sec, "", fill=TEXT, font=self.f_label)
        self.check_var = tk.BooleanVar(value=update.checks_enabled())
        self._check(sec, "Look for a new version when bgtracker starts",
                    self.check_var, self._on_check_toggle)
        self.upd_lbl = self._sub(sec, "")
        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(2, 0))
        self.check_btn = self._button(row, "Check now", self._check_now)
        self.notes_btn = self._button(row, "What changed", self._open_notes)
        self.install_btn = self._button(row, "Download and install", self._install)
        self.upd_src = self._sub(sec, "")
        self._upd_watching = False    # one poll chain at a time
        self._upd_gave_up = False     # polled long past the timeout: no check ran

    def _on_check_toggle(self):
        update.set_checks_enabled(bool(self.check_var.get()))
        # BGTRACKER_NO_UPDATE_CHECK outranks the stored setting, so read the
        # truth back rather than trusting the box we just ticked.
        self.check_var.set(update.checks_enabled())
        self._refresh_updates()

    def _check_now(self):
        self.check_btn.configure(state="disabled")
        self.upd_lbl.configure(text="asking the update server...", fg=SOFT)

        def work():
            update.check()
            self.after(0, self._check_done)

        threading.Thread(target=work, daemon=True).start()

    def _check_done(self):
        self.check_btn.configure(state="normal")
        self._refresh_updates()

    def _open_notes(self):
        u = update.result()
        target = (u.notes or u.url) if u else None
        # Defence in depth behind parse_manifest's https rule: on Windows,
        # webbrowser.open() falls through to os.startfile(), which RUNS a UNC
        # or file:/// path as readily as it opens a page - and the manifest
        # still travels plain http. Nothing that is not https leaves here,
        # even if a poisoned result is somehow sitting in update.result().
        if target and target.lower().startswith("https://"):
            webbrowser.open(target)

    def _install(self):
        u = update.result()
        self.install_btn.configure(state="disabled")
        self.upd_lbl.configure(text="downloading...", fg=SOFT)

        def work():
            try:
                update.install(u)
            except Exception as e:
                self.after(0, self._install_failed, str(e))
                return
            # install() hands the swap to a helper that waits for THIS process
            # to exit and gives up after 60 seconds, so quitting is part of
            # installing rather than a separate decision.
            self.after(0, self.app.quit)

        threading.Thread(target=work, daemon=True).start()

    def _install_failed(self, msg):
        self.install_btn.configure(state="normal")
        self.upd_lbl.configure(text=msg, fg=BAD)

    def _watch_updates(self):
        """Poll update.result() until the on-start check lands.

        The panel opens on start, the on-start check answers a second or two
        LATER on its own thread, and nothing calls back into this panel
        (update.start_check belongs to overlay.py's startup). Without this the
        UPDATES row showed the one-shot read it took while the check was still
        in flight and never changed again. result() is a lock-guarded read of
        memory - no network - so polling it is free; the chain stops the
        moment an answer lands, or after ~20s (three times the check's own
        timeout), when "no check has run" stops being a race and becomes the
        truth (started with --no-update-check, for instance).
        """
        if self._upd_watching or self._upd_gave_up:
            return
        self._upd_watching = True
        state = {"tries": 0}

        def poll():
            try:
                state["tries"] += 1
                if update.result() is not None:
                    self._upd_watching = False
                    self._refresh_updates()
                    return
                if state["tries"] >= 28:            # ~20s at 700ms a step
                    self._upd_watching = False
                    self._upd_gave_up = True
                    self._refresh_updates()
                    return
                self.after(700, poll)
            except tk.TclError:
                self._upd_watching = False          # the panel is gone

        self.after(700, poll)

    def _refresh_updates(self):
        self.ver_lbl.configure(text=f"You are running {update.VERSION}")
        u, at = update.result(), update.checked_at()
        when = time.strftime("%H:%M:%S", time.localtime(at)) if at else None
        if u is None:
            if not update.checks_enabled():
                txt, col = ("The check on start is off, so this build has not "
                            "been compared with anything.", DIM)
            elif self._upd_gave_up:
                txt, col = ("No check has run this session.", DIM)
            else:
                # The on-start check is on and could still land: say checking
                # and watch for it, rather than freezing a stale "no check"
                # on screen for the rest of the session.
                txt, col = ("Checking for a new version...", SOFT)
                self._watch_updates()
        elif u.error:
            # Never "up to date" when the server did not answer. The three
            # states are kept apart all the way from update.check().
            txt, col = (f"Could not reach the update server at {when}: {u.error}",
                        BAD)
        elif u.available:
            size = f", {u.size / 1e6:.1f} MB" if u.size else ""
            pub = f", published {u.published}" if u.published else ""
            txt, col = (f"{u.latest} is available (you have {u.current}{size}"
                        f"{pub}). Checked at {when}.", GOOD)
        else:
            txt, col = (f"{u.current} is the newest build. Checked at {when}.", DIM)
        self.upd_lbl.configure(text=txt, fg=col)
        avail = bool(u and u.available)
        self.notes_btn.configure(state="normal" if avail and (u.notes or u.url)
                                 else "disabled")
        self.install_btn.configure(state="normal" if avail else "disabled")
        self.upd_src.configure(text=f"manifest: {update.manifest_url()}")

    # -- footer ------------------------------------------------------------

    def _build_footer(self):
        sec = self._section("THIS PANEL")
        self.start_var = tk.BooleanVar(value=bool(self.s.get("open_on_start")))
        self._check(sec, "Open this panel when bgtracker starts",
                    self.start_var, self._on_start_toggle)
        self._sub(sec, f"Settings file: {self.s.path}")
        self._sub(sec, "The gear in the bgtracker window's header reopens this "
                       "panel at any time. Closing it here leaves the overlay "
                       "running.")
        row = tk.Frame(sec, bg=PANEL)
        row.pack(fill="x", pady=(6, 16))
        self._button(row, "Close", self.hide)
        self._button(row, "Quit bgtracker", self.app.quit)

    def _on_start_toggle(self):
        self.s.set("open_on_start", bool(self.start_var.get()))

    # ------------------------------------------------------------- refresh

    def refresh(self):
        """Re-read everything this panel only reports on. Cheap, no network."""
        try:
            self.problem_lbl.configure(
                text="\n".join(self.s.problems) if self.s.problems else "")
            self._refresh_display()
            self._refresh_data()
            self._refresh_updates()
        except Exception:
            traceback.print_exc()
