"""SESSION window - how this sitting is going. Nothing about the board.

Every other window answers "what is on screen right now". This one answers the
question you ask between games: am I up or down today, how many did I play,
how did they finish, and what is this lobby running.

  rating      starting MMR of the session, the current one, and the delta -
              read from game memory through native/msync (MemoryTribes), which
              works AT THE MENU too, so the number is there before the first
              game and after the last one
  games       every game that FINISHED while this session was running, newest
              first, with its placement and hero - the same records collect.py
              writes to data/games.jsonl, recognised the moment the game ends
              instead of waiting for the next `python collect.py`
  tribes      the lobby currently in play

WHAT IT REFUSES TO DO
---------------------
* No MMR is ever guessed. Without the optional memory reader built there is no
  rating on this machine at all, so the whole rating block is replaced by one
  line saying so and the window shows games and placements only. A rating that
  cannot be read right now (Hearthstone closed) shows a dash, never the last
  number dressed up as current.
* A game is counted only when the log PROVES it: the hero draft identifies the
  local player, and that player's last PLAYER_LEADERBOARD_PLACE is the
  placement. A game that cannot be pinned to him (the overlay was started
  mid-game, so his draft is not in the tail) is simply not counted.

THE SESSION ITSELF
------------------
Its start time, starting rating and games live in .overlay.json under this
window's own key, next to its drag offset. Relaunching the overlay RESUMES the
same session; a gap longer than SESSION_GAP_S means the sitting is over and the
next launch starts a fresh one. "reset" in the panel starts one by hand.

WHERE IT SITS
-------------
Top of the LEFT column - the band the hero-draft panel uses, which is empty
every other moment of the game (menu, tavern, fight, between games), i.e.
exactly when a session summary is worth reading. While the draft is on screen
this window steps aside for it and comes back on ``hero_over``, so the two
never cover each other. It only yields while it is still in its default slot:
drag it anywhere else and it stays up all the time, because then the conflict
it was avoiding no longer exists.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time

import bgtracker as bg
import collect

from .base import (ACCENT, AMBER, BAD, DIM, F_CHIP, F_HUGE, F_NAME, F_SUB,
                   F_TITLE, GOOD, LINE, PANEL, SOFT, TEXT, TRIBE_COLOR,
                   TRIBE_TAG, BaseWindow, rrect)

# A sitting idle this long is over: the next launch starts a new session
# instead of resuming a stale one from yesterday.
SESSION_GAP_S = 5 * 3600
# How long the panel stands aside for the hero draft if nothing ever tells it
# the draft ended (the draft panel's own backstop is 75s).
YIELD_MS = 80_000
ROW_H = 21
GAMES_FILE = collect.OUT            # data/games.jsonl - collect.py's records
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# How long a finished game is left to settle before its record is read. It is
# log time, not wall time, so a replay behaves exactly like the live tail.
# Measured on his logs: the FINAL placement is written ~0.1s AFTER the game
# state turns COMPLETE - reading on the COMPLETE line itself scored three real
# games one place too low (4 instead of 3, 5 instead of 4).
SETTLE_S = 2.0
_HHMMSS = re.compile(r"^D (\d+):(\d+):(\d+\.\d+)")


def log_seconds(line):
    """Seconds-into-the-day from a Power.log line stamp, or None."""
    m = _HHMMSS.match(line)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def fmt_age(seconds) -> str:
    m, _ = divmod(max(0, int(seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def place_color(place):
    """Battlegrounds pays the top four; first is its own colour."""
    if not place:
        return DIM
    if place == 1:
        return AMBER
    if place <= 4:
        return GOOD
    if place <= 6:
        return SOFT
    return BAD


class GameScanner:
    """A live Power.log tail -> one collect.py record per finished game.

    collect.py mines finished games out of whole log FILES; this is the same
    parse done incrementally, so a game counts seconds after it ends instead of
    at the next `python collect.py`. The slicing matches collect.games_in
    exactly - a game starts at the last CREATE_GAME line - so both produce the
    same ``game_id`` for the same game and the two sources de-duplicate against
    each other.

    The record is NOT read on the COMPLETE line, and that matters. Measured on
    six real logs: the last PLAYER_LEADERBOARD_PLACE update lands about 0.1s
    AFTER ``STATE value=COMPLETE`` - the sequence is literally PLACE=4,
    COMPLETE, PLACE=3 - so reading there scored three real games one place
    worse than they finished. The game is left to settle for SETTLE_S of LOG
    time (or until the tail goes quiet, or the next game starts) and read then.

    Only lines the extractor can actually use are buffered - one real game runs
    to ~40 MB of log and almost all of it is combat - which keeps a game's
    buffer in the hundreds of lines. The one subtlety is that collect.py ends a
    choose-one block on "any line that is not part of it", so a dropped line
    still has to leave a mark: hence the sentinel in ``_buffer``. With it, this
    filtered incremental parse produced exactly the records collect.py produces
    from the whole file - 23 games over six real logs, every id, hero and
    placement identical.
    """

    KEEP = ("HERO_", "PLAYER_LEADERBOARD_PLACE", "CARDRACE", "PlayerName=",
            "DebugPrintEntityChoices", "DebugPrintEntitiesChosen",
            "m_chosenEntities[", "zone=SETASIDE")
    BLOCK = "DebugPrintEntityChoices"

    def __init__(self, log_name: str):
        self.log_name = log_name
        self.buf: list[str] = []
        self.start = None          # line index of this game's CREATE_GAME
        self.state = "idle"        # idle -> playing -> settling -> done
        self.deadline = None

    def feed(self, line: str, idx: int):
        """One log line in; a finished game's record out, when it is ready."""
        ts = log_seconds(line)
        out = None
        if self.state == "settling":
            # Settled by time (log clock, wrap-safe) or by the next game.
            if "CREATE_GAME" in line or (
                    ts is not None and self.deadline is not None
                    and not self.deadline - 3600 < ts < self.deadline):
                out = self.flush()
        if "CREATE_GAME" in line:
            self.buf, self.start = [], idx
            self.state, self.deadline = "playing", None
            return out
        if self.state in ("playing", "settling"):
            self._buffer(line)
            if self.state == "playing" and "STATE value=COMPLETE" in line:
                self.state = "settling"
                self.deadline = None if ts is None else ts + SETTLE_S
        return out

    def _buffer(self, line):
        if any(k in line for k in self.KEEP):
            self.buf.append(line)
        elif self.buf and self.BLOCK in self.buf[-1]:
            # collect.py closes a choose-one block on the first line that is
            # not part of it. Dropping that line silently would fuse two
            # dialogs into one, so leave a stand-in for it.
            self.buf.append("-")

    def flush(self):
        """The tail caught up: a game waiting to settle has settled."""
        if self.state != "settling":
            return None
        self.state = "done"
        got = collect.extract(self.buf, None)
        if not got or len(got) < 2:
            return None                     # not provably ours - not counted
        # extract() has grown extra fields before (offers, picks) and may
        # again; this window wants the first three and reads them by position
        # so a longer tuple is not a crash.
        hero, place = got[0], got[1]
        tribes = list(got[2]) if len(got) > 2 else []
        return {"id": f"{self.log_name}:{self.start}", "hero": hero,
                "place": place, "tribes": tribes, "at": time.time()}


class _Collector(threading.Thread):
    """Finds finished games off the UI thread and posts them to a queue.

    Two sources, one de-duplicated stream:
      * the live tail of the current Power.log, so a game lands here seconds
        after it ends, while the overlay is running;
      * data/games.jsonl, re-read whenever it changes, so a `python collect.py`
        run in another terminal shows up here too.

    Everything already in games.jsonl when the session started is marked seen
    and never posted: those games belong to earlier sittings.
    """

    daemon = True

    def __init__(self, inbox: queue.Queue):
        super().__init__(name="session-collector")
        self.inbox = inbox
        self.seen: set[str] = set()
        self.error = None
        self._mtime = None

    # -- data/games.jsonl --------------------------------------------------

    def scan_jsonl(self, baseline=False):
        p = GAMES_FILE
        if not p.exists():
            return
        mtime = p.stat().st_mtime
        if mtime == self._mtime:
            return
        self._mtime = mtime
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                g = json.loads(line)
            except ValueError:
                continue
            gid = g.get("game_id")
            if not gid or gid in self.seen:
                continue
            self.seen.add(gid)
            if baseline:
                continue                     # played before this session
            self.inbox.put({"id": gid, "hero": g.get("hero"),
                            "place": g.get("place"),
                            "tribes": g.get("tribes") or [], "at": None})

    # -- the live tail -----------------------------------------------------

    def _post(self, rec):
        if rec is not None and rec["id"] not in self.seen:
            self.seen.add(rec["id"])
            self.inbox.put(rec)

    @staticmethod
    def seek_end(f) -> int:
        """Count the lines already in the file and stop on the last complete
        one. The count is what makes our game ids identical to collect.py's
        (its id is the CREATE_GAME line's index); stopping before a
        half-written line is what stops the tail from splitting one in two."""
        lines, last_nl, pos = 0, 0, 0
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            lines += chunk.count(b"\n")
            i = chunk.rfind(b"\n")
            if i >= 0:
                last_nl = pos + i + 1
            pos += len(chunk)
        f.seek(last_nl)
        return lines

    def run(self):
        try:
            # collect.py rewrites this file while we read it, so the baseline
            # pass must not be the one thing that can kill this thread.
            self.scan_jsonl(baseline=True)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        f = path = scanner = None
        idx = 0
        last_rot = last_jsonl = time.monotonic()
        while True:
            try:
                if f is None:
                    path = bg.newest_power_log()
                    if path is None:
                        time.sleep(5)
                        continue
                    f = open(path, "rb")
                    idx = self.seek_end(f)
                    scanner = GameScanner(path.parent.name)
                pos = f.tell()
                raw = f.readline()
                if raw and raw.endswith(b"\n"):
                    self._post(scanner.feed(raw.decode("utf-8", "ignore"), idx))
                    idx += 1
                    continue
                if raw:
                    f.seek(pos)          # half-written line: wait for the rest
                # Caught up: a game that just ended has had its quiet moment,
                # so read it now rather than waiting for the next game.
                self._post(scanner.flush())
                time.sleep(0.4)
                now = time.monotonic()
                if now - last_rot > 2:
                    last_rot = now
                    newest = bg.newest_power_log()
                    if newest is not None and newest != path:
                        self._post(scanner.flush())
                        f.close()        # Hearthstone relaunched: new log
                        f = None
                if now - last_jsonl > 20:
                    last_jsonl = now
                    self.scan_jsonl()
            except Exception as e:                    # never take the UI down
                self.error = f"{type(e).__name__}: {e}"
                try:
                    if f is not None:
                        f.close()
                except Exception:
                    pass
                f = None
                time.sleep(5)


class SessionWindow(BaseWindow):
    KEY = "session"
    TITLE = "SESSION"
    COLUMN = "left"
    DY = 70
    RESERVE = 256
    MAX_H = 256
    EVENTS = ("lobby", "hero", "hero_over")

    def __init__(self, app):
        super().__init__(app)
        self.tribes, self.exact = set(), False
        self.mmr = None                 # rating right now
        self.start_mmr = None           # rating when this session started
        self.games: list[dict] = []     # oldest first; drawn newest first
        self._probe = None              # rating from our own msync call
        self._memory = None             # the overlay's MemoryTribes thread
        self._names = None
        self._inbox = queue.Queue()
        self._collector = None
        self._yielded = False
        self._unyield_timer = None
        self._hits = []
        self._started = False

        saved = app.pos.get(self.KEY)
        now = time.time()
        start = saved.get("start")
        touched = saved.get("updated") or start
        if (isinstance(start, (int, float)) and isinstance(touched, (int, float))
                and start <= now and now - touched <= SESSION_GAP_S):
            self.start_ts = start                    # same sitting, resumed
            self.start_mmr = saved.get("start_mmr")
            self.games = [g for g in (saved.get("games") or [])
                          if isinstance(g, dict)]
        else:
            self.start_ts = now
            self._persist()
        self.show()
        if not self.headless:
            # after() fires only under a running Tk loop, so the workers start
            # in the real overlay and never in the headless render tests.
            self.after(1200, self._start_workers)

    # ------------------------------------------------------------- workers

    def _start_workers(self):
        if self._started:
            return
        self._started = True
        self._collector = _Collector(self._inbox)
        self._collector.start()
        threading.Thread(target=self._probe_loop, name="session-rating",
                         daemon=True).start()
        self._poll()

    def _find_memory(self):
        """The MemoryTribes the reader already runs - reuse it rather than
        starting a second msync (a stray helper outliving the overlay is what
        locks the binary on the next build)."""
        if self._memory is not None and self._memory.is_alive():
            return self._memory
        self._memory = None
        for t in threading.enumerate():
            if isinstance(t, bg.MemoryTribes):
                self._memory = t
                break
        return self._memory

    def _probe_loop(self):
        """Fallback only: read the rating ourselves when nothing else is.

        The live overlay always has a MemoryTribes running, so this never fires
        there; it exists so the window still knows the rating when the reader
        is replaying a log. One-shot calls that exit on their own - never a
        --watch child that could be orphaned.
        """
        while True:
            time.sleep(6)
            try:
                if (self._find_memory() is not None or self.app.rect is None
                        or not bg.MemoryTribes.available()):
                    continue
                out = subprocess.run([str(bg.MSYNC_EXE)], capture_output=True,
                                     text=True, timeout=10,
                                     creationflags=_CREATE_NO_WINDOW)
                for line in reversed((out.stdout or "").splitlines()):
                    d = json.loads(line)
                    if d.get("rating", -1) > 0:
                        self._probe = d["rating"]
                    break
            except Exception:
                pass            # no rating is a dash on screen, never a guess

    def _rating(self):
        mem = self._find_memory()
        if mem is not None and mem.rating:
            return mem.rating
        return self._probe

    # -------------------------------------------------------------- polling

    def _poll(self):
        try:
            self._drain()
        except Exception:
            self.errors += 1
        finally:
            try:
                if not self.headless:
                    self.after(1000, self._poll)
            except Exception:
                pass            # the overlay is shutting down under us

    def _drain(self):
        """Take whatever the collector found, sample the rating, repaint."""
        changed = False
        have = {g.get("id") for g in self.games}
        while True:
            try:
                rec = self._inbox.get_nowait()
            except queue.Empty:
                break
            if rec.get("id") in have:
                continue
            have.add(rec["id"])
            self.games.append(rec)
            changed = True
        r = self._rating()
        if r and r != self.mmr:
            self.mmr = r
            changed = True
            if self.start_mmr is None:
                self.start_mmr = r          # the first rating we could read
        if changed:
            self._persist()
        if self.is_open:
            self.redraw()                   # at least the clock has moved on
        return changed

    def _persist(self):
        """The session itself lives in .overlay.json, under this window's own
        key beside its drag offset - so closing the overlay between games does
        not lose the sitting."""
        try:
            self.app.pos.set(self.KEY, start=self.start_ts,
                             start_mmr=self.start_mmr,
                             games=self.games[-40:], updated=time.time())
        except Exception:
            pass                   # a session that cannot be saved still runs

    # --------------------------------------------------------------- events

    def on_event(self, name, payload):
        if name == "lobby":
            self.tribes = payload.get("seen") or set()
            self.exact = payload.get("exact", False)
            if not self._yielded:
                self.show()
        elif name == "hero":
            # The draft panel wants this exact band. Stand aside - but only
            # while we are still in the default slot it would cover.
            if not self.dx and not self.dy and not self._yielded:
                self._yielded = True
                self.hide()
                if not self.headless:
                    self._unyield_timer = self.after(YIELD_MS, self._unyield)
        elif name == "hero_over":
            self._unyield()

    def _unyield(self):
        if self._unyield_timer is not None:
            try:
                self.after_cancel(self._unyield_timer)
            except Exception:
                pass
            self._unyield_timer = None
        self._yielded = False
        self.show()

    def reset(self):
        """A new game began. The session outlives games - only the lobby's
        tribes belong to the game that just ended."""
        self.tribes, self.exact = set(), False
        if not self._yielded:
            self.show()

    # ------------------------------------------------------------- clicking

    def on_click(self, x, y):
        for key, x1, y1, x2, y2 in self._hits:
            if x1 <= x <= x2 and y1 <= y <= y2:
                if key == "reset":
                    self.start_ts = time.time()
                    self.start_mmr = self.mmr
                    self.games = []
                    self._persist()
                    self.redraw()
                return True
        return False

    # -------------------------------------------------------------- drawing

    def name_of(self, card_id):
        if self._names is None:
            self._names = bg.card_names()
        return self._names.get(card_id) or card_id or "unknown hero"

    def draw(self, c):
        self._hits = []
        y = self.header(c, fmt_age(time.time() - self.start_ts), DIM,
                        dot=GOOD if self.games else DIM)
        y = self._draw_rating(c, y)
        y = self._draw_games(c, y)
        return self._draw_tribes(c, y)

    def _draw_rating(self, c, y):
        if not bg.MemoryTribes.available():
            # No memory reader on this machine: there is no rating to show, so
            # say that once instead of leaving a hole where a number goes.
            c.create_text(14, y + 9, anchor="w", fill=DIM, font=F_SUB,
                          text="MMR needs the optional memory reader")
            return y + 22

        cur, start = self.mmr, self.start_mmr
        c.create_text(14, y + 15, anchor="w", font=F_HUGE,
                      text=f"{cur:,}" if cur else "—",
                      fill=TEXT if cur else DIM)
        if cur is not None and start is not None:
            d = cur - start
            col = GOOD if d > 0 else BAD if d < 0 else DIM
            rrect(c, self.WIDTH - 84, y + 4, self.WIDTH - 12, y + 26, 8,
                  fill=PANEL, outline=col)
            c.create_text(self.WIDTH - 48, y + 15, font=F_NAME, fill=col,
                          text=f"{d:+,}" if d else "even")
        if start is None:
            sub = "waiting for a rating read"
        elif cur is None:
            sub = f"session started at {start:,}"
        else:
            sub = f"from {start:,} this session"
        c.create_text(14, y + 34, text=sub, anchor="w", fill=DIM, font=F_SUB)
        return y + 46

    def _rows_that_fit(self, y, extra=0):
        """How many game rows fit without spilling past this window's band.
        The cap is structural: nothing may be painted below the panel."""
        room = self.MAX_H - (y + self._tribes_h() + 8 + extra)
        return max(0, int(room // ROW_H))

    def _draw_games(self, c, y):
        games = list(reversed(self.games))
        placed = [g["place"] for g in games if g.get("place")]
        label = f"GAMES ({len(games)})" if games else "GAMES"
        if placed:
            label += f"  ·  avg {sum(placed) / len(placed):.1f}"
        c.create_text(14, y + 7, text=label, anchor="w", fill=DIM, font=F_TITLE)
        rx2 = self.WIDTH - 12
        c.create_text(rx2 - 2, y + 7, text="reset ›", anchor="e",
                      fill=ACCENT, font=F_SUB)
        self._hits.append(("reset", rx2 - 46, y, rx2, y + 15))
        y += 18

        if not games:
            c.create_text(14, y + 8, anchor="w", fill=DIM, font=F_SUB,
                          text="no finished games yet this session")
            return y + 20

        fit = self._rows_that_fit(y)
        if len(games) > fit:
            fit = self._rows_that_fit(y, extra=16)     # room for "+N earlier"
        for g in games[:fit]:
            place = g.get("place")
            rrect(c, 14, y + 2, 36, y + 18, 5, fill=place_color(place),
                  outline="")
            c.create_text(25, y + 10, text=str(place) if place else "?",
                          fill="#101116", font=F_CHIP)
            x = 44
            icon = self.app.art.icon(g.get("hero"), 16)
            if icon is not None:
                try:
                    c.create_image(x, y + 10, image=icon, anchor="w")
                    x += 22
                except Exception:
                    pass        # art is decoration: never lose the row over it
            c.create_text(x, y + 10, text=self.name_of(g.get("hero"))[:24],
                          anchor="w", fill=TEXT if place else SOFT, font=F_SUB)
            if g.get("at"):
                c.create_text(self.WIDTH - 14, y + 10, anchor="e", fill=DIM,
                              font=F_CHIP,
                              text=time.strftime("%H:%M",
                                                 time.localtime(g["at"])))
            y += ROW_H
        rest = len(games) - fit
        if rest > 0:
            c.create_text(14, y + 7, text=f"+{rest} earlier this session",
                          anchor="w", fill=DIM, font=F_CHIP)
            y += 16
        return y

    def _tribes_h(self):
        return 40

    def _draw_tribes(self, c, y):
        c.create_text(14, y + 6, anchor="w", fill=DIM, font=F_CHIP,
                      text="TRIBES IN LOBBY" if self.exact
                      else ("TRIBES SEEN" if self.tribes else "TRIBES"))
        y += 14
        x = 12.0
        for t in bg.TRIBES:
            on = t in self.tribes
            rrect(c, x, y, x + 27, y + 15, 7,
                  fill=TRIBE_COLOR[t] if on else PANEL,
                  outline="" if on else LINE)
            c.create_text(x + 13.5, y + 8, text=TRIBE_TAG[t], font=F_CHIP,
                          fill="#101116" if on else "#4a4f59")
            x += 29.5
        return y + 15 + 8
